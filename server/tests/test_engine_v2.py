import random
from datetime import date, datetime, timedelta, timezone

from layoverlab.engine.models import Itinerary, Leg, SearchParams
from layoverlab.engine.search import _pair_round_trips, search
from tests.conftest import add_airport, add_fare, add_ground

D = date(2026, 8, 10)
NOW = datetime.now(timezone.utc)


def _params(**overrides) -> SearchParams:
    defaults = dict(
        origin="BER", dest="BKK", date_from=D, date_to=D,
        stop_min_hours=4, stop_max_days=7, max_stops=3, top_k=5,
    )
    defaults.update(overrides)
    return SearchParams(**defaults)


def test_pareto_keeps_cheap_slow_and_fast_pricey(session):
    for iata in ["AAA", "BBB", "CCC"]:
        add_airport(session, iata)
    add_fare(session, "AAA", "CCC", D, 80000)                     # direct: fast but pricey
    add_fare(session, "AAA", "BBB", D, 10000)
    add_fare(session, "BBB", "CCC", date(2026, 8, 13), 5000)      # 3-night stop: cheap but slow
    results = search(_params(origin="AAA", dest="CCC"), session)

    totals = {tuple(leg.dest for leg in i.legs): i.total_cents for i in results}
    assert totals[("BBB", "CCC")] == 15000
    assert totals[("CCC",)] == 80000
    assert results[0].total_cents == 15000


def test_sort_fastest_orders_by_travel_days(session):
    for iata in ["AAA", "BBB", "CCC"]:
        add_airport(session, iata)
    add_fare(session, "AAA", "CCC", D, 80000)
    add_fare(session, "AAA", "BBB", D, 10000)
    add_fare(session, "BBB", "CCC", date(2026, 8, 13), 5000)
    results = search(_params(origin="AAA", dest="CCC", sort="fastest"), session)

    assert len(results) >= 2
    assert [leg.dest for leg in results[0].legs] == ["CCC"]
    days = [(i.legs[-1].dep_date - i.legs[0].dep_date).days for i in results]
    assert days == sorted(days)


def test_sort_best_trades_nights_for_cost(session, monkeypatch):
    monkeypatch.setenv("ENGINE_NIGHT_COST_CENTS", "50000")
    from layoverlab.settings import get_settings

    get_settings.cache_clear()
    try:
        for iata in ["AAA", "BBB", "CCC"]:
            add_airport(session, iata)
        add_fare(session, "AAA", "CCC", D, 80000)
        add_fare(session, "AAA", "BBB", D, 10000)
        add_fare(session, "BBB", "CCC", date(2026, 8, 13), 5000)
        results = search(_params(origin="AAA", dest="CCC", sort="best"), session)
        assert [leg.dest for leg in results[0].legs] == ["CCC"]
    finally:
        get_settings.cache_clear()


def test_diversity_max_two_per_signature(session):
    add_airport(session, "AAA")
    add_airport(session, "BBB")
    for offset in range(5):
        add_fare(session, "AAA", "BBB", date(2026, 8, 10 + offset), 1000 + offset)
    results = search(
        _params(
            origin="AAA", dest="BBB",
            date_from=date(2026, 8, 10), date_to=date(2026, 8, 20), top_k=10,
        ),
        session,
    )
    assert results
    assert len(results) == 2
    assert len({i.legs[0].dep_date for i in results}) == 2


def test_diversity_prefers_distinct_vias(session):
    for iata in ["AAA", "BBB", "CCC", "DDD"]:
        add_airport(session, iata)
    add_fare(session, "AAA", "BBB", D, 1000)
    add_fare(session, "BBB", "DDD", date(2026, 8, 11), 1000)
    add_fare(session, "AAA", "BBB", date(2026, 8, 11), 1100)
    add_fare(session, "BBB", "DDD", date(2026, 8, 12), 1100)
    add_fare(session, "AAA", "CCC", D, 5000)
    add_fare(session, "CCC", "DDD", D, 5000)
    results = search(
        _params(origin="AAA", dest="DDD", top_k=3, date_to=date(2026, 8, 11)), session
    )

    vias = [i.legs[0].dest for i in results]
    assert "CCC" in vias[:2]


