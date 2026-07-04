from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from layoverlab.db.models import Airport, AirportCluster, Base, Fare, GroundLink


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        yield s


def add_airport(s: Session, iata: str, country: str = "DE", cluster: str | None = None) -> None:
    if cluster and s.get(AirportCluster, cluster) is None:
        s.add(AirportCluster(id=cluster, name=cluster))
        s.flush()
    s.add(
        Airport(
            iata=iata, name=f"{iata} Airport", city=iata, country_code=country,
            lat=0.0, lon=0.0, cluster_id=cluster,
        )
    )
    s.flush()


def add_fare(
    s: Session, origin: str, dest: str, dep: date, cents: int, source: str = "ryanair"
) -> None:
    now = datetime.now(timezone.utc)
    s.add(
        Fare(
            origin=origin, dest=dest, dep_date=dep, source=source,
            min_price_cents=cents, currency="EUR",
            deep_link=f"https://example.com/{origin}{dest}{dep}",
            fetched_at=now, expires_at=now + timedelta(hours=48),
        )
    )
    s.flush()


def add_ground(s: Session, a: str, b: str, minutes: int = 60, cents: int = 1000) -> None:
    s.add(GroundLink(from_iata=a, to_iata=b, mode="train", minutes=minutes, price_cents=cents))
    s.add(GroundLink(from_iata=b, to_iata=a, mode="train", minutes=minutes, price_cents=cents))
    s.flush()
