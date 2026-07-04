"""Worker loop: python -m layoverlab.crawler.run

Runs CRAWLER_CONCURRENCY job coroutines (per-domain politeness stays guaranteed by
PoliteClient's per-domain locks) plus a scheduler tick that re-enqueues stale covered
routes weighted by demand.

SQLite fallback runs a single job coroutine: SQLite has no SELECT ... FOR UPDATE
SKIP LOCKED, and a claim's "running" status is invisible to other sessions until
commit, so concurrent claimers could double-claim the same job.
"""

import asyncio
import logging

from layoverlab.connectors.base import load_default_connectors
from layoverlab.crawler.budget import allowed_connectors, domain_for_connector
from layoverlab.crawler.prioritizer import CONNECTORS_FOR_BULK
from layoverlab.crawler.scheduler import enqueue_refresh_jobs
from layoverlab.crawler.service import claim_next_job, run_job
from layoverlab.db.session import get_engine, session_scope
from layoverlab.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("crawler")

IDLE_SLEEP_S = 5.0


def _domain_groups() -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    for connector in CONNECTORS_FOR_BULK:
        groups.setdefault(domain_for_connector(connector), []).append(connector)
    return list(groups.values())


async def process_one(connectors: list[str] | None = None) -> bool:
    """Claim and run a single job. Returns False when nothing is claimable."""
    with session_scope() as session:
        candidates = connectors if connectors is not None else list(CONNECTORS_FOR_BULK)
        allowed = allowed_connectors(session, candidates)
        if not allowed:
            return False
        job = claim_next_job(session, connectors=allowed)
        if job is None:
            return False
        await run_job(session, job)
        return True


async def _job_worker(name: str, connectors: list[str] | None) -> None:
    settings = get_settings()
    while True:
        if not settings.crawl_enabled:
            await asyncio.sleep(IDLE_SLEEP_S)
            continue
        try:
            worked = await process_one(connectors)
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("[%s] job processing crashed", name)
            worked = False
        if not worked:
            await asyncio.sleep(IDLE_SLEEP_S)


async def _scheduler_tick_loop() -> None:
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.sched_tick_s)
        if not settings.crawl_enabled:
            continue
        try:
            with session_scope() as session:
                enqueue_refresh_jobs(session)
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("scheduler tick crashed")


async def main() -> None:
    load_default_connectors()
    settings = get_settings()
    if not settings.crawl_enabled:
        log.warning("CRAWL_ENABLED=false — worker idle (jobs stay queued)")

    sqlite = get_engine().dialect.name == "sqlite"
    tasks: list[asyncio.Task] = []
    if sqlite:
        log.info("SQLite dialect: single job coroutine (no SKIP LOCKED support)")
        tasks.append(asyncio.create_task(_job_worker("w0", None)))
    else:
        groups = _domain_groups()
        n = max(settings.crawler_concurrency, 1)
        for i in range(n):
            connectors = groups[i] if i < len(groups) else None
            tasks.append(asyncio.create_task(_job_worker(f"w{i}", connectors)))
        log.info("started %d job coroutines (%d domain groups)", n, len(groups))
    tasks.append(asyncio.create_task(_scheduler_tick_loop()))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
