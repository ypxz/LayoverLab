import base64
from datetime import date, datetime
from pathlib import Path

import pytest
import respx
from httpx import Response

from layoverlab.connectors.google_flights import (
    GoogleFlightsConnector,
    build_tfs,
    deep_link,
    parse_flight_options,
)

DEP = date(2026, 8, 15)
FIXTURE = Path(__file__).parent / "fixtures" / "gf_ber_alc_2026-08-15.html"


@pytest.fixture()
def gf_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("GF_ENABLED", "true")
    monkeypatch.setenv("GF_MIN_INTERVAL_S", "0")
    monkeypatch.setenv("CRAWL_MIN_INTERVAL_S", "0")
    monkeypatch.setenv("HTTP_CACHE_DIR", str(tmp_path / "cache"))
    from layoverlab.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_build_tfs_roundtrip():
    tfs = build_tfs("BER", "ALC", DEP)
    raw = base64.urlsafe_b64decode(tfs + "=" * (-len(tfs) % 4))
    assert b"2026-08-15" in raw
    assert b"BER" in raw
    assert b"ALC" in raw


def test_parse_flight_options_from_fixture():
    options = parse_flight_options(FIXTURE.read_text(encoding="utf-8"), DEP)
    assert len(options) >= 5
    cheapest = options[0]
    assert cheapest["price_cents"] == 11900
    assert cheapest["carrier"] == "Vueling"
    assert cheapest["stops"] == 1
    assert cheapest["dep_time"] == datetime(2026, 8, 15, 22, 0)
    assert cheapest["arr_time"] == datetime(2026, 8, 16, 9, 35)  # next-day arrival
    assert all(o["dep_time"].date() == DEP for o in options)


def test_parse_garbage_returns_empty():
    assert parse_flight_options("<html><body>captcha</body></html>", DEP) == []


@respx.mock
async def test_verify_day_from_fixture(gf_enabled):
    respx.get("https://www.google.com/travel/flights").mock(
        return_value=Response(200, text=FIXTURE.read_text(encoding="utf-8"))
    )
    fare = await GoogleFlightsConnector().verify_day("BER", "ALC", DEP)
    assert fare is not None
    assert fare["price_cents"] == 11900
    assert fare["currency"] == "EUR"
    assert fare["deep_link"] == deep_link("BER", "ALC", DEP)


@respx.mock
async def test_verify_day_disabled_returns_none(monkeypatch):
    from layoverlab.settings import get_settings

    monkeypatch.setenv("GF_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert await GoogleFlightsConnector().verify_day("BER", "ALC", DEP) is None
        assert not respx.calls  # disabled: no HTTP at all
    finally:
        get_settings.cache_clear()


@respx.mock
async def test_blocked_response_degrades_to_none(gf_enabled):
    respx.get("https://www.google.com/travel/flights").mock(
        return_value=Response(200, text="<html>unusual traffic</html>")
    )
    connector = GoogleFlightsConnector()
    assert await connector.fetch_day_options("BER", "ALC", DEP) is None
    assert await connector.verify_day("BER", "ALC", DEP) is None


@respx.mock
async def test_http_error_degrades_to_none(gf_enabled):
    respx.get("https://www.google.com/travel/flights").mock(return_value=Response(403))
    assert await GoogleFlightsConnector().fetch_day_options("BER", "ALC", DEP) is None


async def test_never_bulk():
    connector = GoogleFlightsConnector()
    assert getattr(connector, "bulk", False) is False
    assert await connector.fetch_month("BER", "ALC", DEP) == []
    assert await connector.routes_from("BER") == []
