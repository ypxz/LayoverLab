"""Currency normalization: daily ECB reference rates with 24h cache + hardcoded fallback.

All DayFare prices are EUR cents; connectors returning non-EUR amounts convert at ingest
via to_eur_cents().
"""

import logging
import xml.etree.ElementTree as ET

from layoverlab.connectors.http import PoliteClient

log = logging.getLogger(__name__)

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# Approximate rates (units of currency per 1 EUR), used only when the ECB feed is unreachable.
FALLBACK_RATES: dict[str, float] = {
    "USD": 1.08, "GBP": 0.85, "CHF": 0.95, "PLN": 4.30, "HUF": 395.0, "CZK": 25.0,
    "RON": 4.97, "SEK": 11.3, "NOK": 11.5, "DKK": 7.46, "BGN": 1.956, "ISK": 150.0,
    "TRY": 35.0, "AED": 3.97, "ILS": 4.0, "GEL": 2.9, "RSD": 117.0, "MKD": 61.6,
    "ALL": 100.0, "MDL": 19.0, "UAH": 45.0,
}

_rates_cache: dict[str, float] | None = None


def parse_ecb_xml(xml_text: str) -> dict[str, float]:
    rates: dict[str, float] = {}
    root = ET.fromstring(xml_text)
    for cube in root.iter():
        currency = cube.attrib.get("currency")
        rate = cube.attrib.get("rate")
        if currency and rate:
            try:
                rates[currency.upper()] = float(rate)
            except ValueError:
                continue
    return rates


async def get_rates(client: PoliteClient | None = None) -> dict[str, float]:
    global _rates_cache
    client = client or PoliteClient(cache_ttl_s=24 * 3600)
    try:
        xml_text = await client.get_text(ECB_DAILY_URL, headers={"Accept": "application/xml"})
        rates = parse_ecb_xml(xml_text)
        if rates:
            _rates_cache = rates
            return rates
    except Exception as exc:  # noqa: BLE001 - FX must degrade gracefully, never break a crawl
        log.warning("ECB rates fetch failed (%s), using fallback table", exc)
    return _rates_cache or FALLBACK_RATES


async def to_eur_cents(amount: float, currency: str, client: PoliteClient | None = None) -> int:
    currency = currency.upper()
    if currency == "EUR":
        return round(amount * 100)
    rates = await get_rates(client)
    rate = rates.get(currency) or FALLBACK_RATES.get(currency)
    if not rate:
        raise ValueError(f"no EUR rate available for currency {currency}")
    return round(amount / rate * 100)