def test_mid_route_cluster_hop(session):
    add_airport(session, "BER", "DE")
    add_airport(session, "LGW", "GB", cluster="LON")
    add_airport(session, "STN", "GB", cluster="LON")
    add_airport(session, "BKK", "TH")
    add_fare(session, "BER", "BKK", D, 90000)
    add_fare(session, "BER", "LGW", D, 3000)
    add_fare(session, "STN", "BKK", date(2026, 8, 11), 5000)
    results = search(_params(), session)

    assert results
    best = results[0]
    assert [(leg.origin, leg.dest, leg.mode) for leg in best.legs] == [
        ("BER", "LGW", "flight"),
        ("LGW", "STN", "ground"),
        ("STN", "BKK", "flight"),
    ]
    assert best.total_cents == 3000 + 2000 + 5000


def test_round_trip_cheapest_days_incompatible_regression(session):
    add_airport(session, "BER")
    add_airport(session, "LIS", "PT")
    add_fare(session, "BER", "LIS", date(2026, 8, 20), 4000)   # cheapest outbound: late
    add_fare(session, "BER", "LIS", date(2026, 8, 10), 5000)
    add_fare(session, "LIS", "BER", date(2026, 8, 15), 3000)   # cheapest inbound: only fits early outbound
    results = search(
        _params(
            dest="LIS", round_trip=True, trip_min_days=3, trip_max_days=8,
            date_from=date(2026, 8, 10), date_to=date(2026, 8, 20),
        ),
        session,
    )

    assert results
    best = results[0]
    assert best.legs[0].dep_date == date(2026, 8, 10)
    assert best.legs[-1].dep_date == date(2026, 8, 15)
    assert best.total_cents == 8000


def _itin(origin: str, dest: str, dep: date, cents: int) -> Itinerary:
    leg = Leg(
        origin=origin, dest=dest, dep_date=dep, mode="flight",
        price_cents=cents, source="syn", deep_link=None, fetched_at=NOW,
    )
    return Itinerary(legs=[leg], total_cents=cents, currency="EUR",
                     stopovers=[], warnings=[], verified=False)


def _brute_force(outbound, inbound, trip_min, trip_max):
    combos = []
    for out in outbound:
        out_dep = out.legs[0].dep_date
        out_arr = out.legs[-1].dep_date
        best = None
        for ret in inbound:
            ret_dep = ret.legs[0].dep_date
            trip_days = (ret_dep - out_dep).days
            if ret_dep <= out_arr or trip_days < trip_min or trip_days > trip_max:
                continue
            if best is None or ret.total_cents < best.total_cents:
                best = ret
        if best is not None:
            combos.append((out.total_cents + best.total_cents, out_dep, best.legs[0].dep_date))
    return sorted(combos)


def test_round_trip_index_matches_brute_force():
    rng = random.Random(1234)
    for _ in range(20):
        outbound = [
            _itin("AAA", "BBB", date(2026, 8, 1) + timedelta(days=rng.randrange(25)), rng.randrange(1000, 50000))
            for _ in range(rng.randrange(1, 15))
        ]
        inbound = [
            _itin("BBB", "AAA", date(2026, 8, 1) + timedelta(days=rng.randrange(40)), rng.randrange(1000, 50000))
            for _ in range(rng.randrange(1, 15))
        ]
        trip_min = rng.randrange(1, 6)
        trip_max = trip_min + rng.randrange(0, 12)
        combos = _pair_round_trips(outbound, inbound, trip_min, trip_max)
        got = sorted(
            (c.total_cents, c.legs[0].dep_date, c.legs[-1].dep_date) for c in combos
        )
        assert got == _brute_force(outbound, inbound, trip_min, trip_max)


def test_ground_corridor_ground_first_still_works(session):
    for iata, country in [("CGN", "DE"), ("BRU", "BE"), ("FEZ", "MA")]:
        add_airport(session, iata, country)
    add_ground(session, "CGN", "BRU", minutes=110, cents=2900)
    add_fare(session, "BRU", "FEZ", D, 2500)
    results = search(_params(origin="CGN", dest="FEZ"), session)
    assert results
    assert results[0].total_cents == 5400
