"""One-off crawl for a route+month: python scripts/crawl_once.py BER ALC 2026-08"""

import asyncio
import logging
import sys
from datetime import date

from layoverlab.connectors.base import ConnectorDisabled, all_connectors, load_default_connectors
from layoverlab.crawler.service import upsert_fares
from layoverlab.db.session import session_scope

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("crawl_once")


async def main() -> None:
    if len(sys.argv) != 4:
        print("usage: python scripts/crawl_once.py ORIGIN DEST YYYY-MM")
        sys.exit(1)
    origin, dest = sys.argv[1].upper(), sys.argv[2].upper()
    month = date.fromisoformat(sys.argv[3] + "-01")

    load_default_connectors()
    for name, connector in all_connectors().items():
        try:
            fares = await connector.fetch_month(origin, dest, month)
        except ConnectorDisabled as exc:
            log.info("%s: disabled (%s)", name, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: failed (%s)", name, exc)
            continue
        with session_scope() as session:
            n = upsert_fares(session, fares, source=name)
        log.info("%s: %d fares stored", name, n)
        if fares:
            cheapest = min(fares, key=lambda f: f["price_cents"])
            log.info(
                "%s cheapest: %s %.2f %s", name, cheapest["dep_date"],
                cheapest["price_cents"] / 100, cheapest["currency"],
            )


if __name__ == "__main__":
    asyncio.run(main())
