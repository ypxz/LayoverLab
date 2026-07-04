"""Google Flights: deep-link builder always available; live verification only when GF_ENABLED.

Scraping implementation is intentionally minimal and feature-flagged. TODO(T7): implement
fast-flights-style protobuf request for verify_day when GF_ENABLED=true.
"""

import logging
from datetime import date
from urllib.parse import quote

from layoverlab.connectors.base import DayFare, register
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)


def deep_link(origin: str, dest: str, dep_date: date) -> str:
    q = f"Flights from {origin} to {dest} on {dep_date.isoformat()} one way"
    return f"https://www.google.com/travel/flights?q={quote(q)}"


class GoogleFlightsConnector:
    name = "google_flights"

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]:
        return []  # verification-only connector; never bulk-crawled

    async def routes_from(self, origin: str) -> list[str]:
        return []

    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None:
        if not get_settings().gf_enabled:
            return None
        # TODO(T7): low-volume protobuf request to Google Flights; return live cheapest for the day.
        log.info("GF verification requested for %s-%s %s (not yet implemented)", origin, dest, dep_date)
        return None


register(GoogleFlightsConnector())
