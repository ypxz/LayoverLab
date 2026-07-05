"""Load an in-memory fare slice for a search window and expose graph edges."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from layoverlab.db.models import Airport, Fare, GroundLink

log = logging.getLogger(__name__)

CLUSTER_TRANSFER_MINUTES = 120
CLUSTER_TRANSFER_CENTS = 2000  # €20 default intra-cluster transfer (bus/train)
SAME_DAY_GROUND_MAX_MINUTES = 360


@dataclass
class FlightEdge:
    dest: str
    price_cents: int
    source: str
    deep_link: str | None
    fetched_at: datetime


@dataclass
class GroundEdge:
    dest: str
    price_cents: int
    minutes: int
    mode: str  # "train" | "bus" | "transfer"
    day_offset: int = 0


@dataclass
class FareSlice:
    date_from: date
    horizon_days: int
    flights: dict[tuple[str, int], list[FlightEdge]] = field(default_factory=dict)
    ground: dict[str, list[GroundEdge]] = field(default_factory=dict)
    airport_country: dict[str, str] = field(default_factory=dict)
    airport_cluster: dict[str, str | None] = field(default_factory=dict)
    cluster_members: dict[str, list[str]] = field(default_factory=dict)

    def day_index(self, d: date) -> int:
        return (d - self.date_from).days

    def date_of(self, day: int) -> date:
        return self.date_from + timedelta(days=day)

    def cluster_of(self, iata: str) -> list[str]:
        cluster = self.airport_cluster.get(iata)
        if cluster and cluster in self.cluster_members:
            return self.cluster_members[cluster]
        return [iata]


def load_slice(session: Session, date_from: date, date_to: date, extra_days: int) -> FareSlice:
    horizon_days = (date_to - date_from).days + extra_days
    horizon_end = date_from + timedelta(days=horizon_days)
    fslice = FareSlice(date_from=date_from, horizon_days=horizon_days)

    # cheapest fare per (origin, dest, day) across sources
    now = datetime.now(timezone.utc)
    best: dict[tuple[str, str, date], Fare] = {}
    fares = session.execute(
        select(Fare).where(Fare.dep_date >= date_from, Fare.dep_date <= horizon_end)
    ).scalars()
    for fare in fares:
        expires = fare.expires_at
        if expires is not None:
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= now:
                continue
        if fare.currency != "EUR":
            log.warning(
                "skipping non-EUR fare %s->%s %s (%s %s from %s)",
                fare.origin, fare.dest, fare.dep_date, fare.min_price_cents, fare.currency, fare.source,
            )
            continue
        key = (fare.origin, fare.dest, fare.dep_date)
        if key not in best or fare.min_price_cents < best[key].min_price_cents:
            best[key] = fare
    for (origin, dest, dep), fare in best.items():
        day = fslice.day_index(dep)
        fslice.flights.setdefault((origin, day), []).append(
            FlightEdge(
                dest=dest,
                price_cents=fare.min_price_cents,
                source=fare.source,
                deep_link=fare.deep_link,
                fetched_at=fare.fetched_at,
            )
        )

    # explicit ground corridors
    explicit: set[tuple[str, str]] = set()
    for link in session.execute(select(GroundLink)).scalars():
        explicit.add((link.from_iata, link.to_iata))
        fslice.ground.setdefault(link.from_iata, []).append(
            GroundEdge(
                dest=link.to_iata,
                price_cents=link.price_cents,
                minutes=link.minutes,
                mode=link.mode,
                day_offset=0 if link.minutes <= SAME_DAY_GROUND_MAX_MINUTES else 1,
            )
        )

    # airports: country + cluster info, default intra-cluster transfers
    airports = session.execute(select(Airport)).scalars().all()
    for airport in airports:
        fslice.airport_country[airport.iata] = airport.country_code
        fslice.airport_cluster[airport.iata] = airport.cluster_id
        if airport.cluster_id:
            fslice.cluster_members.setdefault(airport.cluster_id, []).append(airport.iata)
    for members in fslice.cluster_members.values():
        for a in members:
            for b in members:
                if a != b and (a, b) not in explicit:
                    fslice.ground.setdefault(a, []).append(
                        GroundEdge(
                            dest=b,
                            price_cents=CLUSTER_TRANSFER_CENTS,
                            minutes=CLUSTER_TRANSFER_MINUTES,
                            mode="transfer",
                        )
                    )
    return fslice
