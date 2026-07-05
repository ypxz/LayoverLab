import itertools
import random
import string
import time
from datetime import date, datetime, timezone

import pytest

from layoverlab.engine.graph import FareSlice, FlightEdge
from layoverlab.engine.models import SearchParams
from layoverlab.engine.search import _diversify, _search_oneway

D0 = date(2026, 8, 1)
N_AIRPORTS = 500
N_FARES = 50_000
WINDOW_DAYS = 60


def build_fixture(seed: int = 42) -> FareSlice:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    airports = list(
        itertools.islice(
            ("".join(p) for p in itertools.product(string.ascii_uppercase, repeat=3)),
            N_AIRPORTS,
        )
    )
    fslice = FareSlice(date_from=D0, horizon_days=WINDOW_DAYS + 23)
    seen: set[tuple[str, str, int]] = set()
    while len(seen) < N_FARES:
        origin, dest = rng.sample(airports, 2)
        day = rng.randrange(WINDOW_DAYS)
        key = (origin, dest, day)
        if key in seen:
            continue
        seen.add(key)
        fslice.flights.setdefault((origin, day), []).append(
            FlightEdge(
                dest=dest,
                price_cents=rng.randrange(1_000, 40_000),
                source="fixture",
                deep_link=None,
                fetched_at=now,
            )
        )
    for iata in airports:
        fslice.airport_country[iata] = "DE"
        fslice.airport_cluster[iata] = None
    return fslice


@pytest.mark.perf
def test_p95_single_search_under_one_second():
    fslice = build_fixture()
    rng = random.Random(7)
    airports = sorted({a for a, _ in fslice.flights})
    timings: list[float] = []
    for _ in range(20):
        origin, dest = rng.sample(airports, 2)
        params = SearchParams(
            origin=origin, dest=dest,
            date_from=D0, date_to=date(2026, 8, 30),
            stop_min_hours=4, stop_max_days=7, max_stops=3, top_k=10,
        )
        start = time.perf_counter()
        raw = _search_oneway(fslice, params, params.top_k * 3)
        _diversify(raw, params.top_k)
        timings.append(time.perf_counter() - start)
    timings.sort()
    p95 = timings[int(len(timings) * 0.95) - 1]
    assert p95 < 1.0, f"p95={p95:.3f}s timings={[f'{t:.3f}' for t in timings]}"
