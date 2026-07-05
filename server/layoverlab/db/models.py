import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AirportCluster(Base):
    __tablename__ = "airport_clusters"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)  # e.g. "LON"
    name: Mapped[str] = mapped_column(String(64))


class Airport(Base):
    __tablename__ = "airports"

    iata: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    city: Mapped[str] = mapped_column(String(96), default="")
    country_code: Mapped[str] = mapped_column(String(2), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    tz: Mapped[str | None] = mapped_column(Text, nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(
        ForeignKey("airport_clusters.id"), nullable=True, index=True
    )


class GroundLink(Base):
    __tablename__ = "ground_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_iata: Mapped[str] = mapped_column(String(3), index=True)
    to_iata: Mapped[str] = mapped_column(String(3), index=True)
    mode: Mapped[str] = mapped_column(String(16))  # "train" | "bus"
    minutes: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")


class Route(Base):
    __tablename__ = "routes"

    origin: Mapped[str] = mapped_column(String(3), primary_key=True)
    dest: Mapped[str] = mapped_column(String(3), primary_key=True)
    carriers: Mapped[list] = mapped_column(JSON, default=list)
    frequency_score: Mapped[float] = mapped_column(Float, default=1.0)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Fare(Base):
    __tablename__ = "fares"

    origin: Mapped[str] = mapped_column(String(3), primary_key=True)
    dest: Mapped[str] = mapped_column(String(3), primary_key=True)
    dep_date: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    min_price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    deep_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"
    __table_args__ = (
        Index(
            "uq_crawl_jobs_active",
            "connector",
            "origin",
            "dest",
            "month",
            unique=True,
            postgresql_where=text("status IN ('pending', 'error')"),
            sqlite_where=text("status IN ('pending', 'error')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connector: Mapped[str] = mapped_column(String(32))
    origin: Mapped[str] = mapped_column(String(3))
    dest: Mapped[str] = mapped_column(String(3))
    month: Mapped[date] = mapped_column(Date)  # first day of month
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RouteCoverage(Base):
    __tablename__ = "route_coverage"

    origin: Mapped[str] = mapped_column(String(3), primary_key=True)
    dest: Mapped[str] = mapped_column(String(3), primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    demand_score: Mapped[float] = mapped_column(Float, default=0.0)
    demand_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RequestBudget(Base):
    __tablename__ = "request_budgets"

    domain: Mapped[str] = mapped_column(String(128), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    used: Mapped[int] = mapped_column(Integer, default=0)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g. "crawler"
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItinerarySnapshot(Base):
    __tablename__ = "itineraries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON)
