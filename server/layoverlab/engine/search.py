"""Top-K cheapest itinerary search over a time-expanded (airport, day) graph.

Plans at day granularity: the cache stores the cheapest fare per origin/dest/day.
Real flight times are resolved later by the verification pass (engine.verify).
"""

import heapq
import itertools
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from layoverlab.engine.graph import FareSlice, load_slice
from layoverlab.engine.models import Itinerary, Leg, SearchParams, Stopover
from layoverlab.engine.warnings import build_warnings

log = logging.getLogger(__name__)

MAX_POPS = 500_000  # hard safety valve


def _min_gap_days(stop_min_hours: int) -> int:
    return math.ceil(stop_min_hours / 24) if stop_min_hours >= 24 else 0


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


def _search_oneway(fslice: FareSlice, params: SearchParams, needed: int) -> list[Itinerary]:
    dest_set = set(fslice.cluster_of(params.dest))
    window_days = (params.date_to - params.date_from).days
    min_gap = _min_gap_days(params.stop_min_hours)
    max_gap = max(params.stop_max_days, min_gap)
    max_legs = params.max_stops + 1

    counter = itertools.count()  # tie-breaker for heap
    heap: list = []
    best_cost: dict[tuple[str, int, int], int] = {}

    start_day = fslice.day_index(params.date_from)
    for day in range(start_day, start_day + window_days + 1):
        heapq.heappush(heap, (0, next(counter), params.origin, day, ()))

    results: dict[tuple[str, ...], Itinerary] = {}
    origin_country = fslice.airport_country.get(params.origin)
    pops = 0

    while heap and len(results) < needed and pops < MAX_POPS:
        cost, _, airport, day, path = heapq.heappop(heap)
        pops += 1
        legs_used = len(path)
        state = (airport, day, legs_used)
        if best_cost.get(state, cost) < cost:
            continue
        best_cost[state] = cost

        if airport in dest_set and legs_used > 0:
            legs = list(path)
            signature = tuple([legs[0].origin, *[leg.dest for leg in legs]])
            if signature not in results:
                results[signature] = _build_itinerary(fslice, legs, origin_country)
            continue  # do not expand past the destination

        if legs_used >= max_legs:
            continue
        visited = {airport, *(leg.origin for leg in path)}

        gap_range = [0] if legs_used == 0 else range(min_gap, max_gap + 1)
        for gap in gap_range:
            dep_day = day + gap
            if dep_day > fslice.horizon_days:
                break
            for edge in fslice.flights.get((airport, dep_day), []):
                if edge.dest in visited:
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
                new_cost = cost + edge.price_cents
                new_state = (edge.dest, dep_day, legs_used + 1)
                if best_cost.get(new_state, new_cost + 1) <= new_cost:
                    continue
                heapq.heappush(heap, (new_cost, next(counter), edge.dest, dep_day, (*path, leg)))
            for gedge in fslice.ground.get(airport, []):
                if gedge.dest in visited:
                    continue
                arrive_day = dep_day + gedge.day_offset
                if arrive_day > fslice.horizon_days:
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
                new_cost = cost + gedge.price_cents
                new_state = (gedge.dest, arrive_day, legs_used + 1)
                if best_cost.get(new_state, new_cost + 1) <= new_cost:
                    continue
                heapq.heappush(heap, (new_cost, next(counter), gedge.dest, arrive_day, (*path, leg)))

    itins = sorted(results.values(), key=lambda i: i.total_cents)
    log.info("oneway %s->%s: %d itineraries (%d pops)", params.origin, params.dest, len(itins), pops)
    return itins[:needed]


def search(params: SearchParams, session: Session) -> list[Itinerary]:
    extra_days = params.max_stops * params.stop_max_days + 2
    if not params.round_trip:
        fslice = load_slice(session, params.date_from, params.date_to, extra_days)
        return _search_oneway(fslice, params, params.top_k)

    trip_min = params.trip_min_days or 1
    trip_max = params.trip_max_days or 30
    inbound_to = params.date_to + timedelta(days=trip_max)
    fslice = load_slice(session, params.date_from, inbound_to, extra_days)

    out_params = params.model_copy(update={"round_trip": False})
    outbound = _search_oneway(fslice, out_params, params.top_k)
    in_params = params.model_copy(
        update={
            "round_trip": False,
            "origin": params.dest,
            "dest": params.origin,
            "date_from": params.date_from + timedelta(days=trip_min),
            "date_to": inbound_to,
        }
    )
    inbound = _search_oneway(fslice, in_params, params.top_k)

    combos: list[Itinerary] = []
    for out in outbound:
        out_dep = out.legs[0].dep_date
        out_arr = out.legs[-1].dep_date
        for ret in inbound:
            ret_dep = ret.legs[0].dep_date
            trip_days = (ret_dep - out_dep).days
            if ret_dep <= out_arr or trip_days < trip_min or trip_days > trip_max:
                continue
            legs = [*out.legs, *ret.legs]
            combined = Itinerary(
                legs=legs,
                total_cents=out.total_cents + ret.total_cents,
                currency="EUR",
                stopovers=[*out.stopovers, *ret.stopovers],
                warnings=sorted(set(out.warnings) | set(ret.warnings)),
                verified=False,
            )
            combos.append(combined)
    combos.sort(key=lambda i: i.total_cents)
    return combos[: params.top_k]
