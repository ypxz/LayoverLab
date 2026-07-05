"""Inject fresh fares into the running E2E stack DB (simulates crawled results landing).

Usage: inject_fares.py ORIGIN DEST YYYY-MM PRICE_CENTS
Requires DATABASE_URL pointing at the stack's SQLite file.
"""

import calendar
import sys
from datetime import date, timedelta

from layoverlab.connectors.base import DayFare
from layoverlab.crawler.service import upsert_fares
from layoverlab.db.session import session_scope


def main() -> int:
    origin, dest, month_raw, price_raw = sys.argv[1:5]
    month = date.fromisoformat(f"{month_raw}-01")
    price_cents = int(price_raw)
    days = calendar.monthrange(month.year, month.month)[1]
    fares = [
        DayFare(
            origin=origin, dest=dest, dep_date=month + timedelta(days=offset),
            price_cents=price_cents, currency="EUR",
            deep_link=f"https://fixture.invalid/injected/{origin}/{dest}",
        )
        for offset in range(days)
    ]
    with session_scope() as session:
        n = upsert_fares(session, fares, source="fixture")
    print(f"injected {n} fares {origin}->{dest} @ {price_cents}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
