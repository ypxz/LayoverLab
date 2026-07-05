"""Worker liveness heartbeat, persisted in the worker_heartbeats table.

The crawler worker upserts its row every loop iteration; the API surfaces
staleness via /api/health and the search `done` meta so a dead worker is
visible instead of silently producing zero results.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from layoverlab.db.models import WorkerHeartbeat, utcnow
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

DEFAULT_WORKER_ID = "crawler"


def beat(session: Session, worker_id: str = DEFAULT_WORKER_ID) -> None:
    row = session.get(WorkerHeartbeat, worker_id)
    if row is None:
        session.add(WorkerHeartbeat(id=worker_id, updated_at=utcnow()))
    else:
        row.updated_at = utcnow()
    session.flush()


def last_heartbeat_age_s(
    session: Session, worker_id: str = DEFAULT_WORKER_ID, now: datetime | None = None
) -> float | None:
    """Seconds since the worker's last heartbeat, or None when it never beat."""
    row = session.get(WorkerHeartbeat, worker_id)
    if row is None:
        return None
    last = row.updated_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    now = now or utcnow()
    return max(0.0, (now - last).total_seconds())


def worker_alive(
    session: Session, worker_id: str = DEFAULT_WORKER_ID, now: datetime | None = None
) -> bool:
    age = last_heartbeat_age_s(session, worker_id, now)
    return age is not None and age < get_settings().worker_heartbeat_stale_s
