from datetime import date

import pytest
import respx
from httpx import Response

from layoverlab.connectors.http import PoliteClient
from layoverlab.connectors.ryanair import FARFND_BASE, RyanairConnector
from layoverlab.connectors.travelpayouts import PRICES_FOR_DATES_URL, TravelpayoutsConnector

RYANAIR_FIXTURE = {
    "outbound": {
        "fares": [
            {"day": "2026-08-01", "price": {"value": 19.99, "currencyCode": "EUR"}},
            {"day": "2026-08-02", "price": None, "unavailable": True},
            {"day": "2026-08-03", "price": {"value": 45.5, "currencyCode": "EUR"}, "soldOut": True},
            {"day": "2026-08-04", "price": {"value": 12.34, "currencyCode": "EUR"}},
        ]
    }
}

TP_FIXTURE = {
    "data": [
        {"departure_at": "2026-08-01T06:20:00Z", "price": 89, "link": "/search/x1"},
        {"departure_at": "2026-08-01T18:00:00Z", "price": 55, "link": "/search/x2"},
        {"departure_at": "2026-08-09T10:00:00Z", "price": 120.5, "link": None},
    ]
}


@pytest.fixture()
def polite_client(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("CRAWL_MIN_INTERVAL_S", "0")
    from layoverlab.settings import get_settings

    get_settings.cache_clear()
    yield PoliteClient()
    get_settings.cache_clear()


@respx.mock
async def test_ryanair_fetch_month_parses_and_skips_unavailable(polite_client):
    url = f"{FARFND_BASE}/oneWayFares/BER/ALC/cheapestPerDay"
    respx.get(url).mock(return_value=Response(200, json=RYANAIR_FIXTURE))
    connector = RyanairConnector(client=polite_client)
    fares = await connector.fetch_month("BER", "ALC", date(2026, 8, 1))

    assert [f["dep_date"] for f in fares] == [date(2026, 8, 1), date(2026, 8, 4)]
    assert fares[0]["price_cents"] == 1999
    assert "ryanair.com" in fares[0]["deep_link"]


@respx.mock
async def test_ryanair_verify_day(polite_client):
    url = f"{FARFND_BASE}/oneWayFares/BER/ALC/cheapestPerDay"
    respx.get(url).mock(return_value=Response(200, json=RYANAIR_FIXTURE))
    connector = RyanairConnector(client=polite_client)
    fare = await connector.verify_day("BER", "ALC", date(2026, 8, 4))
    assert fare is not None and fare["price_cents"] == 1234
    missing = await connector.verify_day("BER", "ALC", date(2026, 8, 2))
    assert missing is None


@respx.mock
async def test_travelpayouts_min_per_day(polite_client, monkeypatch):
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "test-token")
    from layoverlab.settings import get_settings

    get_settings.cache_clear()
    respx.get(PRICES_FOR_DATES_URL).mock(return_value=Response(200, json=TP_FIXTURE))
    connector = TravelpayoutsConnector(client=polite_client)
    fares = await connector.fetch_month("BER", "ALC", date(2026, 8, 1))

    assert len(fares) == 2
    aug1 = next(f for f in fares if f["dep_date"] == date(2026, 8, 1))
    assert aug1["price_cents"] == 5500  # min of 89 and 55
    assert aug1["deep_link"].startswith("https://www.aviasales.com/")


async def test_travelpayouts_disabled_without_token(polite_client, monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)
    from layoverlab.connectors.base import ConnectorDisabled
    from layoverlab.settings import get_settings

    get_settings.cache_clear()
    connector = TravelpayoutsConnector(client=polite_client)
    with pytest.raises(ConnectorDisabled):
        await connector.fetch_month("BER", "ALC", date(2026, 8, 1))


@respx.mock
async def test_http_cache_prevents_second_request(polite_client):
    url = f"{FARFND_BASE}/oneWayFares/BER/ALC/cheapestPerDay"
    route = respx.get(url).mock(return_value=Response(200, json=RYANAIR_FIXTURE))
    connector = RyanairConnector(client=polite_client)
    await connector.fetch_month("BER", "ALC", date(2026, 8, 1))
    await connector.fetch_month("BER", "ALC", date(2026, 8, 1))
    assert route.call_count == 1
