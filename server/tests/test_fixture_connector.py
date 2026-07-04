from datetime import date

from sqlalchemy import func, select

from layoverlab.connectors.fixture import (
    FIXTURE_FARES,
    FixtureConnector,
    fixture_price_cents,
    month_fares,
    seed_fixture_stack,
)
from layoverlab.db.models import Airport, Fare, GroundLink
from layoverlab.engine.models import SearchParams
from layoverlab.engine.search import search

MONTH = date(2026, 9, 1)


def test_fares_are_deterministic():
    first = month_fares("BER", "ALC", MONTH)
    second = month_fares("BER", "ALC", MONTH)
    assert first == second
    assert len(first) == 30
    assert all(f["currency"] == "EUR" for f in first)
    assert all(0 < f["price_cents"] for f in first)


def test_unknown_pair_returns_empty():
    assert month_fares("BER", "XXX", MONTH) == []
    assert fixture_price_cents("BER", "XXX", MONTH) is None


async def test_verify_day_matches_month_fare():
    connector = FixtureConnector()
    fares = await connector.fetch_month("BER", "BKK", MONTH)
    verified = await connector.verify_day("BER", "BKK", fares[3]["dep_date"])
    assert verified == fares[3]


async def test_routes_from():
    connector = FixtureConnector()
    assert await connector.routes_from("BER") == ["ALC", "BKK", "DXB", "MUC"]
    assert await connector.routes_from("XXX") == []


def test_stopover_combos_beat_direct():
    for dep in month_fares("HAM", "ALC", MONTH):
        d = dep["dep_date"]
        direct = fixture_price_cents("HAM", "ALC", d)
        combo = fixture_price_cents("HAM", "BCN", d) + fixture_price_cents("BCN", "ALC", d)
        assert combo < direct
        direct_lh = fixture_price_cents("BER", "BKK", d)
        combo_lh = fixture_price_cents("BER", "DXB", d) + fixture_price_cents("DXB", "BKK", d)
        assert combo_lh < direct_lh


def test_registration_gated_by_setting(monkeypatch):
    from layoverlab.connectors import base
    from layoverlab.settings import get_settings

    monkeypatch.setattr(base, "_REGISTRY", {})
    get_settings.cache_clear()
    monkeypatch.setenv("FIXTURE_CONNECTOR", "false")
    base.load_default_connectors()
    registered_off = "fixture" in base.all_connectors()
    get_settings.cache_clear()
    monkeypatch.setenv("FIXTURE_CONNECTOR", "true")
    base.load_default_connectors()
    registered_on = "fixture" in base.all_connectors()
    get_settings.cache_clear()
    assert not registered_off
    assert registered_on


def test_seed_fixture_stack_idempotent(session):
    n1 = seed_fixture_stack(session, [MONTH])
    n2 = seed_fixture_stack(session, [MONTH])
    assert n1 == n2 == sum(len(month_fares(o, d, MONTH)) for o, d in FIXTURE_FARES)
    assert session.execute(select(func.count()).select_from(Fare)).scalar_one() == n1
    assert session.get(Airport, "BER") is not None
    links = session.execute(select(GroundLink)).scalars().all()
    assert {(link.from_iata, link.to_iata) for link in links} == {("CGN", "BRU"), ("BRU", "CGN")}


def test_seeded_stack_supports_cluster_and_ground_searches(session):
    seed_fixture_stack(session, [MONTH])
    params = SearchParams(origin="LHR", dest="MXP", date_from=MONTH, date_to=MONTH)
    cluster_results = search(params, session)
    assert cluster_results
    assert cluster_results[0].legs[-1].dest in {"MXP", "BGY"}

    params = SearchParams(origin="CGN", dest="PMI", date_from=MONTH, date_to=MONTH)
    ground_results = search(params, session)
    assert ground_results
    assert any(leg.mode == "ground" for leg in ground_results[0].legs)

    params = SearchParams(origin="BER", dest="BKK", date_from=MONTH, date_to=MONTH)
    longhaul = search(params, session)
    assert longhaul
    assert len(longhaul[0].legs) >= 2
    direct = fixture_price_cents("BER", "BKK", MONTH)
    assert longhaul[0].total_cents < direct
