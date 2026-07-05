"""Live verification of top candidates: re-check each flight leg against its source connector,
attach real departure/arrival times (Google Flights, when enabled), enforce self-transfer
buffers with known times, and re-rank on price drift."""

import asyncio
import itertools
import logging
from datetime import datetime, timezone

from layoverlab.connectors.base import all_connectors, load_default_connectors
from layoverlab.engine.models import Itinerary, Leg
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

PRICE_DRIFT_NOTE_PCT = 15
STRONG_BUFFER_H = 6.0
OVERNIGHT_H = 24.0


async def _fetch_times(leg: Leg) -> tuple[datetime, datetime] | None:
    """Departure/arrival times for a flight leg via Google Flights (None when disabled/down)."""
    if not get_settings().gf_enabled:
        return None
    gf = all_connectors().get("google_flights")
    if gf is None or not hasattr(gf, "fetch_day_options"):
        return None
    try:
        options = await gf.fetch_day_options(leg.origin, leg.dest, leg.dep_date)
    except Exception as exc:  # noqa: BLE001 - verification must never break search results
        log.warning("GF times %s->%s %s failed: %s", leg.origin, leg.dest, leg.dep_date, exc)
        return None
    if not options:
        return None
    best = options[0]  # cheapest option for the day
    return best["dep_time"], best["arr_time"]


async def _verify_leg(leg: Leg) -> tuple[Leg, bool]:
    """Returns (possibly updated leg, verified?). Graceful: source down -> keep cached, unverified."""
    if leg.mode != "flight":
        return leg, True  # ground legs: static estimates, nothing to verify live
    connectors = all_connectors()
    connector = connectors.get(leg.source)
    if connector is None:
        return leg, False

    async def _fresh():
        try:
            return await connector.verify_day(leg.origin, leg.dest, leg.dep_date)
        except Exception as exc:  # noqa: BLE001 - verification must never break search results
            log.warning("verify %s %s->%s failed: %s", leg.source, leg.origin, leg.dest, exc)
            return None

    fresh, times = await asyncio.gather(_fresh(), _fetch_times(leg))
    update: dict = {}
    if times is not None:
        update["dep_time"], update["arr_time"] = times
    if fresh is None:
        return (leg.model_copy(update=update) if update else leg), False
    update.update(
        price_cents=fresh["price_cents"],
        currency=fresh["currency"],
        deep_link=fresh["deep_link"] or leg.deep_link,
        fetched_at=datetime.now(timezone.utc),
    )
    return leg.model_copy(update=update), True


def _buffer_warnings(legs: list[Leg]) -> tuple[list[str], bool]:
    """Connection-gap warnings from real times. Returns (warnings, drop_from_verified)."""
    min_h = get_settings().self_transfer_min_h
    warnings: list[str] = []
    drop = False
    for prev, nxt in itertools.pairwise(legs):
        if prev.arr_time is None or nxt.dep_time is None:
            continue  # times unknown: keep existing heuristic warnings untouched
        gap_h = (nxt.dep_time - prev.arr_time).total_seconds() / 3600
        if gap_h >= OVERNIGHT_H:
            continue  # overnight stopover, buffers do not apply
        if gap_h < min_h:
            drop = True
            warnings.append(
                f"Connection in {prev.dest}: only {gap_h:.1f}h between flights — below the "
                f"{min_h:.0f}h self-transfer minimum. Do not book as shown."
            )
        elif gap_h < STRONG_BUFFER_H:
            warnings.append(
                f"Connection in {prev.dest}: {gap_h:.1f}h between flights — tight for a "
                f"self-transfer (recommended: {STRONG_BUFFER_H:.0f}h+)."
            )
    return warnings, drop


async def _verify_itin(itin: Itinerary) -> Itinerary:
    pairs = await asyncio.gather(*[_verify_leg(leg) for leg in itin.legs])
    legs = [leg for leg, _ in pairs]
    all_verified = all(ok for _, ok in pairs)
    new_total = sum(leg.price_cents for leg in legs)
    warnings = list(itin.warnings)
    if itin.total_cents > 0:
        drift_pct = abs(new_total - itin.total_cents) * 100 / itin.total_cents
        if drift_pct > PRICE_DRIFT_NOTE_PCT:
            warnings.insert(
                0,
                f"Price changed since cached: {itin.total_cents / 100:.2f} -> "
                f"{new_total / 100:.2f} {itin.currency}",
            )
    buffer_warnings, drop = _buffer_warnings(legs)
    warnings.extend(buffer_warnings)
    return itin.model_copy(
        update={
            "legs": legs,
            "total_cents": new_total,
            "verified": all_verified and not drop,
            "warnings": warnings,
        }
    )


async def verify_top(itins: list[Itinerary], n: int = 5) -> list[Itinerary]:
    load_default_connectors()
    k = min(n, get_settings().verify_top_k)
    result = list(await asyncio.gather(*[_verify_itin(itin) for itin in itins[:k]]))
    result.extend(itins[k:])
    result.sort(key=lambda i: i.total_cents)
    return result
