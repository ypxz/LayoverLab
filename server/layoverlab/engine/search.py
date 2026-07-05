"""Top-K cheapest itinerary search over a time-expanded (airport, day) graph.

Plans at day granularity: the cache stores the cheapest fare per origin/dest/day.
Real flight times are resolved later by the verification pass (engine.verify).

v2: multi-criteria labels (cost, travel days, legs) with a Pareto frontier per
(airport, day) node, a sort knob (cheapest|fastest|best), a diversity pass over
the top-K, and an O(n log n) round-trip pairing via a sparse-table range-min
index over inbound departure days.
"""

import heapq
import itertools
import logging
import math
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from layoverlab.engine.graph import FareSlice, load_slice
from layoverlab.engine.models import Itinerary, Leg, SearchParams, Stopover
from layoverlab.engine.warnings import build_warnings
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

MAX_POPS = 500_000  # hard safety valve
MAX_PER_SIGNATURE = 2
RAW_RESULT_FACTOR = 3


def _min_gap_days(stop_min_hours: int) -> int:
    return math.ceil(stop_min_hours / 24) if stop_min_hours >= 24 else 0


def _night_cost_cents() -> int:
    return get_settings().engine_night_cost_cents


def _itin_travel_days(itin: Itinerary) -> int:
    return (itin.legs[-1].dep_date - itin.legs[0].dep_date).days


def _sort_key(sort: str, night_cost: int):
    def key(itin: Itinerary) -> tuple[int, int]:
        days = _itin_travel_days(itin)
        if sort == "fastest":
            return (days, itin.total_cents)
        if sort == "best":
            nights = sum(s.nights for s in itin.stopovers)
            return (itin.total_cents + nights * night_cost, itin.total_cents)
        return (itin.total_cents, days)

    return key


def _label_priority(sort: str, night_cost: int, cost: int, days: int) -> tuple[int, int]:
    if sort == "fastest":
        return (days, cost)
    if sort == "best":
        return (cost + days * night_cost, cost)
    return (cost, days)


def _dominates(a: tuple[int, int, int], b: tuple[int, int, int]) -> bool:
    return a[0] <= b[0] and a[1] <= b[1] and a[2] <= b[2] and a != b


def _frontier_admit(
    frontier: dict[tuple[str, int], list[tuple[int, int, int]]],
    node: tuple[str, int],
    label: tuple[int, int, int],
) -> bool:
    labels = frontier.get(node)
    if labels is None:
        frontier[node] = [label]
        return True
    for existing in labels:
        if existing == label or _dominates(existing, label):
            return False
    frontier[node] = [ex for ex in labels if not _dominates(label, ex)]
    frontier[node].append(label)
    return True


def _build_itinerary(fslice: FareSlice, legs: list[Leg], origin_country: str | None) -> Itinerary:
    stopovers = []
    for prev, nxt in itertools.pairwise(legs):
        nights = (nxt.dep_date - prev.dep_date).days
        if nights >= 1:
            stopovers.append(Stopover(iata=prev.dest, nights=nights))
    itin = Itinerary(
        legs=legs,
        total_cents=sum(leg.price_cents for leg in legs),
        currency="EUR",
        stopovers=stopovers,
        warnings=[],
        verified=False,
    )
    itin.warnings.extend(build_warnings(itin, fslice, origin_country))
    return itin


def _diversify(itins: list[Itinerary], top_k: int) -> list[Itinerary]:
    picked: list[Itinerary] = []
    deferred: list[Itinerary] = []
    per_sig: dict[tuple[str, ...], int] = {}
    seen_vias: set[str] = set()
    for itin in itins:
        sig = itin.signature
        if per_sig.get(sig, 0) >= MAX_PER_SIGNATURE:
            continue
        vias = set(sig[1:-1])
        if not vias or not vias.issubset(seen_vias):
            picked.append(itin)
            per_sig[sig] = per_sig.get(sig, 0) + 1
            seen_vias |= vias
        else:
            deferred.append(itin)
        if len(picked) == top_k:
            return picked
    for itin in deferred:
        if len(picked) == top_k:
            break
        if per_sig.get(itin.signature, 0) < MAX_PER_SIGNATURE:
            picked.append(itin)
            per_sig[itin.signature] = per_sig.get(itin.signature, 0) + 1
    return picked


