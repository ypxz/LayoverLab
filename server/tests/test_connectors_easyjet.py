from datetime import date

import pytest
import respx
from httpx import Response

from layoverlab.connectors.base import ConnectorDisabled
from layoverlab.connectors.easyjet import LOWEST_DAILY_FARES_URL, EasyJetConnector
from layoverlab.settings import get_settings

FARES_FIXTURE = [
    {
        "departureAirport": "VIE",
        "arrivalAirport": "BCN",
        "departureDateTime": "2026-09-01T00:00:00",
        "outboundPrice": 25.99,
        "returnPrice": 30.49,
    },
    {
        "departureAirport": "VIE",
        "arrivalAirport": "BCN",
        "departureDateTime": "2026-09-04T00:00:00",
        "outboundPrice": 0,
    },
    {
        "departureAirport": "VIE",
        "arrivalAirport": "BCN",
        "departureDateTime": "2026-09-06T00:00:00",
        "outboundPrice": 41.5,
    },
    {
        "departureAirport": "VIE",
        "arrivalAirport": "BCN",
        "departureDateTime": "2026-10-02T00:00:00",
        "outboundPrice": 19.99,
    },
]


@respx.mock
async def test_easyjet_fetch_month_filters_month_and_zero_prices(polite_client):
    respx.get(LOWEST_DAILY_FARES_URL).mock(return_value=Response(200, json=FARES_FIXTURE))
    connector = EasyJetConnector(client=polite_client)
    fares = await connector.fetch_month("VIE", "BCN", date(2026, 9, 1))

    assert [f["dep_date"] for f in fares] == [date(2026, 9, 1), date(2026, 9, 6)]
    assert fares[0]["price_cents"] == 2599
    assert "easyjet.com" in fares[0]["deep_link"]


@respx.mock
async def test_easyjet_verify_day(polite_client):
    respx.get(LOWEST_DAILY_FARES_URL).mock(return_value=Response(200, json=FARES_FIXTURE))
    connector = EasyJetConnector(client=polite_client)
    fare = await connector.verify_day("VIE", "BCN", date(2026, 10, 2))
    assert fare is not None and fare["price_cents"] == 1999
    assert await connector.verify_day("VIE", "BCN", date(2026, 9, 4)) is None


async def test_easyjet_disabled_by_flag(polite_client, monkeypatch):
    monkeypatch.setenv("EASYJET_ENABLED", "false")
    get_settings.cache_clear()
    connector = EasyJetConnector(client=polite_client)
    with pytest.raises(ConnectorDisabled):
        await connector.fetch_month("VIE", "BCN", date(2026, 9, 1))
    get_settings.cache_clear()
