"""Per-domain daily request budgets. Counters persist in the request_budgets table;
exhausted domains keep their jobs pending until midnight UTC."""

from datetime import datetime

from sqlalchemy.orm import Session

from layoverlab.db.models import RequestBudget, utcnow
from layoverlab.settings import get_settings

CONNECTOR_DOMAINS: dict[str, str] = {
    "ryanair": "services-api.ryanair.com",
    "travelpayouts": "api.travelpayouts.com",
    "google_flights": "www.google.com",
}


def domain_for_connector(connector: str) -> str:
    return CONNECTOR_DOMAINS.get(connector, connector)


def budget_used(session: Session, domain: str, now: datetime | None = None) -> int:
    now = now or utcnow()
    row = session.get(RequestBudget, (domain, now.date()))
    return row.used if row else 0


def budget_remaining(session: Session, domain: str, now: datetime | None = None) -> int:
    return max(0, get_settings().crawl_daily_budget - budget_used(session, domain, now))


def has_budget(session: Session, connector: str, now: datetime | None = None) -> bool:
    return budget_remaining(session, domain_for_connector(connector), now) > 0


def consume_budget(session: Session, connector: str, n: int = 1, now: datetime | None = None) -> None:
    now = now or utcnow()
    domain = domain_for_connector(connector)
    row = session.get(RequestBudget, (domain, now.date()))
    if row is None:
        row = RequestBudget(domain=domain, day=now.date(), used=0)
        session.add(row)
        session.flush()
    row.used += n


def allowed_connectors(session: Session, connectors: list[str], now: datetime | None = None) -> list[str]:
    return [c for c in connectors if has_budget(session, c, now)]