def _search_oneway(
    fslice: FareSlice,
    params: SearchParams,
    needed: int,
    per_sig_days: int = MAX_PER_SIGNATURE,
) -> list[Itinerary]:
    dest_set = set(fslice.cluster_of(params.dest))
    window_days = (params.date_to - params.date_from).days
    min_gap = _min_gap_days(params.stop_min_hours)
    max_gap = max(params.stop_max_days, min_gap)
    max_legs = params.max_stops + 1
    night_cost = _night_cost_cents()
    sort = params.sort

    dep_days: dict[str, list[int]] = {}
    for airport, day in fslice.flights:
        dep_days.setdefault(airport, []).append(day)
    for days in dep_days.values():
        days.sort()

    counter = itertools.count()  # tie-breaker for heap
    heap: list = []
    frontier: dict[tuple[str, int], list[tuple[int, int, int]]] = {}

    start_day = fslice.day_index(params.date_from)
    for day in range(start_day, start_day + window_days + 1):
        heapq.heappush(heap, ((0, 0), next(counter), 0, day, day, params.origin, ()))

    raw_needed = max(needed, params.top_k) * RAW_RESULT_FACTOR
    results: dict[tuple[tuple[str, ...], int], Itinerary] = {}
    sig_days: dict[tuple[str, ...], int] = {}
    origin_country = fslice.airport_country.get(params.origin)
    pops = 0

    while heap and len(results) < raw_needed and pops < MAX_POPS:
        _, _, cost, day, path_start, airport, path = heapq.heappop(heap)
        pops += 1
        legs_used = len(path)
        label = (cost, day - path_start, legs_used)
        node = (airport, day)
        labels = frontier.get(node)
        if labels is not None and any(
            ex != label and _dominates(ex, label) for ex in labels
        ):
            continue

        if airport in dest_set and legs_used > 0:
            legs = list(path)
            signature = tuple([legs[0].origin, *[leg.dest for leg in legs]])
            key = (signature, path_start)
            if key not in results and sig_days.get(signature, 0) < per_sig_days:
                results[key] = _build_itinerary(fslice, legs, origin_country)
                sig_days[signature] = sig_days.get(signature, 0) + 1
            continue  # do not expand past the destination

        if legs_used >= max_legs:
            continue
        visited = {airport, *(leg.origin for leg in path)}

        if legs_used == 0:
            gap_lo, gap_hi = day, day
        else:
            gap_lo, gap_hi = day + min_gap, day + max_gap
        gap_hi = min(gap_hi, fslice.horizon_days)

        airport_days = dep_days.get(airport)
        if airport_days:
            lo = bisect_left(airport_days, gap_lo)
            hi = bisect_right(airport_days, gap_hi)
            for dep_day in airport_days[lo:hi]:
                for edge in fslice.flights[(airport, dep_day)]:
                    if edge.dest in visited:
                        continue
                    new_cost = cost + edge.price_cents
                    new_start = dep_day if legs_used == 0 else path_start
                    new_label = (new_cost, dep_day - new_start, legs_used + 1)
                    if not _frontier_admit(frontier, (edge.dest, dep_day), new_label):
                        continue
                    leg = Leg(
                        origin=airport,
                        dest=edge.dest,
                        dep_date=fslice.date_of(dep_day),
                        mode="flight",
                        price_cents=edge.price_cents,
                        source=edge.source,
                        deep_link=edge.deep_link,
                        fetched_at=edge.fetched_at,
                    )
                    priority = _label_priority(sort, night_cost, new_cost, dep_day - new_start)
                    heapq.heappush(
                        heap,
                        (priority, next(counter), new_cost, dep_day, new_start, edge.dest, (*path, leg)),
                    )

        ground_edges = fslice.ground.get(airport)
        if ground_edges:
            for dep_day in range(gap_lo, gap_hi + 1):
                for gedge in ground_edges:
                    if gedge.dest in visited:
                        continue
                    arrive_day = dep_day + gedge.day_offset
                    if arrive_day > fslice.horizon_days:
                        continue
                    new_cost = cost + gedge.price_cents
                    new_start = dep_day if legs_used == 0 else path_start
                    new_label = (new_cost, arrive_day - new_start, legs_used + 1)
                    if not _frontier_admit(frontier, (gedge.dest, arrive_day), new_label):
                        continue
                    leg = Leg(
                        origin=airport,
                        dest=gedge.dest,
                        dep_date=fslice.date_of(dep_day),
                        mode="ground",
                        price_cents=gedge.price_cents,
                        source=gedge.mode,
                        deep_link=None,
                        fetched_at=datetime.now(timezone.utc),
                    )
                    priority = _label_priority(sort, night_cost, new_cost, arrive_day - new_start)
                    heapq.heappush(
                        heap,
                        (
                            priority,
                            next(counter),
                            new_cost,
                            arrive_day,
                            new_start,
                            gedge.dest,
                            (*path, leg),
                        ),
                    )

    itins = sorted(results.values(), key=_sort_key(sort, night_cost))
    log.info("oneway %s->%s: %d itineraries (%d pops)", params.origin, params.dest, len(itins), pops)
    return itins[:needed]


