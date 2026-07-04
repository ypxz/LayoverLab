"""Travelpayouts/Aviasales Data API (free token). Cached prices from real Aviasales searches (~48h)."""

import logging
from datetime import date

from layoverlab.connectors.base import ConnectorDisabled, DayFare, register
from layoverlab.connectors.http import PoliteClient
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

PRICES_FOR_DATES_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AVIASALES_BASE = "https://www.aviasales.com"


class TravelpayoutsConnector:
    name = "travelpayouts"
    bulk = True

    def __init__(self, client: PoliteClient | None = None) -> None:
        self.client = client or PoliteClient(cache_ttl_s=12 * 3600)

    def _token(self) -> str:
        token = get_settings().travelpayouts_token
        if not token:
            raise ConnectorDisabled("TRAVELPAYOUTS_TOKEN not set")
        return token

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]:
        token = self._token()
        params = {
            "origin": origin,
            "destination": dest,
            "departure_at": month.strftime("%Y-%m"),
            "one_way": "true",
            "direct": "false",
            "unique": "false",
            "sorting": "price",
            "limit": "1000",
            "currency": "eur",
            "token": token,
        }
        body = await self.client.get_json(PRICES_FOR_DATES_URL, params=params)
        best: dict[date, DayFare] = {}
        for entry in (body or {}).get("data") or []:
            try:
                dep = date.fromisoformat(str(entry["departure_at"])[:10])
                cents = round(float(entry["price"]) * 100)
            except (KeyError, TypeError, ValueError):
                continue
            link = entry.get("link")
            deep_link = f"{AVIASALES_BASE}{link}" if link else None
            fare = DayFare(
                origin=origin,
                dest=dest,
                dep_date=dep,
                price_cents=cents,
                currency="EUR",
                deep_link=deep_link,
            )
            if dep not in best or cents < best[dep]["price_cents"]:
                best[dep] = fare
        return sorted(best.values(), key=lambda f: f["dep_date"])

    async def routes_from(self, origin: str) -> list[str]:
        return []

    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None:
        fares = await self.fetch_month(origin, dest, dep_date)
        for fare in fares:
            if fare["dep_date"] == dep_date:
                return fare
        return None


register(TravelpayoutsConnector())
