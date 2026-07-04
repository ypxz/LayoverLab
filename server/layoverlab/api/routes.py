import json
import logging
import time
from datetime import datetime, timedelta, timezone

import anyio
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from layoverlab.api import metrics
from layoverlab.crawler.prioritizer import enqueue_for_search
from layoverlab.db.models import Airport, Fare, ItinerarySnapshot
from layoverlab.db.session import get_db, session_scope
from layoverlab.engine.models import Itinerary, SearchParams
from layoverlab.engine.search import search
from layoverlab.engine.verify import verify_top
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


class AirportOut(BaseModel):
    iata: str
    name: str
    city: str
    country_code: str


class ItineraryId(BaseModel):
    id: str


@router.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok"}


@router.get("/airports", response_model=list[AirportOut], tags=["airports"])
def airports(q: str = Query(min_length=2, max_length=64), db: Session = Depends(get_db)):
    pattern = f"%{q}%"
    exact = q.strip().upper()
    rows = (
        db.execute(
            select(Airport)
            .where(
                or_(
                    Airport.iata == exact,
                    Airport.name.ilike(pattern),
                    Airport.city.ilike(pattern),
                )
            )
            .order_by(case((Airport.iata == exact, 0), else_=1), Airport.name)
            .limit(10)
        )
        .scalars()
        .all()
    )
    return [
        AirportOut(iata=a.iata, name=a.name, city=a.city, country_code=a.country_code) for a in rows
    ]


def _run_search(params: SearchParams) -> list[Itinerary]:
    with session_scope() as session:
        enqueue_for_search(session, params.origin, params.dest, params.date_from, params.date_to)
        return search(params, session)


def _rerun_search(params: SearchParams) -> list[Itinerary]:
    with session_scope() as session:
        return search(params, session)


def _pair_cache_fresh(params: SearchParams) -> bool:
    """True when the direct pair has fares fetched within FARE_TTL_HOURS/2.

    Fails open (True) so a cache-check error never holds the stream open.
    """
    try:
        return _pair_cache_fresh_inner(params)
    except Exception:  # noqa: BLE001
        log.exception("fare cache freshness check failed")
        return True


def _pair_cache_fresh_inner(params: SearchParams) -> bool:
    with session_scope() as session:
        latest = session.execute(
            select(func.max(Fare.fetched_at)).where(
                Fare.origin == params.origin,
                Fare.dest == params.dest,
                Fare.dep_date >= params.date_from,
                Fare.dep_date <= params.date_to,
            )
        ).scalar_one_or_none()
    if latest is None:
        return False
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    ttl = timedelta(hours=get_settings().fare_ttl_hours / 2)
    return datetime.now(timezone.utc) - latest < ttl


async def _wait_for_fares(origin: str, dest: str, timeout_s: float) -> None:
    """Wait for the crawler to signal fresh fares for the pair; poll-based fallback."""
    try:
        from layoverlab.crawler.notify import wait_for_pair  # provided by agent D
    except ImportError:
        await anyio.sleep(timeout_s)
        return
    try:
        with anyio.fail_after(timeout_s):
            await wait_for_pair(origin, dest)
    except TimeoutError:
        pass


def _improved(new: list[Itinerary], best_total: int | None, best_count: int) -> bool:
    if not new:
        return False
    new_total = min(i.total_cents for i in new)
    if best_total is None:
        return True
    return new_total < best_total or len(new) > best_count


@router.post(
    "/search",
    tags=["search"],
    summary="Streaming cheapest-route search",
    description="SSE stream: `candidates` -> `verified` -> zero or more `update` -> `done`.",
)
async def search_endpoint(
    params: SearchParams = Body(
        examples=[
            {
                "origin": "BER",
                "dest": "ALC",
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
                "round_trip": False,
                "max_stops": 3,
                "top_k": 10,
            }
        ]
    ),
):
    async def event_stream():
        settings = get_settings()
        started = time.perf_counter()
        event_counts: dict[str, int] = {}
        metrics.sse_searches_started_total.inc()

        def emit(event: str, data: str) -> dict:
            event_counts[event] = event_counts.get(event, 0) + 1
            return {"event": event, "data": data}

        crawl_pending = False
        covered = True
        try:
            candidates = await anyio.to_thread.run_sync(_run_search, params)
            yield emit("candidates", json.dumps([i.model_dump(mode="json") for i in candidates]))
            verified = await verify_top(candidates, n=5)
            yield emit("verified", json.dumps([i.model_dump(mode="json") for i in verified]))

            covered = await anyio.to_thread.run_sync(_pair_cache_fresh, params)
            if not covered:
                crawl_pending = True
                best_total = min((i.total_cents for i in candidates), default=None)
                best_count = len(candidates)
                deadline = started + settings.search_stream_max_s
                while time.perf_counter() < deadline:
                    remaining = deadline - time.perf_counter()
                    await _wait_for_fares(
                        params.origin, params.dest, min(settings.search_stream_poll_s, remaining)
                    )
                    if time.perf_counter() >= deadline:
                        break
                    fresh = await anyio.to_thread.run_sync(_rerun_search, params)
                    improved = _improved(fresh, best_total, best_count)
                    if improved:
                        best_total = min(i.total_cents for i in fresh)
                        best_count = len(fresh)
                        yield emit(
                            "update", json.dumps([i.model_dump(mode="json") for i in fresh])
                        )
                    covered = await anyio.to_thread.run_sync(_pair_cache_fresh, params)
                    if covered and not improved:
                        crawl_pending = False
                        break
        except Exception:  # noqa: BLE001 - stream errors to the client instead of dropping the SSE
            log.exception("search failed")
            yield emit("error", json.dumps({"message": "search failed"}))
        meta = {"crawl_pending": crawl_pending, "searched_pairs_covered": covered}
        yield emit("done", json.dumps({"meta": meta}))
        metrics.sse_searches_completed_total.inc()
        log.info(
            "search stream closed",
            extra={
                "duration_s": round(time.perf_counter() - started, 3),
                "events": event_counts,
            },
        )

    return EventSourceResponse(event_stream())


@router.post("/itineraries", response_model=ItineraryId, tags=["itineraries"])
def save_itinerary(itin: Itinerary, db: Session = Depends(get_db)):
    snapshot = ItinerarySnapshot(payload=itin.model_dump(mode="json"))
    db.add(snapshot)
    db.flush()
    return ItineraryId(id=snapshot.id)


@router.get("/r/{itinerary_id}", response_model=Itinerary, tags=["itineraries"])
async def get_itinerary(itinerary_id: str, db: Session = Depends(get_db)):
    snapshot = db.get(ItinerarySnapshot, itinerary_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="itinerary not found")
    itin = Itinerary.model_validate(snapshot.payload)
    verified = await verify_top([itin], n=1)
    result = verified[0]
    result.id = snapshot.id
    return result