class _RangeMinIndex:
    """Sparse-table range-min over a list of comparable values; O(n log n) build, O(1) query."""

    def __init__(self, vals: list) -> None:
        n = len(vals)
        self.vals = vals
        self.logs = [0] * (n + 1)
        for i in range(2, n + 1):
            self.logs[i] = self.logs[i // 2] + 1
        self.table: list[list[int]] = [list(range(n))]
        k = 1
        while (1 << k) <= n:
            prev = self.table[-1]
            half = 1 << (k - 1)
            row = []
            for i in range(n - (1 << k) + 1):
                a, b = prev[i], prev[i + half]
                row.append(a if vals[a] <= vals[b] else b)
            self.table.append(row)
            k += 1

    def argmin(self, lo: int, hi: int) -> int:
        k = self.logs[hi - lo + 1]
        a = self.table[k][lo]
        b = self.table[k][hi - (1 << k) + 1]
        return a if self.vals[a] <= self.vals[b] else b


def _pair_round_trips(
    outbound: list[Itinerary],
    inbound: list[Itinerary],
    trip_min: int,
    trip_max: int,
) -> list[Itinerary]:
    if not outbound or not inbound:
        return []
    inbound_sorted = sorted(inbound, key=lambda i: i.legs[0].dep_date)
    dep_ordinals = [i.legs[0].dep_date.toordinal() for i in inbound_sorted]
    index = _RangeMinIndex([i.total_cents for i in inbound_sorted])

    combos: list[Itinerary] = []
    for out in outbound:
        out_dep = out.legs[0].dep_date.toordinal()
        out_arr = out.legs[-1].dep_date.toordinal()
        lo_day = max(out_dep + trip_min, out_arr + 1)
        hi_day = out_dep + trip_max
        lo = bisect_left(dep_ordinals, lo_day)
        hi = bisect_right(dep_ordinals, hi_day) - 1
        if lo > hi:
            continue
        ret = inbound_sorted[index.argmin(lo, hi)]
        combos.append(
            Itinerary(
                legs=[*out.legs, *ret.legs],
                total_cents=out.total_cents + ret.total_cents,
                currency="EUR",
                stopovers=[*out.stopovers, *ret.stopovers],
                warnings=sorted(set(out.warnings) | set(ret.warnings)),
                verified=False,
            )
        )
    return combos


def search(params: SearchParams, session: Session) -> list[Itinerary]:
    extra_days = params.max_stops * params.stop_max_days + 2
    night_cost = _night_cost_cents()
    if not params.round_trip:
        fslice = load_slice(session, params.date_from, params.date_to, extra_days)
        raw = _search_oneway(fslice, params, params.top_k * RAW_RESULT_FACTOR)
        return _diversify(raw, params.top_k)

    trip_min = params.trip_min_days or 1
    trip_max = params.trip_max_days or 30
    inbound_to = params.date_to + timedelta(days=trip_max)
    fslice = load_slice(session, params.date_from, inbound_to, extra_days)

    per_sig_days = max(MAX_PER_SIGNATURE, trip_max - trip_min + 1)
    out_params = params.model_copy(update={"round_trip": False})
    outbound = _search_oneway(
        fslice, out_params, params.top_k * RAW_RESULT_FACTOR, per_sig_days=per_sig_days
    )
    in_params = params.model_copy(
        update={
            "round_trip": False,
            "origin": params.dest,
            "dest": params.origin,
            "date_from": params.date_from + timedelta(days=trip_min),
            "date_to": inbound_to,
        }
    )
    inbound = _search_oneway(
        fslice, in_params, params.top_k * RAW_RESULT_FACTOR, per_sig_days=per_sig_days
    )

    combos = _pair_round_trips(outbound, inbound, trip_min, trip_max)
    combos.sort(key=_sort_key(params.sort, night_cost))
    return _diversify(combos, params.top_k)
