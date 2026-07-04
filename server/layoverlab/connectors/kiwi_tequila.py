"""Kiwi.com Tequila API (free tier, header apikey: TEQUILA_API_KEY).

Kiwi natively prices self-transfer multi-leg trips, so verify_day doubles as a
whole-itinerary sanity check. Signup: https://tequila.kiwi.com (free).
"""

import calendar
import logging
from datetime import date

from layoverlab.connectors.base import ConnectorDisabled, DayFare, register
from layoverlab.connectors.fx import to_eur_cents
from layoverlab.connectors.http import PoliteClient
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

TEQUILA_SEARCH_URL = "https://api.tequila.kiwi.com/v2/search"


class KiwiTequilaConnector:
    name = "kiwi_tequila"
    bulk = True

    def __init__(self, client: PoliteClient | None = None) -> None:
        self.client = client or PoliteClient(cache_ttl_s=6 * 3600)

    def _api_key(self) -> str:
        key = get_settings().tequila_api_key
        if not key:
            raise ConnectorDisabled("TEQUILA_API_KEY not set")
        return key

    async def _search(self, origin: str, dest: str, date_from: date, date_to: date) -> list[DayFare]:
        key = self._api_key()
        params = {
            "fly_from": origin,
            "fly_to": dest,
            "date_from": date_from.strftime("%d/%m/%Y"),
            "date_to": date_to.strftime("%d/%m/%Y"),
            "curr": "EUR",
            "sort": "price",
            "limit": "200",
            "one_for_city": "0",
            "adults": "1",
        }
        body = await self.client.get_json(TEQUILA_SEARCH_URL, params=params, headers={"apikey": key})
        currency = (body or {}).get("currency") or "EUR"
        best: dict[date, DayFare] = {}
        for entry in (body or {}).get("data") or []:
            try:
                dep = date.fromisoformat(str(entry["local_departure"])[:10])
                cents = await to_eur_cents(float(entry["price"]), currency)
            except (KeyError, TypeError, ValueError):
                continue
            fare = DayFare(
                origin=origin,
                dest=dest,
                dep_date=dep,
                price_cents=cents,
                currency="EUR",
                deep_link=entry.get("deep_link"),
            )
            if dep not in best or cents < best[dep]["price_cents"]:
                best[dep] = fare
        return sorted(best.values(), key=lambda f: f["dep_date"])

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]:
        month_start = month.replace(day=1)
        month_end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        return await self._search(origin, dest, month_start, month_end)

    async def routes_from(self, origin: str) -> list[str]:
        return []

    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None:
        fares = await self._search(origin, dest, dep_date, dep_date)
        for fare in fares:
            if fare["dep_date"] == dep_date:
                return fare
        return None


register(KiwiTequilaConnector())
