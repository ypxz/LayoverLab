from datetime import date

import pytest

from layoverlab.connectors import coverage
from layoverlab.db.models import Route
from layoverlab.settings import get_settings
from tests.conftest import add_airport


@pytest.fixture()
def clean_settings(monkeypatch):
    for var in (
        "TRAVELPAYOUTS_TOKEN", "TEQUILA_API_KEY", "AMADEUS_CLIENT_ID",
        "AMADEUS_CLIENT_SECRET", "WIZZ_ENABLED", "EASYJET_ENABLED", "GF_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_enabled_sources_reports_missing_tokens(clean_settings):
    statuses = coverage.enabled_sources()
    assert statuses["ryanair"] == {"enabled": True, "reason": None, "bulk": True}
    assert statuses["wizzair"]["enabled"] is True
    assert statuses["easyjet"]["enabled"] is True
    assert statuses["travelpayouts"] == {
        "enabled": False, "reason": "TRAVELPAYOUTS_TOKEN not set", "bulk": True,
    }
    assert statuses["kiwi_tequila"]["enabled"] is False
    assert statuses["amadeus"] == {
        "enabled": False, "reason": "AMADEUS_CLIENT_ID/AMADEUS_CLIENT_SECRET not set", "bulk": False,
    }
    assert statuses["google_flights"]["enabled"] is False


def test_enabled_sources_with_tokens(clean_settings):
    clean_settings.setenv("TRAVELPAYOUTS_TOKEN", "t")
    clean_settings.setenv("TEQUILA_API_KEY", "k")
    clean_settings.setenv("AMADEUS_CLIENT_ID", "a")
    clean_settings.setenv("AMADEUS_CLIENT_SECRET", "b")
    get_settings.cache_clear()
    statuses = coverage.enabled_sources()
    assert statuses["travelpayouts"]["enabled"] is True
    assert statuses["kiwi_tequila"]["enabled"] is True
    assert statuses["amadeus"]["enabled"] is True
    assert statuses["amadeus"]["bulk"] is False  # quota-aware: verify-first


def test_bulk_sources_excludes_disabled_and_verify_only(clean_settings):
    bulk = coverage.bulk_sources()
    assert "ryanair" in bulk and "wizzair" in bulk and "easyjet" in bulk
    assert "travelpayouts" not in bulk  # disabled without token
    assert "amadeus" not in bulk and "google_flights" not in bulk


def test_sources_for_route_unexplored_pair_claims_all_enabled(clean_settings, session):
    add_airport(session, "VIE", "AT")
    add_airport(session, "BCN", "ES")
    claimed = coverage.sources_for_route(session, "VIE", "BCN")
    assert set(claimed) == {"ryanair", "wizzair", "easyjet"}


def test_sources_for_route_seed_carriers_do_not_restrict(clean_settings, session):
    from layoverlab.db.models import utcnow

    session.add(Route(origin="VIE", dest="BCN", carriers=["FR", "W6"],
                      frequency_score=2.0, last_seen=utcnow()))
    session.flush()
    claimed = coverage.sources_for_route(session, "VIE", "BCN")
    assert {"ryanair", "wizzair", "easyjet"} <= set(claimed)


def test_sources_for_route_crawled_pair_restricts_airline_sources(clean_settings, session):
    from layoverlab.db.models import utcnow

    clean_settings.setenv("TRAVELPAYOUTS_TOKEN", "t")
    get_settings.cache_clear()
    session.add(Route(origin="VIE", dest="BCN", carriers=["ryanair"],
                      frequency_score=1.0, last_seen=utcnow()))
    session.flush()
    claimed = coverage.sources_for_route(session, "VIE", "BCN")
    assert "ryanair" in claimed
    assert "travelpayouts" in claimed  # universal source always claims
    assert "wizzair" not in claimed and "easyjet" not in claimed


def test_log_disabled_sources_warns(clean_settings, caplog):
    with caplog.at_level("WARNING", logger="layoverlab.connectors.coverage"):
        coverage.log_disabled_sources()
    combined = "\n".join(r.message for r in caplog.records)
    assert "FARE SOURCES DISABLED" in combined
    assert "TRAVELPAYOUTS_TOKEN" in combined


def test_enqueue_for_search_uses_coverage(clean_settings, session):
    from layoverlab.crawler.prioritizer import enqueue_for_search

    add_airport(session, "VIE", "AT")
    add_airport(session, "BCN", "ES")
    created = enqueue_for_search(session, "VIE", "BCN", date(2026, 9, 1), date(2026, 9, 1))
    assert created == 3  # ryanair + wizzair + easyjet (bulk, enabled, unexplored pair)
