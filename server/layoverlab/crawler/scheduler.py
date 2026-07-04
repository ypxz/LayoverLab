"""Periodic refresh: re-enqueue covered routes whose fares are stale, demand-weighted."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from layoverlab.crawler.coverage import effective_demand
from layoverlab.db.models import RouteCoverage, utcnow

log = logging.getLogger(__name__)

REFRESH_PRIORITY_CAP = 90
DEMAND_PRIORITY_SCALE = 10.0


def refresh_priority(demand: float) -> int:
    return min(REFRESH_PRIORITY_CAP, max(1, round(demand * DEMAND_PRIORITY_SCALE)))


def enqueue_refresh_jobs(session: Session, now: datetime | None = None) -> int:
    from layoverlab.crawler.prioritizer import _upsert_job
    from layoverlab.settings import get_settings

    now = now or utcnow()
    stale_before = now - timedelta(hours=get_settings().fare_ttl_hours / 2)
    current_month = now.date().replace(day=1)
    rows = session.execute(
        select(RouteCoverage).where(
            RouteCoverage.last_success_at.is_not(None),
            RouteCoverage.last_success_at < stale_before,
            RouteCoverage.month >= current_month,
        )
    ).scalars()
    created = 0
    for row in rows:
        priority = refresh_priority(effective_demand(row, now))
        if _upsert_job(session, row.source, row.origin, row.dest, row.month, priority):
            created += 1
    session.flush()
    if created:
        log.info("refresh tick enqueued %d stale-route jobs", created)
    return created
