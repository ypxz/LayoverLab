"""Crawler observability: get_stats(session) -> dict.

Agent G mounts this at /api/admin/crawler.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from layoverlab.crawler.budget import CONNECTOR_DOMAINS, budget_remaining
from layoverlab.db.models import CrawlJob, RouteCoverage, utcnow


def get_stats(session: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()

    counts = {
        status: n
        for status, n in session.execute(
            select(CrawlJob.status, func.count()).group_by(CrawlJob.status)
        ).all()
    }
    jobs = {s: counts.get(s, 0) for s in ("pending", "running", "done", "error", "dead")}

    since = now - timedelta(hours=24)
    outcomes: dict[str, dict[str, int]] = {}
    for connector, status, n in session.execute(
        select(CrawlJob.connector, CrawlJob.status, func.count())
        .where(CrawlJob.updated_at >= since, CrawlJob.status.in_(["done", "error", "dead"]))
        .group_by(CrawlJob.connector, CrawlJob.status)
    ).all():
        rates = outcomes.setdefault(connector, {"done": 0, "failed": 0})
        rates["done" if status == "done" else "failed"] += n
    success_rate_24h = {
        connector: round(r["done"] / (r["done"] + r["failed"]), 4) if (r["done"] + r["failed"]) else 0.0
        for connector, r in outcomes.items()
    }

    budget = {
        domain: budget_remaining(session, domain, now) for domain in sorted(set(CONNECTOR_DOMAINS.values()))
    }

    oldest_pending = session.execute(
        select(func.min(CrawlJob.created_at)).where(CrawlJob.status == "pending")
    ).scalar_one_or_none()
    oldest_pending_age_s = None
    if oldest_pending is not None:
        if oldest_pending.tzinfo is None:
            oldest_pending = oldest_pending.replace(tzinfo=now.tzinfo)
        oldest_pending_age_s = max(0.0, (now - oldest_pending).total_seconds())

    coverage_rows = session.execute(select(func.count()).select_from(RouteCoverage)).scalar_one()

    return {
        "jobs": jobs,
        "success_rate_24h": success_rate_24h,
        "budget_remaining": budget,
        "oldest_pending_age_s": oldest_pending_age_s,
        "coverage_rows": coverage_rows,
    }
