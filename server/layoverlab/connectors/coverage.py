"""Source coverage instrumentation.

- enabled_sources(): which registered connectors can run right now (and why not, if not) —
  used by worker startup logging and crawler stats.
- sources_for_route(): which enabled sources claim support for an (origin, dest) pair, from
  routes-table carriers + per-connector capability flags — lets the prioritizer skip sources
  that cannot serve a pair.
"""

import logging
from typing import TypedDict

from sqlalchemy.orm import Session

from layoverlab.connectors.base import all_connectors, load_default_connectors
from layoverlab.db.models import Route
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

# Marketplace/GDS sources aggregate all airlines: they can claim any pair.
UNIVERSAL_SOURCES = {"travelpayouts", "kiwi_tequila", "amadeus"}


class SourceStatus(TypedDict):
    enabled: bool
    reason: str | None  # why disabled, None when enabled
    bulk: bool  # safe to bulk-crawl month fan-outs


def _disabled_reason(name: str) -> str | None:
    settings = get_settings()
    if name == "travelpayouts" and not settings.travelpayouts_token:
        return "TRAVELPAYOUTS_TOKEN not set"
    if name == "kiwi_tequila" and not settings.tequila_api_key:
        return "TEQUILA_API_KEY not set"
    if name == "amadeus" and not (settings.amadeus_client_id and settings.amadeus_client_secret):
        return "AMADEUS_CLIENT_ID/AMADEUS_CLIENT_SECRET not set"
    if name == "wizzair" and not settings.wizz_enabled:
        return "WIZZ_ENABLED=false"
    if name == "easyjet" and not settings.easyjet_enabled:
        return "EASYJET_ENABLED=false"
    if name == "google_flights" and not settings.gf_enabled:
        return "GF_ENABLED=false"
    return None


def enabled_sources() -> dict[str, SourceStatus]:
    load_default_connectors()
    statuses: dict[str, SourceStatus] = {}
    for name, connector in sorted(all_connectors().items()):
        reason = _disabled_reason(name)
        statuses[name] = SourceStatus(
            enabled=reason is None,
            reason=reason,
            bulk=bool(getattr(connector, "bulk", False)),
        )
    return statuses


def bulk_sources() -> list[str]:
    return [name for name, s in enabled_sources().items() if s["enabled"] and s["bulk"]]


def sources_for_route(session: Session, origin: str, dest: str) -> list[str]:
    """Enabled sources that claim (origin, dest). Airline sources claim a pair when the routes
    table lists them as a carrier, or when no connector has explored the pair yet (route row
    missing, or its carriers only contain airline codes from seed data)."""
    statuses = enabled_sources()
    route = session.get(Route, (origin, dest))
    carriers = set(route.carriers or []) if route else set()
    crawled_by = carriers & statuses.keys()
    claimed: list[str] = []
    for name, status in statuses.items():
        if not status["enabled"]:
            continue
        if name in UNIVERSAL_SOURCES or not crawled_by or name in crawled_by:
            claimed.append(name)
    return claimed


def log_disabled_sources() -> None:
    disabled = {n: s["reason"] for n, s in enabled_sources().items() if not s["enabled"]}
    if not disabled:
        log.info("all fare sources enabled")
        return
    lines = "\n".join(f"  - {name}: {reason}" for name, reason in disabled.items())
    log.warning(
        "==========================================================\n"
        "FARE SOURCES DISABLED — fare coverage is reduced!\n%s\n"
        "See .env.example for how to obtain the missing tokens (all free tiers).\n"
        "==========================================================",
        lines,
    )
