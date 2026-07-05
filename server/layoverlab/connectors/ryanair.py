"""Ryanair public fare-finder API (no key). Cheapest fare per day for a whole month in one call."""

import logging
from datetime import date

from layoverlab.connectors.base import ConnectorError, DayFare, register
from layoverlab.connectors.http import PoliteClient

log = logging.getLogger(__name__)

FARFND_BASE = "https://services-api.ryanair.com/farfnd/v4"
ROUTES_URL = "https://www.ryanair.com/api/views/locate/searchWidget/routes/en/airport/{iata}"


def booking_deep_link(origin: str, dest: str, dep_date: date) -> str:
    return (
        "https://www.ryanair.com/de/de/trip/flights/select"
        f"?adults=1&teens=0&children=0&infants=0&isReturn=false"
        f"&dateOut={dep_date.isoformat()}&originIata={origin}&destinationIata={dest}"
    )


class RyanairConnector:
    name = "ryanair"
    bulk = True

    def __init__(self, client: PoliteClient | None = None) -> None:
        self.client = client or PoliteClient(cache_ttl_s=6 * 3600)

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]:
        month_start = month.replace(day=1)
        url = f"{FARFND_BASE}/oneWayFares/{origin}/{dest}/cheapestPerDay"
        params = {"outboundMonthOfDate": month_start.isoformat(), "currency": "EUR"}
        body = await self.client.get_json(url, params=params)
        outbound = (body or {}).get("outbound") or {}
        fares: list[DayFare] = []
        for entry in outbound.get("fares") or []:
            price = entry.get("price")
            if not price or entry.get("unavailable") or entry.get("soldOut"):
                continue
            try:
                dep = date.fromisoformat(entry["day"])
                cents = round(float(price["value"]) * 100)
                currency = price.get("currencyCode", "EUR")
            except (KeyError, TypeError, ValueError) as exc:
                raise ConnectorError(f"unexpected fare entry shape: {entry!r}") from exc
            fares.append(
                DayFare(
                    origin=origin,
                    dest=dest,
                    dep_date=dep,
                    price_cents=cents,
                    currency=currency,
                    deep_link=booking_deep_link(origin, dest, dep),
                )
            )
        return fares

    async def routes_from(self, origin: str) -> list[str]:
        body = await self.client.get_json(ROUTES_URL.format(iata=origin))
        dests: list[str] = []
        for entry in body or []:
            code = ((entry or {}).get("arrivalAirport") or {}).get("code")
            if code and len(code) == 3:
                dests.append(code.upper())
        return sorted(set(dests))

    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None:
        fares = await self.fetch_month(origin, dest, dep_date)
        for fare in fares:
            if fare["dep_date"] == dep_date:
                return fare
        return None


register(RyanairConnector())
