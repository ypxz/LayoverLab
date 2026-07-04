from datetime import date

import pytest
import respx
from httpx import Response

from layoverlab.connectors.amadeus import (
    CHEAPEST_DATES_URL,
    FLIGHT_OFFERS_URL,
    TOKEN_URL,
    AmadeusConnector,
)
from layoverlab.connectors.base import ConnectorDisabled
from layoverlab.settings import get_settings

TOKEN_FIXTURE = {"access_token": "amadeus-test-token", "expires_in": 1799, "token_type": "Bearer"}

FLIGHT_DATES_FIXTURE = {
    "data": [
        {
            "type": "flight-date",
            "origin": "VIE",
            "destination": "BCN",
            "departureDate": "2026-09-02",
            "price": {"total": "61.30"},
            "links": {"flightOffers": "https://test.api.amadeus.com/v2/shopping/flight-offers?x=1"},
        },
        {
            "type": "flight-date",
            "origin": "VIE",
            "destination": "BCN",
            "departureDate": "2026-09-10",
            "price": {"total": "45.00"},
            "links": {},
        },
    ]
}

FLIGHT_OFFERS_FIXTURE = {
    "data": [
        {"price": {"grandTotal": "88.40", "currency": "EUR"}},
        {"price": {"grandTotal": "61.30", "currency": "EUR"}},
    ]
}


@pytest.fixture()
def amadeus_creds(monkeypatch):
    monkeypatch.setenv("AMADEUS_CLIENT_ID", "cid")
    monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "csecret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@respx.mock
async def test_amadeus_fetch_month_cheapest_dates(polite_client, amadeus_creds):
    respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_FIXTURE))
    dates_route = respx.get(CHEAPEST_DATES_URL).mock(
        return_value=Response(200, json=FLIGHT_DATES_FIXTURE)
    )
    connector = AmadeusConnector(client=polite_client)
    fares = await connector.fetch_month("VIE", "BCN", date(2026, 9, 1))

    assert dates_route.calls.last.request.headers["Authorization"] == "Bearer amadeus-test-token"
    assert [f["dep_date"] for f in fares] == [date(2026, 9, 2), date(2026, 9, 10)]
    assert fares[0]["price_cents"] == 6130
    assert fares[1]["deep_link"] is None


@respx.mock
async def test_amadeus_fetch_month_unsupported_pair_returns_empty(polite_client, amadeus_creds):
    respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_FIXTURE))
    respx.get(CHEAPEST_DATES_URL).mock(return_value=Response(404, json={"errors": []}))
    connector = AmadeusConnector(client=polite_client)
    fares = await connector.fetch_month("VIE", "XYZ", date(2026, 9, 1))
    assert fares == []


@respx.mock
async def test_amadeus_verify_day_min_offer(polite_client, amadeus_creds):
    respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_FIXTURE))
    respx.get(FLIGHT_OFFERS_URL).mock(return_value=Response(200, json=FLIGHT_OFFERS_FIXTURE))
    connector = AmadeusConnector(client=polite_client)
    fare = await connector.verify_day("VIE", "BCN", date(2026, 9, 2))
    assert fare is not None and fare["price_cents"] == 6130


@respx.mock
async def test_amadeus_token_reused_across_calls(polite_client, amadeus_creds):
    token_route = respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_FIXTURE))
    respx.get(FLIGHT_OFFERS_URL).mock(return_value=Response(200, json=FLIGHT_OFFERS_FIXTURE))
    connector = AmadeusConnector(client=polite_client)
    await connector.verify_day("VIE", "BCN", date(2026, 9, 2))
    await connector.verify_day("VIE", "BCN", date(2026, 9, 3))
    assert token_route.call_count == 1


async def test_amadeus_disabled_without_credentials(polite_client, monkeypatch):
    monkeypatch.delenv("AMADEUS_CLIENT_ID", raising=False)
    monkeypatch.delenv("AMADEUS_CLIENT_SECRET", raising=False)
    get_settings.cache_clear()
    connector = AmadeusConnector(client=polite_client)
    with pytest.raises(ConnectorDisabled):
        await connector.fetch_month("VIE", "BCN", date(2026, 9, 1))
    get_settings.cache_clear()
