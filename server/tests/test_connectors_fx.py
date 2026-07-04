import pytest
import respx
from httpx import Response

from layoverlab.connectors import fx

ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time="2026-07-03">
      <Cube currency="USD" rate="1.0850"/>
      <Cube currency="GBP" rate="0.8500"/>
      <Cube currency="PLN" rate="4.2500"/>
      <Cube currency="HUF" rate="400.00"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


@pytest.fixture(autouse=True)
def _clear_fx_cache():
    fx._rates_cache = None
    yield
    fx._rates_cache = None


def test_parse_ecb_xml():
    rates = fx.parse_ecb_xml(ECB_XML)
    assert rates == {"USD": 1.085, "GBP": 0.85, "PLN": 4.25, "HUF": 400.0}


@respx.mock
async def test_to_eur_cents_uses_live_rates(polite_client):
    respx.get(fx.ECB_DAILY_URL).mock(return_value=Response(200, text=ECB_XML))
    cents = await fx.to_eur_cents(42.50, "PLN", client=polite_client)
    assert cents == 1000  # 42.50 / 4.25 = 10 EUR
    assert await fx.to_eur_cents(10.0, "EUR", client=polite_client) == 1000


@respx.mock
async def test_to_eur_cents_falls_back_when_ecb_down(polite_client):
    respx.get(fx.ECB_DAILY_URL).mock(return_value=Response(404))
    cents = await fx.to_eur_cents(108.0, "USD", client=polite_client)
    assert cents == round(108.0 / fx.FALLBACK_RATES["USD"] * 100)


@respx.mock
async def test_to_eur_cents_unknown_currency_raises(polite_client):
    respx.get(fx.ECB_DAILY_URL).mock(return_value=Response(200, text=ECB_XML))
    with pytest.raises(ValueError):
        await fx.to_eur_cents(10.0, "XXX", client=polite_client)
