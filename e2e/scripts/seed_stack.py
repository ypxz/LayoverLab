"""Seed the E2E fixture stack: fixture fares for two months plus a stale 'cold route' pair.

The stale pair (MUC->ALC, source 'stale-seed') exercises the SSE `update` flow: its
fetched_at is older than FARE_TTL_HOURS/2, so /api/search enters the update loop and picks
up cheaper fares injected mid-stream by inject_fares.py.
"""

import calendar
import os
import sys
from datetime import date, datetime, timedelta, timezone

from layoverlab.connectors.fixture import seed_fixture_stack
from layoverlab.db.models import Fare
from layoverlab.db.session import session_scope

STALE_PAIR = ("MUC", "ALC")
STALE_PRICE_CENTS = 20000
STALE_AGE_H = 30


def e2e_month() -> date:
    raw = os.environ.get("E2E_MONTH")
    if raw:
        return date.fromisoformat(f"{raw}-01")
    today = date.today()
    return (today.replace(day=1) + timedelta(days=62)).replace(day=1)


def main() -> int:
    month = e2e_month()
    months = [month, (month + timedelta(days=32)).replace(day=1)]
    stale_at = datetime.now(timezone.utc) - timedelta(hours=STALE_AGE_H)
    with session_scope() as session:
        n = seed_fixture_stack(session, months)
        origin, dest = STALE_PAIR
        days = calendar.monthrange(month.year, month.month)[1]
        for offset in range(days):
            session.add(
                Fare(
                    origin=origin, dest=dest, dep_date=month + timedelta(days=offset),
                    source="stale-seed", min_price_cents=STALE_PRICE_CENTS, currency="EUR",
                    deep_link=None, fetched_at=stale_at, expires_at=stale_at + timedelta(hours=48),
                )
            )
    print(f"seeded {n} fixture fares + stale {origin}->{dest} for {month.isoformat()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
