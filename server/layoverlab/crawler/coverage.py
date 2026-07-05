"""Per-(origin, dest, month, source) coverage tracking: fare freshness + demand scores."""

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from layoverlab.db.models import RouteCoverage, utcnow

DEMAND_DECAY_PER_DAY = 0.95


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _get_or_create(session: Session, origin: str, dest: str, month: date, source: str) -> RouteCoverage:
    row = session.get(RouteCoverage, (origin, dest, month, source))
    if row is None:
        row = RouteCoverage(
            origin=origin, dest=dest, month=month, source=source,
            fail_count=0, demand_score=0.0, demand_updated_at=utcnow(),
        )
        session.add(row)
        session.flush()
    return row


def effective_demand(row: RouteCoverage, now: datetime | None = None) -> float:
    """Demand score with lazy exponential decay (0.95/day since last update)."""
    now = now or utcnow()
    days = max(0.0, (_aware(now) - _aware(row.demand_updated_at)).total_seconds() / 86400)
    return row.demand_score * (DEMAND_DECAY_PER_DAY**days)


def bump_demand(
    session: Session, origin: str, dest: str, month: date, source: str, now: datetime | None = None
) -> None:
    now = now or utcnow()
    row = _get_or_create(session, origin, dest, month, source)
    row.demand_score = effective_demand(row, now) + 1.0
    row.demand_updated_at = now


def record_success(
    session: Session, origin: str, dest: str, month: date, source: str, now: datetime | None = None
) -> None:
    row = _get_or_create(session, origin, dest, month, source)
    row.last_success_at = now or utcnow()
    row.fail_count = 0


def record_failure(session: Session, origin: str, dest: str, month: date, source: str) -> None:
    row = _get_or_create(session, origin, dest, month, source)
    row.fail_count += 1
