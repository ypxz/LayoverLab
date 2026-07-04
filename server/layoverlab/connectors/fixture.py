"""Deterministic synthetic fare connector for tests and the local fixture stack.

Registered only when FIXTURE_CONNECTOR=true. Fares are a pure function of
(origin, dest, dep_date): same inputs always produce the same prices, so the
route-matrix harness and E2E suites can assert exact expectations with zero
live HTTP.

Covered route classes:
- direct cheap LCC intra-EU pair: BER<->ALC (also the round-trip-friendly pair;
  prices rise monotonically within a month so cheapest outbound/inbound days align)
- direct expensive + cheaper 2-leg stopover combo: HAM->ALC vs HAM->BCN->ALC
- cluster-only pair: STN->BGY (searches for LON/MIL siblings must use clusters)
- ground-corridor-dependent pair: BRU->PMI (CGN reaches it via CGN->BRU train)
- long-haul pair: BER->BKK direct vs cheaper BER->DXB->BKK
- domestic pair: BER<->MUC
- island pair: MAD<->PMI
"""

import calendar
import hashlib
from datetime import date, timedelta

from sqlalchemy.orm import Session

from layoverlab.connectors.base import DayFare
from layoverlab.db.models import Airport, AirportCluster, GroundLink

# (origin, dest) -> base price in cents
FIXTURE_FARES: dict[tuple[str, str], int] = {
    ("BER", "ALC"): 2900,
    ("ALC", "BER"): 3100,
    ("HAM", "ALC"): 12000,
    ("HAM", "BCN"): 3000,
    ("BCN", "ALC"): 2500,
    ("STN", "BGY"): 2200,
    ("BRU", "PMI"): 3500,
    ("BER", "BKK"): 55000,
    ("BER", "DXB"): 18000,
    ("DXB", "BKK"): 15000,
    ("BER", "MUC"): 8000,
    ("MAD", "PMI"): 2500,
    ("PMI", "MAD"): 2600,
}

# iata, name, city, country, cluster_id
FIXTURE_AIRPORTS: list[tuple[str, str, str, str, str | None]] = [
    ("BER", "Berlin Brandenburg", "Berlin", "DE", None),
    ("ALC", "Alicante", "Alicante", "ES", None),
    ("HAM", "Hamburg", "Hamburg", "DE", None),
    ("BCN", "Barcelona El Prat", "Barcelona", "ES", "BCN"),
    ("LHR", "London Heathrow", "London", "GB", "LON"),
    ("STN", "London Stansted", "London", "GB", "LON"),
    ("MXP", "Milan Malpensa", "Milan", "IT", "MIL"),
    ("BGY", "Milan Bergamo", "Milan", "IT", "MIL"),
    ("CGN", "Cologne Bonn", "Cologne", "DE", None),
    ("BRU", "Brussels", "Brussels", "BE", "BRU"),
    ("PMI", "Palma de Mallorca", "Palma", "ES", None),
    ("MAD", "Madrid Barajas", "Madrid", "ES", None),
    ("MUC", "Munich", "Munich", "DE", "MUC"),
    ("DXB", "Dubai International", "Dubai", "AE", "DXB"),
    ("BKK", "Bangkok Suvarnabhumi", "Bangkok", "TH", "BKK"),
]

FIXTURE_CLUSTERS: dict[str, str] = {
    "BCN": "Barcelona",
    "LON": "London",
    "MIL": "Milan",
    "BRU": "Brussels",
    "MUC": "Munich",
    "DXB": "Dubai",
    "BKK": "Bangkok",
}

# from, to, mode, minutes, price_cents (seeded in both directions)
FIXTURE_GROUND_LINKS: list[tuple[str, str, str, int, int]] = [
    ("CGN", "BRU", "train", 110, 2900),
]

MAX_JITTER_PCT = 15

# monotonic day-of-month pricing so round-trip date windows combine deterministically
TREND_PAIRS: set[tuple[str, str]] = {("BER", "ALC"), ("ALC", "BER")}
TREND_STEP_CENTS = 25


def fixture_price_cents(origin: str, dest: str, dep_date: date) -> int | None:
    """Deterministic price for a pair/day, or None when the pair is not served."""
    base = FIXTURE_FARES.get((origin, dest))
    if base is None:
        return None
    if (origin, dest) in TREND_PAIRS:
        return base + dep_date.day * TREND_STEP_CENTS
    digest = hashlib.sha256(f"{origin}{dest}{dep_date.isoformat()}".encode()).digest()
    jitter_pct = digest[0] % (2 * MAX_JITTER_PCT + 1) - MAX_JITTER_PCT
    return base + base * jitter_pct // 100


def fixture_deep_link(origin: str, dest: str, dep_date: date) -> str:
    return f"https://fixture.invalid/book/{origin}/{dest}/{dep_date.isoformat()}"


def month_fares(origin: str, dest: str, month: date) -> list[DayFare]:
    if (origin, dest) not in FIXTURE_FARES:
        return []
    month_start = month.replace(day=1)
    days = calendar.monthrange(month_start.year, month_start.month)[1]
    fares: list[DayFare] = []
    for offset in range(days):
        dep = month_start + timedelta(days=offset)
        price = fixture_price_cents(origin, dest, dep)
        assert price is not None
        fares.append(
            DayFare(
                origin=origin,
                dest=dest,
                dep_date=dep,
                price_cents=price,
                currency="EUR",
                deep_link=fixture_deep_link(origin, dest, dep),
            )
        )
    return fares


class FixtureConnector:
    name = "fixture"

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]:
        return month_fares(origin, dest, month)

    async def routes_from(self, origin: str) -> list[str]:
        return sorted(d for (o, d) in FIXTURE_FARES if o == origin)

    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None:
        price = fixture_price_cents(origin, dest, dep_date)
        if price is None:
            return None
        return DayFare(
            origin=origin,
            dest=dest,
            dep_date=dep_date,
            price_cents=price,
            currency="EUR",
            deep_link=fixture_deep_link(origin, dest, dep_date),
        )


def seed_fixture_stack(session: Session, months: list[date]) -> int:
    """Idempotently seed airports/clusters/ground links and fixture fares for the given months."""
    from layoverlab.crawler.service import upsert_fares

    for cid, name in FIXTURE_CLUSTERS.items():
        if session.get(AirportCluster, cid) is None:
            session.add(AirportCluster(id=cid, name=name))
    session.flush()
    for iata, name, city, country, cluster in FIXTURE_AIRPORTS:
        if session.get(Airport, iata) is None:
            session.add(
                Airport(
                    iata=iata, name=name, city=city, country_code=country,
                    lat=0.0, lon=0.0, cluster_id=cluster,
                )
            )
    session.flush()
    existing_links = {
        (link.from_iata, link.to_iata)
        for link in session.query(GroundLink).all()
    }
    for a, b, mode, minutes, cents in FIXTURE_GROUND_LINKS:
        for x, y in ((a, b), (b, a)):
            if (x, y) not in existing_links:
                session.add(
                    GroundLink(
                        from_iata=x, to_iata=y, mode=mode, minutes=minutes,
                        price_cents=cents, currency="EUR",
                    )
                )
    session.flush()
    total = 0
    for month in months:
        for origin, dest in FIXTURE_FARES:
            total += upsert_fares(session, month_fares(origin, dest, month), source="fixture")
    session.flush()
    return total
