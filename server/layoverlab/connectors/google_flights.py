"""Google Flights: deep-link builder always available; live verification only when GF_ENABLED.

One-way day queries via the public ``tfs=`` protobuf URL parameter (fast-flights technique):
a hand-encoded protobuf message (origin/dest/date, one-way, 1 adult, economy) is base64url
encoded into the URL, and the flight options are parsed from the server-rendered HTML
response. Verification-only: tiny volume, never bulk-crawled, always through PoliteClient.
"""

import asyncio
import base64
import logging
import re
import time
from datetime import date, datetime
from typing import TypedDict
from urllib.parse import quote

from layoverlab.connectors.base import DayFare, register
from layoverlab.connectors.http import PoliteClient
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

FLIGHTS_URL = "https://www.google.com/travel/flights"

_gf_lock = asyncio.Lock()
_gf_last = 0.0


def deep_link(origin: str, dest: str, dep_date: date) -> str:
    q = f"Flights from {origin} to {dest} on {dep_date.isoformat()} one way"
    return f"https://www.google.com/travel/flights?q={quote(q)}"


class FlightOption(TypedDict):
    dep_time: datetime
    arr_time: datetime
    carrier: str
    stops: int
    price_cents: int | None
    currency: str


def _varint(n: int) -> bytes:
    out = b""
    while True:
        b7 = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b7 | 0x80])
        else:
            return out + bytes([b7])


def _pb_field(num: int, wire: int, payload: bytes) -> bytes:
    return _varint((num << 3) | wire) + payload


def _pb_len(num: int, data: bytes) -> bytes:
    return _pb_field(num, 2, _varint(len(data)) + data)


def _pb_str(num: int, s: str) -> bytes:
    return _pb_len(num, s.encode())


def build_tfs(origin: str, dest: str, dep_date: date) -> str:
    """Encode a one-way, 1-adult, economy day query as a base64url tfs parameter."""
    flight_data = (
        _pb_str(2, dep_date.isoformat())
        + _pb_len(13, _pb_str(2, origin))
        + _pb_len(14, _pb_str(2, dest))
    )
    info = (
        _pb_len(3, flight_data)
        + _pb_field(8, 0, _varint(1))  # passengers: 1 adult
        + _pb_field(9, 0, _varint(1))  # seat: economy
        + _pb_field(19, 0, _varint(2))  # trip: one-way
    )
    return base64.urlsafe_b64encode(info).decode().rstrip("=")


_OPTION_RE = re.compile(
    r"From (?P<price>\d+) euros\.[^\"]*?"
    r"(?:(?P<nonstop>Nonstop)|(?P<stops>\d+) stops?) flight with (?P<carrier>[^.]+)\.[^\"]*?"
    r"Leaves .*? at (?P<dep_time>\d{1,2}:\d{2})\s?(?P<dep_ampm>AM|PM) "
    r"on \w+, (?P<dep_month>\w+) (?P<dep_day>\d{1,2}) "
    r"and arrives at .*? at (?P<arr_time>\d{1,2}:\d{2})\s?(?P<arr_ampm>AM|PM) "
    r"on \w+, (?P<arr_month>\w+) (?P<arr_day>\d{1,2})\.",
)

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        start=1,
    )
}


def _parse_local_dt(base: date, month_name: str, day: str, hhmm: str, ampm: str) -> datetime | None:
    month = _MONTHS.get(month_name)
    if month is None:
        return None
    year = base.year + 1 if month < base.month else base.year
    hour, minute = (int(p) for p in hhmm.split(":"))
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    try:
        return datetime(year, month, int(day), hour, minute)
    except ValueError:
        return None


def parse_flight_options(html: str, dep_date: date) -> list[FlightOption]:
    """Parse flight options from the aria-label summaries embedded in the GF HTML response."""
    options: list[FlightOption] = []
    seen: set[tuple] = set()
    for match in _OPTION_RE.finditer(html.replace("\u202f", " ")):
        dep = _parse_local_dt(
            dep_date, match["dep_month"], match["dep_day"], match["dep_time"], match["dep_ampm"]
        )
        arr = _parse_local_dt(
            dep_date, match["arr_month"], match["arr_day"], match["arr_time"], match["arr_ampm"]
        )
        if dep is None or arr is None or dep.date() != dep_date:
            continue
        key = (dep, arr, match["carrier"])
        if key in seen:
            continue
        seen.add(key)
        options.append(
            FlightOption(
                dep_time=dep,
                arr_time=arr,
                carrier=match["carrier"].strip(),
                stops=0 if match["nonstop"] else int(match["stops"]),
                price_cents=int(match["price"]) * 100,
                currency="EUR",
            )
        )
    options.sort(key=lambda o: (o["price_cents"] is None, o["price_cents"], o["dep_time"]))
    return options


class GoogleFlightsConnector:
    name = "google_flights"

    def __init__(self, client: PoliteClient | None = None) -> None:
        self.client = client or PoliteClient(cache_ttl_s=15 * 60)

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]:
        return []  # verification-only connector; never bulk-crawled

    async def routes_from(self, origin: str) -> list[str]:
        return []

    async def _respect_gf_interval(self) -> None:
        global _gf_last
        min_interval = get_settings().gf_min_interval_s
        async with _gf_lock:
            wait = min_interval - (time.monotonic() - _gf_last)
            if wait > 0:
                await asyncio.sleep(wait)
            _gf_last = time.monotonic()

    async def fetch_day_options(
        self, origin: str, dest: str, dep_date: date
    ) -> list[FlightOption] | None:
        """Flight options (times, carrier, stops, price) for one day; None when disabled/blocked."""
        if not get_settings().gf_enabled:
            return None
        params = {"tfs": build_tfs(origin, dest, dep_date), "hl": "en", "curr": "EUR"}
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
        }
        await self._respect_gf_interval()
        try:
            html = await self.client.get_text(FLIGHTS_URL, params=params, headers=headers)
        except Exception as exc:  # noqa: BLE001 - verification must degrade gracefully
            log.warning("GF fetch failed for %s-%s %s: %s", origin, dest, dep_date, exc)
            return None
        options = parse_flight_options(html, dep_date)
        if not options:
            log.warning(
                "GF response for %s-%s %s yielded no parseable options (blocked/format change?)",
                origin, dest, dep_date,
            )
            return None
        return options

    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None:
        options = await self.fetch_day_options(origin, dest, dep_date)
        if not options:
            return None
        cheapest = next((o for o in options if o["price_cents"] is not None), None)
        if cheapest is None:
            return None
        return DayFare(
            origin=origin,
            dest=dest,
            dep_date=dep_date,
            price_cents=cheapest["price_cents"],
            currency=cheapest["currency"],
            deep_link=deep_link(origin, dest, dep_date),
        )


register(GoogleFlightsConnector())
