"""Smart-crawler behaviors: claim ordering, budgets, dead-lettering, refresh, stats, notify."""

import asyncio
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from layoverlab.connectors import base as connectors_base
from layoverlab.connectors.base import ConnectorDisabled, DayFare, register
from layoverlab.crawler import budget as budget_mod
from layoverlab.crawler.budget import allowed_connectors, budget_remaining, consume_budget
from layoverlab.crawler.coverage import bump_demand, effective_demand, record_success
from layoverlab.crawler.notify import wait_for_pair
from layoverlab.crawler.prioritizer import MAX_HUBS, PRIORITY_HUB, enqueue_for_search
from layoverlab.crawler.scheduler import enqueue_refresh_jobs, refresh_priority
from layoverlab.crawler.service import MAX_RETRIES, claim_next_job, run_job
from layoverlab.crawler.stats import get_stats
from layoverlab.db.models import CrawlJob, Fare, Route, RouteCoverage, utcnow
from tests.conftest import add_airport

D = date(2026, 8, 1)


@pytest.fixture()
def registry():
    saved = dict(connectors_base._REGISTRY)
    connectors_base._REGISTRY.clear()
    yield connectors_base._REGISTRY
    connectors_base._REGISTRY.clear()
    connectors_base._REGISTRY.update(saved)


class FakeConnector:
    def __init__(self, name: str, latency_s: float = 0.0, fail: Exception | None = None):
        self.name = name
        self.bulk = True
        self.latency_s = latency_s
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]:
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        self.calls.append((origin, dest))
        if self.fail is not None:
            raise self.fail
        return [
            DayFare(
                origin=origin, dest=dest, dep_date=month.replace(day=15),
                price_cents=1999, currency="EUR", deep_link=None,
            )
        ]

    async def routes_from(self, origin: str) -> list[str]:
        return []

    async def verify_day(self, origin: str, dest: str, dep_date: date):
        return None


def _seed_hubs(session, origins: list[str], dests: list[str], hubs: list[str]) -> None:
    for hub in hubs:
        for o in origins:
            session.add(Route(origin=o, dest=hub, carriers=["XX"], frequency_score=2.0, last_seen=utcnow()))
        for d in dests:
            session.add(Route(origin=hub, dest=d, carriers=["XX"], frequency_score=2.0, last_seen=utcnow()))
    session.flush()


def test_hub_fanout_capped_at_8_priority_30(session):
    add_airport(session, "BER", "DE")
    add_airport(session, "BKK", "TH")
    hubs = [f"H{i:02d}" for i in range(12)]
    for h in hubs:
        add_airport(session, h, "XX")
    _seed_hubs(session, ["BER"], ["BKK"], hubs)

    enqueue_for_search(session, "BER", "BKK", D, D)
    jobs = session.execute(select(CrawlJob)).scalars().all()
    hub_jobs = [j for j in jobs if (j.origin, j.dest) != ("BER", "BKK")]
    hub_airports = {j.origin for j in hub_jobs} | {j.dest for j in hub_jobs} - {"BER", "BKK"}
    assert len(hub_airports - {"BER", "BKK"}) <= MAX_HUBS == 8
    assert all(j.priority == PRIORITY_HUB == 30 for j in hub_jobs)


def test_direct_pair_and_cluster_claimed_before_hub_fanout(session):
    add_airport(session, "BER", "DE")
    add_airport(session, "ALC", "ES", cluster="ALC_C")
    add_airport(session, "VLC", "ES", cluster="ALC_C")
    for h in ["H01", "H02"]:
        add_airport(session, h, "XX")
    _seed_hubs(session, ["BER"], ["ALC", "VLC"], ["H01", "H02"])

    enqueue_for_search(session, "BER", "ALC", D, D)
    direct_pairs = {("BER", "ALC"), ("BER", "VLC")}
    claimed: list[tuple[str, str]] = []
    while (job := claim_next_job(session)) is not None:
        claimed.append((job.origin, job.dest))
    n_direct = len([p for p in claimed if p in direct_pairs])
    assert claimed[:n_direct] == [p for p in claimed if p in direct_pairs]
    assert set(claimed[:n_direct]) == direct_pairs


async def test_cold_start_direct_pair_covered_fast(session, registry):
    connector = FakeConnector("ryanair", latency_s=0.05)
    register(connector)
    register(FakeConnector("travelpayouts", latency_s=0.05))
    add_airport(session, "BER", "DE")
    add_airport(session, "ALC", "ES")
    hubs = [f"H{i:02d}" for i in range(8)]
    for h in hubs:
        add_airport(session, h, "XX")
    _seed_hubs(session, ["BER"], ["ALC"], hubs)

    enqueue_for_search(session, "BER", "ALC", D, D)
    start = time.monotonic()
    direct_done_at = None
    while (job := claim_next_job(session)) is not None:
        await run_job(session, job)
        fare = session.execute(
            select(Fare).where(Fare.origin == "BER", Fare.dest == "ALC")
        ).scalars().first()
        if fare is not None and direct_done_at is None:
            direct_done_at = time.monotonic() - start
    assert direct_done_at is not None
    assert direct_done_at < 15.0
    assert connector.calls[0] == ("BER", "ALC")


