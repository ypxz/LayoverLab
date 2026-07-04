"""Amadeus Self-Service APIs (official free tier, test environment).

OAuth2 client-credentials with AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET
(signup: https://developers.amadeus.com, free monthly quota).

Quota-aware: Flight Cheapest Date Search covers only a subset of pairs — fetch_month
returns [] for unsupported pairs instead of failing, and the connector is registered
verify-first (bulk=False) so the crawler never bulk-fans it out.
"""

import calendar
import logging
import time
from datetime import date

from layoverlab.connectors.base import ConnectorDisabled, ConnectorError, DayFare, register
from layoverlab.connectors.http import PoliteClient
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

AMADEUS_BASE = "https://test.api.amadeus.com"
TOKEN_URL = f"{AMADEUS_BASE}/v1/security/oauth2/token"
CHEAPEST_DATES_URL = f"{AMADEUS_BASE}/v1/shopping/flight-dates"
FLIGHT_OFFERS_URL = f"{AMADEUS_BASE}/v2/shopping/flight-offers"


class AmadeusConnector:
    name = "amadeus"
    bulk = False

    def __init__(self, client: PoliteClient | None = None) -> None:
        self.client = client or PoliteClient(cache_ttl_s=6 * 3600)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _credentials(self) -> tuple[str, str]:
        settings = get_settings()
        if not settings.amadeus_client_id or not settings.amadeus_client_secret:
            raise ConnectorDisabled("AMADEUS_CLIENT_ID/AMADEUS_CLIENT_SECRET not set")
        return settings.amadeus_client_id, settings.amadeus_client_secret

    async def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        client_id, client_secret = self._credentials()
        body = await self.client.post_json(
            TOKEN_URL,
            form_data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            cache=False,
        )
        token = (body or {}).get("access_token")
        if not token:
            raise ConnectorError("amadeus token response missing access_token")
        self._token = token
        self._token_expires_at = time.monotonic() + float(body.get("expires_in", 1799)) - 60
        return token

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]:
        token = await self._access_token()
        month_start = month.replace(day=1)
        month_end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        params = {
            "origin": origin,
            "destination": dest,
            "departureDate": f"{month_start.isoformat()},{month_end.isoformat()}",
            "oneWay": "true",
            "nonStop": "false",
        }
        try:
            body = await self.client.get_json(
                CHEAPEST_DATES_URL, params=params, headers={"Authorization": f"Bearer {token}"}
            )
        except ConnectorError as exc:
            # Cheapest Date Search covers a limited set of pairs; unsupported pair != failure.
            log.info("amadeus flight-dates unavailable for %s-%s: %s", origin, dest, exc)
            return []
        fares: list[DayFare] = []
        for entry in (body or {}).get("data") or []:
            try:
                dep = date.fromisoformat(entry["departureDate"])
                cents = round(float(entry["price"]["total"]) * 100)
            except (KeyError, TypeError, ValueError):
                continue
            links = entry.get("links") or {}
            fares.append(
                DayFare(
                    origin=origin,
                    dest=dest,
                    dep_date=dep,
                    price_cents=cents,
                    currency="EUR",
                    deep_link=links.get("flightOffers"),
                )
            )
        return sorted(fares, key=lambda f: f["dep_date"])

    async def routes_from(self, origin: str) -> list[str]:
        return []

    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None:
        token = await self._access_token()
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": dest,
            "departureDate": dep_date.isoformat(),
            "adults": "1",
            "currencyCode": "EUR",
            "max": "5",
        }
        body = await self.client.get_json(
            FLIGHT_OFFERS_URL, params=params, headers={"Authorization": f"Bearer {token}"}
        )
        best: DayFare | None = None
        for offer in (body or {}).get("data") or []:
            try:
                cents = round(float(offer["price"]["grandTotal"]) * 100)
            except (KeyError, TypeError, ValueError):
                continue
            if best is None or cents < best["price_cents"]:
                best = DayFare(
                    origin=origin,
                    dest=dest,
                    dep_date=dep_date,
                    price_cents=cents,
                    currency="EUR",
                    deep_link=None,
                )
        return best


register(AmadeusConnector())
