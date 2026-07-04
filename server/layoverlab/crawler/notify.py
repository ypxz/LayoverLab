"""Wait for a searched pair's direct+cluster crawl jobs to reach a terminal state.

Consumed by the API layer (agent G) to stream fresh results as fares land.
"""

import asyncio
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from layoverlab.db.models import Airport, CrawlJob

TERMINAL_STATUSES = ("done", "dead")
POLL_INTERVAL_S = 1.0


def _cluster_variants(session: Session, iata: str) -> list[str]:
    airport = session.get(Airport, iata)
    if airport is None or airport.cluster_id is None:
        return [iata]
    siblings = session.execute(
        select(Airport.iata).where(Airport.cluster_id == airport.cluster_id)
    ).scalars()
    return sorted({iata, *siblings})


def pair_covered(session: Session, origin: str, dest: str, month: date) -> bool:
    """True when every direct+cluster job for the pair/month is done or dead."""
    origins = _cluster_variants(session, origin)
    dests = _cluster_variants(session, dest)
    open_jobs = session.execute(
        select(CrawlJob.id)
        .where(
            CrawlJob.origin.in_(origins),
            CrawlJob.dest.in_(dests),
            CrawlJob.month == month.replace(day=1),
            CrawlJob.status.not_in(TERMINAL_STATUSES),
        )
        .limit(1)
    ).first()
    return open_jobs is None


async def wait_for_pair(
    session_factory: sessionmaker, origin: str, dest: str, month: date, timeout_s: float = 30.0
) -> bool:
    """Poll every second until all direct+cluster jobs for (origin, dest, month) are
    terminal (done/dead). Returns True when covered, False on timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        with session_factory() as session:
            if pair_covered(session, origin, dest, month):
                return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(min(POLL_INTERVAL_S, max(0.0, deadline - loop.time())))
