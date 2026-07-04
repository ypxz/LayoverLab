from datetime import date

import pytest
import respx
from httpx import Response

from layoverlab.connectors.base import ConnectorDisabled
from layoverlab.connectors.wizzair import BUILDNUMBER_URL, WizzAirConnector
from layoverlab.settings import get_settings

TIMETABLE_URL = "https://be.wizzair.com/27.6.0/Api/search/timetable"

TIMETABLE_FIXTURE = {
    "outboundFlights": [
        {
            "departureStation": "VIE",
            "arrivalStation": "BCN",
            "departureDate": "2026-09-01T00:00:00",
            "price": {"amount": 29.99, "currencyCode": "EUR"},
            "priceType": "price",
        },
        {
            "departureStation": "VIE",
            "arrivalStation": "BCN",
            "departureDate": "2026-09-01T18:30:00",
            "price": {"amount": 19.99, "currencyCode": "EUR"},
            "priceType": "price",
        },
        {
            "departureStation": "VIE",
            "arrivalStation": "BCN",
            "departureDate": "2026-09-03T07:15:00",
            "price": {"amount": 0, "currencyCode": "EUR"},
            "priceType": "checkPrice",
        },
        {
            "departureStation": "VIE",
            "arrivalStation": "BCN",
            "departureDate": "2026-09-05T10:00:00",
            "price": {"amount": 45.0, "currencyCode": "EUR"},
            "priceType": "price",
        },
    ],
    "returnFlights": [],
}


@respx.mock
async def test_wizzair_fetch_month_min_per_day(polite_client):
    respx.get(BUILDNUMBER_URL).mock(return_value=Response(200, text="https://be.wizzair.com/27.6.0"))
    respx.post(TIMETABLE_URL).mock(return_value=Response(200, json=TIMETABLE_FIXTURE))
    connector = WizzAirConnector(client=polite_client)
    fares = await connector.fetch_month("VIE", "BCN", date(2026, 9, 1))

    assert [f["dep_date"] for f in fares] == [date(2026, 9, 1), date(2026, 9, 5)]
    assert fares[0]["price_cents"] == 1999  # min of the two Sep 1 flights
    assert fares[0]["currency"] == "EUR"
    assert "wizzair.com" in fares[0]["deep_link"]


@respx.mock
async def test_wizzair_verify_day(polite_client):
    respx.get(BUILDNUMBER_URL).mock(return_value=Response(200, text="27.6.0"))
    respx.post(TIMETABLE_URL).mock(return_value=Response(200, json=TIMETABLE_FIXTURE))
    connector = WizzAirConnector(client=polite_client)
    fare = await connector.verify_day("VIE", "BCN", date(2026, 9, 5))
    assert fare is not None and fare["price_cents"] == 4500
    assert await connector.verify_day("VIE", "BCN", date(2026, 9, 2)) is None


async def test_wizzair_disabled_by_flag(polite_client, monkeypatch):
    monkeypatch.setenv("WIZZ_ENABLED", "false")
    get_settings.cache_clear()
    connector = WizzAirConnector(client=polite_client)
    with pytest.raises(ConnectorDisabled):
        await connector.fetch_month("VIE", "BCN", date(2026, 9, 1))
    get_settings.cache_clear()
