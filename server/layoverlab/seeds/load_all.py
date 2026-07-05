"""Run all seed loaders: python -m layoverlab.seeds.load_all"""

import logging

from layoverlab.db.session import session_scope
from layoverlab.seeds.loaders import (
    load_airports,
    load_clusters,
    load_ground_links,
    load_routes_auto,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("seeds")


def main() -> None:
    with session_scope() as session:
        n = load_clusters(session)
        log.info("clusters: %d", n)
        n = load_airports(session)
        log.info("airports: %d", n)
        n = load_ground_links(session)
        log.info("ground links (directed): %d", n)
        n = load_routes_auto(session)
        log.info("routes: %d", n)
    log.info("done")


if __name__ == "__main__":
    main()
