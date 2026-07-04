"""Live verification of top candidates: re-check each flight leg against its source connector."""

import asyncio
import logging
from datetime import datetime, timezone

from layoverlab.connectors.base import all_connectors, load_default_connectors
from layoverlab.engine.models import Itinerary, Leg

log = logging.getLogger(__name__)

PRICE_DRIFT_WARN_PCT = 25


async def _verify_leg(leg: Leg) -> tuple[Leg, bool]:
    """Returns (possibly updated leg, verified?). Graceful: source down -> keep cached, unverified."""
    if leg.mode != "flight":
        return leg, True  # ground legs: static estimates, nothing to verify live
    connectors = all_connectors()
    connector = connectors.get(leg.source)
    if connector is None:
        return leg, False
    try:
        fresh = await connector.verify_day(leg.origin, leg.dest, leg.dep_date)
    except Exception as exc:  # noqa: BLE001 - verification must never break search results
        log.warning("verify %s %s->%s failed: %s", leg.source, leg.origin, leg.dest, exc)
        return leg, False
    if fresh is None:
        return leg, False
    updated = leg.model_copy(
        update={
            "price_cents": fresh["price_cents"],
            "currency": fresh["currency"],
            "deep_link": fresh["deep_link"] or leg.deep_link,
            "fetched_at": datetime.now(timezone.utc),
        }
    )
    return updated, True


async def verify_top(itins: list[Itinerary], n: int = 5) -> list[Itinerary]:
    load_default_connectors()
    result: list[Itinerary] = []
    for itin in itins[:n]:
        pairs = await asyncio.gather(*[_verify_leg(leg) for leg in itin.legs])
        legs = [leg for leg, _ in pairs]
        all_verified = all(ok for _, ok in pairs)
        new_total = sum(leg.price_cents for leg in legs)
        warnings = list(itin.warnings)
        if itin.total_cents > 0:
            drift_pct = abs(new_total - itin.total_cents) * 100 / itin.total_cents
            if drift_pct >= PRICE_DRIFT_WARN_PCT:
                warnings.insert(
                    0, f"Price moved ~{drift_pct:.0f}% vs. cache during live verification."
                )
        result.append(
            itin.model_copy(
                update={
                    "legs": legs,
                    "total_cents": new_total,
                    "verified": all_verified,
                    "warnings": warnings,
                }
            )
        )
    result.extend(itins[n:])
    result.sort(key=lambda i: i.total_cents)
    return result
