from datetime import date

from layoverlab.engine.models import SearchParams
from layoverlab.engine.search import search
from tests.conftest import add_airport, add_fare, add_ground

D = date(2026, 8, 10)


def _params(**overrides) -> SearchParams:
    defaults = dict(
        origin="BER", dest="BKK", date_from=D, date_to=D,
        stop_min_hours=4, stop_max_days=7, max_stops=3, top_k=5,
    )
    defaults.update(overrides)
    return SearchParams(**defaults)


def test_multi_day_stopover_beats_direct(session):
    for iata, country in [("BER", "DE"), ("KUL", "MY"), ("BKK", "TH")]:
        add_airport(session, iata, country)
    add_fare(session, "BER", "BKK", D, 80000)                       # direct: 800€
    add_fare(session, "BER", "KUL", D, 20000)                       # leg 1: 200€
    add_fare(session, "KUL", "BKK", date(2026, 8, 13), 5000)        # leg 2 after 3 nights: 50€
    results = search(_params(), session)

    assert results
    best = results[0]
    assert best.total_cents == 25000
    assert [leg.dest for leg in best.legs] == ["KUL", "BKK"]
    assert best.stopovers[0].iata == "KUL"
    assert best.stopovers[0].nights == 3
    assert any("visa" in w.lower() for w in best.warnings)
    # direct itinerary still present as an alternative
    assert any(len(i.legs) == 1 for i in results)


def test_cluster_swap_is_found(session):
    add_airport(session, "BER", "DE")
    add_airport(session, "LGW", "GB", cluster="LON")
    add_airport(session, "STN", "GB", cluster="LON")
    add_fare(session, "BER", "LGW", D, 90000)   # direct to requested airport: 900€
    add_fare(session, "BER", "STN", D, 3000)    # sibling airport: 30€
    results = search(_params(dest="LGW"), session)

    assert results
    assert results[0].legs[-1].dest == "STN"    # arriving anywhere in the LON cluster counts
    assert results[0].total_cents == 3000


def test_ground_corridor_used(session):
    for iata, country in [("CGN", "DE"), ("BRU", "BE"), ("FEZ", "MA")]:
        add_airport(session, iata, country)
    add_ground(session, "CGN", "BRU", minutes=110, cents=2900)
    add_fare(session, "CGN", "FEZ", D, 60000)                      # direct from Cologne: 600€
    add_fare(session, "BRU", "FEZ", D, 2500)                       # from Brussels: 25€
    results = search(_params(origin="CGN", dest="FEZ"), session)

    assert results
    best = results[0]
    assert [leg.mode for leg in best.legs] == ["ground", "flight"]
    assert best.total_cents == 2900 + 2500
    assert any("Ground segment" in w for w in best.warnings)


def test_max_stops_respected(session):
    for iata in ["AAA", "BBB", "CCC", "DDD"]:
        add_airport(session, iata)
    add_fare(session, "AAA", "BBB", D, 1000)
    add_fare(session, "BBB", "CCC", date(2026, 8, 11), 1000)
    add_fare(session, "CCC", "DDD", date(2026, 8, 12), 1000)
    add_fare(session, "AAA", "DDD", D, 99000)
    results = search(_params(origin="AAA", dest="DDD", max_stops=1), session)

    assert results
    assert all(len(i.legs) <= 2 for i in results)
    assert results[0].total_cents == 99000  # cheap 3-leg chain excluded by max_stops=1


def test_month_range_picks_cheapest_date(session):
    add_airport(session, "BER")
    add_airport(session, "ALC", "ES")
    add_fare(session, "BER", "ALC", date(2026, 8, 5), 12000)
    add_fare(session, "BER", "ALC", date(2026, 8, 19), 1500)
    results = search(
        _params(origin="BER", dest="ALC", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31)),
        session,
    )

    assert results
    assert results[0].legs[0].dep_date == date(2026, 8, 19)


def test_round_trip_combines_and_respects_trip_length(session):
    add_airport(session, "BER")
    add_airport(session, "LIS", "PT")
    add_fare(session, "BER", "LIS", D, 4000)
    add_fare(session, "LIS", "BER", date(2026, 8, 12), 9000)   # too early (2 days)
    add_fare(session, "LIS", "BER", date(2026, 8, 20), 3000)   # 10 days -> valid
    results = search(
        _params(round_trip=True, trip_min_days=7, trip_max_days=14, dest="LIS"),
        session,
    )

    assert results
    best = results[0]
    assert best.total_cents == 7000
    assert best.legs[0].origin == "BER" and best.legs[-1].dest == "BER"
    assert best.legs[-1].dep_date == date(2026, 8, 20)


def test_stopover_bounds_respected(session):
    for iata in ["AAA", "BBB", "CCC"]:
        add_airport(session, iata)
    add_fare(session, "AAA", "BBB", D, 1000)
    add_fare(session, "BBB", "CCC", date(2026, 8, 25), 100)  # 15-night stopover > stop_max_days
    add_fare(session, "AAA", "CCC", D, 50000)
    results = search(_params(origin="AAA", dest="CCC", stop_max_days=7), session)

    assert results
    assert results[0].total_cents == 50000  # the 15-night combo must not appear
