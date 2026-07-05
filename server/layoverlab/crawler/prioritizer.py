"""Demand-driven crawl planning: user searches enqueue the fare coverage the engine will need."""

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from layoverlab.connectors.coverage import bulk_sources, sources_for_route
from layoverlab.crawler.coverage import bump_demand
from layoverlab.db.models import Airport, CrawlJob, Route, utcnow

log = logging.getLogger(__name__)

MAX_HUBS = 8
MAX_JOBS_PER_SEARCH = 200
PRIORITY_DIRECT = 100
PRIORITY_HUB = 30


def _months_in_window(date_from: date, date_to: date) -> list[date]:
    months = []
    cursor = date_from.replace(day=1)
    while cursor <= date_to:
        months.append(cursor)
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return months


def _expand_cluster(session: Session, iata: str) -> list[str]:
    airport = session.get(Airport, iata)
    if not airport:
        return [iata]
    result = {iata}
    if airport.cluster_id:
        siblings = session.execute(
            select(Airport.iata).where(Airport.cluster_id == airport.cluster_id)
        ).scalars()
        result.update(siblings)
    return sorted(result)


def _candidate_hubs(session: Session, origins: list[str], dests: list[str]) -> list[str]:
    """Airports reachable from origin AND connecting to dest, ranked by frequency score."""
    from_origin = {
        r.dest: r.frequency_score
        for r in session.execute(select(Route).where(Route.origin.in_(origins))).scalars()
    }
    to_dest = {
        r.origin: r.frequency_score
        for r in session.execute(select(Route).where(Route.dest.in_(dests))).scalars()
    }
    hubs = {
        iata: from_origin[iata] + to_dest[iata]
        for iata in from_origin.keys() & to_dest.keys()
        if iata not in origins and iata not in dests
    }
    ranked = sorted(hubs, key=lambda h: hubs[h], reverse=True)
    return ranked[:MAX_HUBS]


def _active_job(session: Session, connector: str, origin: str, dest: str, month: date) -> CrawlJob | None:
    return (
        session.execute(
            select(CrawlJob)
            .where(
                CrawlJob.connector == connector,
                CrawlJob.origin == origin,
                CrawlJob.dest == dest,
                CrawlJob.month == month,
                CrawlJob.status.in_(["pending", "error"]),
            )
            .order_by(CrawlJob.id)
        )
        .scalars()
        .first()
    )


def _upsert_job(session: Session, connector: str, origin: str, dest: str, month: date, priority: int) -> bool:
    existing = _active_job(session, connector, origin, dest, month)
    if existing:
        existing.priority = max(existing.priority, priority)
        existing.status = "pending"
        return False
    nested = session.begin_nested()
    session.add(
        CrawlJob(
            connector=connector, origin=origin, dest=dest, month=month,
            priority=priority, status="pending", run_after=utcnow(),
        )
    )
    try:
        session.flush()
    except IntegrityError:
        nested.rollback()
        existing = _active_job(session, connector, origin, dest, month)
        if existing:
            existing.priority = max(existing.priority, priority)
            existing.status = "pending"
        return False
    return True


def enqueue_for_search(session: Session, origin: str, dest: str, date_from: date, date_to: date) -> int:
    """Create/bump crawl jobs covering direct pair, cluster variants and top stopover hubs."""
    origins = _expand_cluster(session, origin)
    dests = _expand_cluster(session, dest)
    months = _months_in_window(date_from, date_to)
    hubs = _candidate_hubs(session, origins, dests)

    created = 0
    budget = MAX_JOBS_PER_SEARCH
    bulk = set(bulk_sources())

    def add(o: str, d: str, month: date, priority: int) -> None:
        nonlocal created, budget
        if budget <= 0 or o == d:
            return
        for connector in sources_for_route(session, o, d):
            if connector not in bulk:
                continue
            if _upsert_job(session, connector, o, d, month, priority):
                created += 1
            budget -= 1

    for month in months:
        for o in origins:
            for d in dests:
                add(o, d, month, priority=PRIORITY_DIRECT)  # direct pair(s): highest priority
                for connector in sorted(bulk):
                    bump_demand(session, o, d, month, connector)
        for hub in hubs:
            for o in origins:
                add(o, hub, month, priority=PRIORITY_HUB)  # origin -> hub
            for d in dests:
                add(hub, d, month, priority=PRIORITY_HUB)  # hub -> dest
    session.flush()
    log.info("enqueued %d new jobs for %s->%s (%d hubs)", created, origin, dest, len(hubs))
    return created