async def test_wait_for_pair_returns_when_jobs_terminal(session):
    add_airport(session, "BER", "DE")
    add_airport(session, "ALC", "ES")
    enqueue_for_search(session, "BER", "ALC", D, D)
    session.commit()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    assert await wait_for_pair(factory, "BER", "ALC", D, timeout_s=0.1) is False

    for job in session.execute(select(CrawlJob)).scalars():
        job.status = "done"
    session.commit()
    assert await wait_for_pair(factory, "BER", "ALC", D, timeout_s=5.0) is True


def test_refresh_tick_enqueues_stale_route_with_demand_priority(session, monkeypatch):
    now = utcnow()
    future_month = (now.date() + timedelta(days=40)).replace(day=1)
    session.add(
        RouteCoverage(
            origin="BER", dest="ALC", month=future_month, source="ryanair",
            last_success_at=now - timedelta(hours=30), fail_count=0,
            demand_score=5.0, demand_updated_at=now,
        )
    )
    session.add(
        RouteCoverage(
            origin="BER", dest="VLC", month=future_month, source="ryanair",
            last_success_at=now - timedelta(minutes=5), fail_count=0,
            demand_score=5.0, demand_updated_at=now,
        )
    )
    session.flush()

    created = enqueue_refresh_jobs(session, now=now)
    assert created == 1
    job = session.execute(select(CrawlJob)).scalar_one()
    assert (job.origin, job.dest) == ("BER", "ALC")
    assert job.priority == refresh_priority(5.0) == 50
    assert refresh_priority(20.0) == 90  # capped below user-search priority 100


def test_demand_score_bumps_and_decays(session):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    bump_demand(session, "BER", "ALC", D, "ryanair", now=now)
    bump_demand(session, "BER", "ALC", D, "ryanair", now=now)
    row = session.get(RouteCoverage, ("BER", "ALC", D, "ryanair"))
    assert row.demand_score == pytest.approx(2.0)
    later = now + timedelta(days=10)
    assert effective_demand(row, now=later) == pytest.approx(2.0 * 0.95**10)


def test_budget_exhaustion_pauses_claims_until_next_day(session, monkeypatch):
    monkeypatch.setattr(budget_mod, "get_settings", lambda: SimpleNamespace(crawl_daily_budget=2))
    fake_now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    consume_budget(session, "ryanair", now=fake_now)
    consume_budget(session, "ryanair", now=fake_now)
    assert budget_remaining(session, "services-api.ryanair.com", now=fake_now) == 0
    assert allowed_connectors(session, ["ryanair"], now=fake_now) == []

    session.add(CrawlJob(connector="ryanair", origin="BER", dest="ALC", month=D,
                         priority=100, status="pending", run_after=utcnow()))
    session.flush()
    assert claim_next_job(session, connectors=allowed_connectors(session, ["ryanair"], now=fake_now)) is None

    next_day = fake_now + timedelta(days=1)
    assert allowed_connectors(session, ["ryanair"], now=next_day) == ["ryanair"]
    assert claim_next_job(session, connectors=["ryanair"]) is not None


async def test_dead_letter_after_max_retries(session, registry):
    register(FakeConnector("ryanair", fail=RuntimeError("boom")))
    job = CrawlJob(connector="ryanair", origin="BER", dest="ALC", month=D,
                   priority=100, status="running", run_after=utcnow())
    session.add(job)
    session.flush()

    for i in range(1, MAX_RETRIES + 1):
        await run_job(session, job)
        assert job.retries == i
        assert job.status == ("dead" if i == MAX_RETRIES else "error")
    coverage = session.get(RouteCoverage, ("BER", "ALC", D, "ryanair"))
    assert coverage.fail_count == MAX_RETRIES
    assert get_stats(session)["jobs"]["dead"] == 1


async def test_connector_disabled_skips_quietly(session, registry):
    register(FakeConnector("ryanair", fail=ConnectorDisabled("no token")))
    job = CrawlJob(connector="ryanair", origin="BER", dest="ALC", month=D,
                   priority=100, status="running", run_after=utcnow())
    session.add(job)
    session.flush()

    await run_job(session, job)
    assert job.status == "done"
    assert job.retries == 0
    assert session.get(RouteCoverage, ("BER", "ALC", D, "ryanair")) is None
    assert budget_remaining(session, "services-api.ryanair.com") == 500


def test_get_stats(session):
    now = utcnow()
    for status in ["pending", "pending", "running", "done", "dead"]:
        session.add(CrawlJob(connector="ryanair", origin="BER", dest="ALC", month=D,
                             priority=10, status=status, run_after=now,
                             created_at=now - timedelta(minutes=30), updated_at=now))
    session.add(CrawlJob(connector="travelpayouts", origin="BER", dest="ALC", month=D,
                         priority=10, status="error", run_after=now,
                         created_at=now, updated_at=now))
    record_success(session, "BER", "ALC", D, "ryanair")
    consume_budget(session, "ryanair", n=100)
    session.flush()

    stats = get_stats(session, now=now)
    assert stats["jobs"] == {"pending": 2, "running": 1, "done": 1, "error": 1, "dead": 1}
    assert stats["success_rate_24h"]["ryanair"] == 0.5
    assert stats["success_rate_24h"]["travelpayouts"] == 0.0
    assert stats["budget_remaining"]["services-api.ryanair.com"] == 400
    assert stats["oldest_pending_age_s"] == pytest.approx(1800, abs=60)
    assert stats["coverage_rows"] == 1
