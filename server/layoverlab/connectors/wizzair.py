"""Wizz Air public timetable endpoint (used by wizzair.com itself; no key).

The API lives under a rotating version prefix (e.g. https://be.wizzair.com/27.6.0); the
current prefix is served at https://wizzair.com/buildnumber and cached via PoliteClient.
Disable with WIZZ_ENABLED=false if the endpoint becomes unstable.
"""

import calendar
import logging
import re
from datetime import date

from layoverlab.connectors.base import ConnectorDisabled, ConnectorError, DayFare, register
from layoverlab.connectors.fx import to_eur_cents
from layoverlab.connectors.http import PoliteClient
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

BUILDNUMBER_URL = "https://wizzair.com/buildnumber"
BE_BASE = "https://be.wizzair.com"
_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


def booking_deep_link(origin: str, dest: str, dep_date: date) -> str:
    return (
        "https://www.wizzair.com/en-gb/booking/select-flight/"
        f"{origin}/{dest}/{dep_date.isoformat()}/null/1/0/0/null"
    )


class WizzAirConnector:
    name = "wizzair"
    bulk = True

    def __init__(self, client: PoliteClient | None = None) -> None:
        self.client = client or PoliteClient(cache_ttl_s=6 * 3600)
        self._version_client = PoliteClient(cache_ttl_s=24 * 3600) if client is None else client

    def _check_enabled(self) -> None:
        if not get_settings().wizz_enabled:
            raise ConnectorDisabled("WIZZ_ENABLED=false")

    async def _api_base(self) -> str:
        text = await self._version_client.get_text(BUILDNUMBER_URL, headers={"Accept": "text/plain"})
        match = _VERSION_RE.search(text or "")
        if not match:
            raise ConnectorError(f"cannot parse wizzair build number from {text[:100]!r}")
        return f"{BE_BASE}/{match.group(1)}/Api"

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]:
        self._check_enabled()
        month_start = month.replace(day=1)
        month_end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        base = await self._api_base()
        payload = {
            "flightList": [
                {
                    "departureStation": origin,
                    "arrivalStation": dest,
                    "from": month_start.isoformat(),
                    "to": month_end.isoformat(),
                }
            ],
            "priceType": "regular",
            "adultCount": 1,
            "childCount": 0,
            "infantCount": 0,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        body = await self.client.post_json(f"{base}/search/timetable", json_body=payload, headers=headers)
        best: dict[date, DayFare] = {}
        for flight in (body or {}).get("outboundFlights") or []:
            price = (flight or {}).get("price") or {}
            amount = price.get("amount")
            if amount is None or float(amount) <= 0:
                continue
            try:
                dep = date.fromisoformat(str(flight["departureDate"])[:10])
                currency = price.get("currencyCode") or "EUR"
                cents = await to_eur_cents(float(amount), currency)
            except (KeyError, TypeError, ValueError) as exc:
                raise ConnectorError(f"unexpected wizzair flight shape: {flight!r}") from exc
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

    async def routes_from(self, origin: str) -> list[str]:
        return []

    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None:
        fares = await self.fetch_month(origin, dest, dep_date)
        for fare in fares:
            if fare["dep_date"] == dep_date:
                return fare
        return None


register(WizzAirConnector())
