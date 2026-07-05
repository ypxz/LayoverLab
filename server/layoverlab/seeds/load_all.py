"""Run all seed loaders: python -m layoverlab.seeds.load_all [--force]

Idempotent and fast when already seeded: if every seed table has rows the run is
skipped entirely (no downloads), so it is safe to run on every container start.
Pass --force to re-load anyway.
"""

import argparse
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from layoverlab.db.models import Airport, AirportCluster, Route
from layoverlab.db.session import session_scope
from layoverlab.seeds.loaders import (
    load_airports,
    load_clusters,
    load_ground_links,
    load_routes_auto,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("seeds")

SEED_TABLES = (AirportCluster, Airport, Route)


def is_seeded(session: Session) -> bool:
    """True when every core seed table already has rows (cheap COUNT-limited checks)."""
    for model in SEED_TABLES:
        n = session.execute(select(func.count()).select_from(model)).scalar_one()
        if n == 0:
            return False
    return True


def run(force: bool = False) -> bool:
    """Load all seeds. Returns True when loaders ran, False when skipped (already seeded)."""
    with session_scope() as session:
        if not force and is_seeded(session):
            log.info("seed tables already populated — skipping (use --force to re-load)")
            return False
        n = load_clusters(session)
        log.info("clusters: %d", n)
        n = load_airports(session)
        log.info("airports: %d", n)
        n = load_ground_links(session)
        log.info("ground links (directed): %d", n)
        n = load_routes_auto(session)
        log.info("routes: %d", n)
    log.info("done")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Load all seed data (idempotent).")
    parser.add_argument("--force", action="store_true", help="re-load even when already seeded")
    args = parser.parse_args()
    run(force=args.force)


if __name__ == "__main__":
    main()
