"""Crawl job execution: claim pending jobs, run connectors, upsert fares."""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from layoverlab.connectors.base import ConnectorDisabled, DayFare, get_connector
from layoverlab.crawler.budget import consume_budget
from layoverlab.crawler.coverage import record_failure, record_success
from layoverlab.db.models import CrawlJob, Fare, Route, utcnow
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

RETRY_BACKOFF = timedelta(minutes=15)
MAX_RETRIES = 5


def upsert_fares(session: Session, fares: list[DayFare], source: str) -> int:
    ttl = timedelta(hours=get_settings().fare_ttl_hours)
    now = utcnow()
    for fare in fares:
        key = dict(origin=fare["origin"], dest=fare["dest"], dep_date=fare["dep_date"], source=source)
        existing = session.get(Fare, tuple(key.values()))
        if existing:
            existing.min_price_cents = fare["price_cents"]
            existing.currency = fare["currency"]
            existing.deep_link = fare["deep_link"]
            existing.fetched_at = now
            existing.expires_at = now + ttl
        else:
            session.add(
                Fare(
                    **key,
                    min_price_cents=fare["price_cents"],
                    currency=fare["currency"],
                    deep_link=fare["deep_link"],
                    fetched_at=now,
                    expires_at=now + ttl,
                )
            )
    return len(fares)


def _touch_route(session: Session, origin: str, dest: str, carrier: str) -> None:
    route = session.get(Route, (origin, dest))
    if route:
        carriers = set(route.carriers or [])
        carriers.add(carrier)
        route.carriers = sorted(carriers)
        route.last_seen = utcnow()
        route.frequency_score = max(route.frequency_score, float(len(carriers)))
    else:
        session.add(
            Route(origin=origin, dest=dest, carriers=[carrier], frequency_score=1.0, last_seen=utcnow())
        )


def claim_next_job(session: Session, connectors: list[str] | None = None) -> CrawlJob | None:
    stmt = (
        select(CrawlJob)
        .where(CrawlJob.status.in_(["pending", "error"]), CrawlJob.run_after <= utcnow())
        .order_by(CrawlJob.priority.desc(), CrawlJob.id.asc())
        .limit(1)
    )
    if connectors is not None:
        stmt = stmt.where(CrawlJob.connector.in_(connectors))
    if session.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = session.execute(stmt).scalar_one_or_none()
    if job:
        job.status = "running"
        session.flush()
    return job


async def run_job(session: Session, job: CrawlJob) -> int:
    connector = get_connector(job.connector)
    try:
        fares = await connector.fetch_month(job.origin, job.dest, job.month)
    except ConnectorDisabled as exc:
        job.status = "done"
        job.last_error = f"disabled: {exc}"
        log.info("job %d skipped (%s disabled)", job.id, job.connector)
        return 0
    except Exception as exc:  # noqa: BLE001 - job isolation: any failure marks the job, not the worker
        consume_budget(session, job.connector)
        record_failure(session, job.origin, job.dest, job.month, job.connector)
        job.retries += 1
        job.last_error = str(exc)[:500]
        if job.retries >= MAX_RETRIES:
            job.status = "dead"
            log.error("job %d dead after %d retries: %s", job.id, job.retries, exc)
        else:
            job.status = "error"
            job.run_after = utcnow() + job.retries * RETRY_BACKOFF
            log.warning("job %d failed (retry %d/%d): %s", job.id, job.retries, MAX_RETRIES, exc)
        return 0
    consume_budget(session, job.connector)
    count = upsert_fares(session, fares, source=connector.name)
    if fares:
        _touch_route(session, job.origin, job.dest, connector.name)
    record_success(session, job.origin, job.dest, job.month, job.connector)
    job.status = "done"
    job.last_error = None
    log.info("job %d %s %s->%s %s: %d fares", job.id, job.connector, job.origin, job.dest, job.month, count)
    return count
