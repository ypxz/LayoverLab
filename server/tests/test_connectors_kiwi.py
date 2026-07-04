from datetime import date

import pytest
import respx
from httpx import Response

from layoverlab.connectors import fx
from layoverlab.connectors.base import ConnectorDisabled
from layoverlab.connectors.kiwi_tequila import TEQUILA_SEARCH_URL, KiwiTequilaConnector
from layoverlab.settings import get_settings

SEARCH_FIXTURE = {
    "currency": "EUR",
    "data": [
        {
            "local_departure": "2026-09-01T06:20:00.000Z",
            "price": 89,
            "deep_link": "https://www.kiwi.com/deep?booking=1",
        },
        {
            "local_departure": "2026-09-01T18:00:00.000Z",
            "price": 55,
            "deep_link": "https://www.kiwi.com/deep?booking=2",
        },
        {
            "local_departure": "2026-09-09T10:00:00.000Z",
            "price": 120.5,
            "deep_link": "https://www.kiwi.com/deep?booking=3",
        },
    ],
}

ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube time="2026-07-03"><Cube currency="GBP" rate="0.80"/></Cube></Cube>
</gesmes:Envelope>
"""


@pytest.fixture()
def tequila_key(monkeypatch):
    monkeypatch.setenv("TEQUILA_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@respx.mock
async def test_kiwi_fetch_month_min_per_day(polite_client, tequila_key):
    route = respx.get(TEQUILA_SEARCH_URL).mock(return_value=Response(200, json=SEARCH_FIXTURE))
    connector = KiwiTequilaConnector(client=polite_client)
    fares = await connector.fetch_month("VIE", "BCN", date(2026, 9, 1))

    assert route.calls.last.request.headers["apikey"] == "test-key"
    assert [f["dep_date"] for f in fares] == [date(2026, 9, 1), date(2026, 9, 9)]
    assert fares[0]["price_cents"] == 5500  # min of 89 and 55
    assert fares[0]["deep_link"].startswith("https://www.kiwi.com/")


@respx.mock
async def test_kiwi_verify_day(polite_client, tequila_key):
    respx.get(TEQUILA_SEARCH_URL).mock(return_value=Response(200, json=SEARCH_FIXTURE))
    connector = KiwiTequilaConnector(client=polite_client)
    fare = await connector.verify_day("VIE", "BCN", date(2026, 9, 9))
    assert fare is not None and fare["price_cents"] == 12050


@respx.mock
async def test_kiwi_converts_non_eur(polite_client, tequila_key):
    fx._rates_cache = None
    respx.get(fx.ECB_DAILY_URL).mock(return_value=Response(200, text=ECB_XML))
    fixture = {"currency": "GBP", "data": [SEARCH_FIXTURE["data"][0]]}
    respx.get(TEQUILA_SEARCH_URL).mock(return_value=Response(200, json=fixture))
    connector = KiwiTequilaConnector(client=polite_client)
    fares = await connector.fetch_month("VIE", "BCN", date(2026, 9, 1))
    assert fares[0]["price_cents"] == round(89 / 0.80 * 100)
    assert fares[0]["currency"] == "EUR"
    fx._rates_cache = None


async def test_kiwi_disabled_without_key(polite_client, monkeypatch):
    monkeypatch.delenv("TEQUILA_API_KEY", raising=False)
    get_settings.cache_clear()
    connector = KiwiTequilaConnector(client=polite_client)
    with pytest.raises(ConnectorDisabled):
        await connector.fetch_month("VIE", "BCN", date(2026, 9, 1))
    get_settings.cache_clear()
