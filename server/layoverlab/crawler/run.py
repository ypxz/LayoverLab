"""Worker loop: python -m layoverlab.crawler.run

Processes crawl jobs continuously; re-enqueues stale hot fares daily.
"""

import asyncio
import logging

from sqlalchemy import func, select

from layoverlab.connectors.base import load_default_connectors
from layoverlab.connectors.coverage import log_disabled_sources
from layoverlab.crawler.service import claim_next_job, run_job
from layoverlab.db.models import CrawlJob, utcnow
from layoverlab.db.session import session_scope
from layoverlab.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("crawler")

IDLE_SLEEP_S = 5.0


async def process_one() -> bool:
    """Claim and run a single job. Returns False when queue is empty."""
    with session_scope() as session:
        job = claim_next_job(session)
        if job is None:
            return False
        await run_job(session, job)
        return True


async def refresh_stale_jobs() -> None:
    """Re-open done jobs so previously requested coverage stays fresh."""
    with session_scope() as session:
        stale_cutoff = utcnow()
        stale = session.execute(
            select(CrawlJob).where(
                CrawlJob.status == "done",
                CrawlJob.month >= func.date(stale_cutoff),
            )
        ).scalars()
        n = 0
        for job in stale:
            job.status = "pending"
            job.run_after = stale_cutoff
            n += 1
        log.info("re-opened %d jobs for refresh", n)


async def main() -> None:
    load_default_connectors()
    log_disabled_sources()
    settings = get_settings()
    if not settings.crawl_enabled:
        log.warning("CRAWL_ENABLED=false — worker idle (jobs stay queued)")
    last_refresh = utcnow()
    while True:
        if not settings.crawl_enabled:
            await asyncio.sleep(IDLE_SLEEP_S)
            continue
        try:
            worked = await process_one()
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("job processing crashed")
            worked = False
        if (utcnow() - last_refresh).total_seconds() > 24 * 3600:
            await refresh_stale_jobs()
            last_refresh = utcnow()
        if not worked:
            await asyncio.sleep(IDLE_SLEEP_S)


if __name__ == "__main__":
    asyncio.run(main())
