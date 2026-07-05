"""easyJet lowest-daily-fares endpoint (public JSON used by easyjet.com's own low-fare finder).

GET https://www.easyjet.com/api/routepricing/v3/searchfares/GetLowestDailyFares returns a flat
list of {outboundPrice, departureDateTime, ...} per departure day. No key required. Endpoint is
unofficial and may rotate — disable with EASYJET_ENABLED=false; failures degrade gracefully.
"""

import logging
from datetime import date

from layoverlab.connectors.base import ConnectorDisabled, DayFare, register
from layoverlab.connectors.fx import to_eur_cents
from layoverlab.connectors.http import PoliteClient
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

LOWEST_DAILY_FARES_URL = "https://www.easyjet.com/api/routepricing/v3/searchfares/GetLowestDailyFares"


def booking_deep_link(origin: str, dest: str, dep_date: date) -> str:
    return (
        "https://www.easyjet.com/deeplink"
        f"?lang=EN&dep={origin}&dest={dest}&dd={dep_date.isoformat()}&apax=1"
    )


class EasyJetConnector:
    name = "easyjet"
    bulk = True

    def __init__(self, client: PoliteClient | None = None) -> None:
        self.client = client or PoliteClient(cache_ttl_s=6 * 3600)

    def _check_enabled(self) -> None:
        if not get_settings().easyjet_enabled:
            raise ConnectorDisabled("EASYJET_ENABLED=false")

    async def _lowest_daily_fares(self, origin: str, dest: str) -> list[DayFare]:
        self._check_enabled()
        params = {"departureAirport": origin, "arrivalAirport": dest, "currency": "EUR"}
        body = await self.client.get_json(LOWEST_DAILY_FARES_URL, params=params)
        best: dict[date, DayFare] = {}
        for entry in body or []:
            price = (entry or {}).get("outboundPrice")
            if price is None or float(price) <= 0:
                continue
            try:
                dep = date.fromisoformat(str(entry["departureDateTime"])[:10])
                currency = entry.get("currency") or "EUR"
                cents = await to_eur_cents(float(price), currency)
            except (KeyError, TypeError, ValueError):
                continue
            fare = DayFare(
                origin=origin,
                dest=dest,
                dep_date=dep,
                price_cents=cents,
                currency="EUR",
                deep_link=booking_deep_link(origin, dest, dep),
            )
            if dep not in best or cents < best[dep]["price_cents"]:
                best[dep] = fare
        return sorted(best.values(), key=lambda f: f["dep_date"])

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]:
        month_start = month.replace(day=1)
        fares = await self._lowest_daily_fares(origin, dest)
        return [
            f for f in fares
            if f["dep_date"].year == month_start.year and f["dep_date"].month == month_start.month
        ]

    async def routes_from(self, origin: str) -> list[str]:
        return []

    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None:
        fares = await self._lowest_daily_fares(origin, dest)
        for fare in fares:
            if fare["dep_date"] == dep_date:
                return fare
        return None


register(EasyJetConnector())
