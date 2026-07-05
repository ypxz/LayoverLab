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
import time

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from layoverlab.connectors.base import load_default_connectors
from layoverlab.connectors.coverage import bulk_sources, log_disabled_sources
from layoverlab.crawler.budget import allowed_connectors, domain_for_connector
from layoverlab.crawler.heartbeat import beat
from layoverlab.crawler.scheduler import enqueue_refresh_jobs
from layoverlab.crawler.service import claim_next_job, run_job
from layoverlab.db.session import get_engine, session_scope
from layoverlab.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("crawler")

IDLE_SLEEP_S = 5.0
MIGRATION_POLL_S = 2.0
REQUIRED_TABLES = frozenset({"crawl_jobs", "request_budgets", "route_coverage", "fares"})


def wait_for_migrations(
    engine: Engine, timeout_s: float | None = None, poll_s: float = MIGRATION_POLL_S
) -> None:
    """Block until the API's `alembic upgrade head` has created the tables the worker
    needs (bounded wait), so a first boot never crash-loops on UndefinedTable."""
    timeout_s = get_settings().worker_db_wait_s if timeout_s is None else timeout_s
    deadline = time.monotonic() + timeout_s
    while True:
        missing: set[str] | str
        try:
            missing = REQUIRED_TABLES - set(inspect(engine).get_table_names())
            if not missing:
                return
        except SQLAlchemyError as exc:
            missing = f"db not reachable: {exc.__class__.__name__}"
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"database schema not ready after {timeout_s:.0f}s (missing: {missing}); "
                "is the api container running `alembic upgrade head`?"
            )
        log.info("waiting for migrations (%s)", missing)
        time.sleep(min(poll_s, max(0.0, deadline - time.monotonic())))


def _domain_groups() -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    for connector in bulk_sources():
        groups.setdefault(domain_for_connector(connector), []).append(connector)
    return list(groups.values())


def _worker_assignments(groups: list[list[str]], concurrency: int) -> list[list[str] | None]:
    """One coroutine per domain group at minimum, so no enabled source is ever starved;
    extra coroutines (None) claim from any domain."""
    n = max(concurrency, len(groups), 1)
    return [groups[i] if i < len(groups) else None for i in range(n)]


async def process_one(connectors: list[str] | None = None) -> bool:
    """Claim and run a single job. Returns False when nothing is claimable."""
    with session_scope() as session:
        candidates = connectors if connectors is not None else bulk_sources()
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
        _beat_safe(name)
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


def _beat_safe(name: str) -> None:
    try:
        with session_scope() as session:
            beat(session)
    except Exception:  # noqa: BLE001 - liveness must never kill the loop
        log.exception("[%s] heartbeat failed", name)


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
    wait_for_migrations(get_engine())
    load_default_connectors()
    log_disabled_sources()
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
        assignments = _worker_assignments(groups, settings.crawler_concurrency)
        for i, connectors in enumerate(assignments):
            tasks.append(asyncio.create_task(_job_worker(f"w{i}", connectors)))
        log.info("started %d job coroutines (%d domain groups)", len(assignments), len(groups))
    tasks.append(asyncio.create_task(_scheduler_tick_loop()))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
