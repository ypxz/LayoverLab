import json
import logging
import time
from datetime import date, datetime, timedelta, timezone

import anyio
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from layoverlab.api import metrics
from layoverlab.crawler.heartbeat import last_heartbeat_age_s, worker_alive
from layoverlab.crawler.prioritizer import enqueue_for_search
from layoverlab.db.models import Airport, CrawlJob, Fare, ItinerarySnapshot
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
def health(db: Session = Depends(get_db)) -> dict:
    worker: dict = {"alive": None, "last_heartbeat_age_s": None}
    try:
        age = last_heartbeat_age_s(db)
        worker = {
            "alive": worker_alive(db),
            "last_heartbeat_age_s": round(age, 1) if age is not None else None,
        }
    except Exception:  # noqa: BLE001 - health must not 500 on a half-migrated DB
        log.exception("worker heartbeat check failed")
    return {"status": "ok", "worker": worker}


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
        if params.round_trip:
            inbound_to = params.date_to + timedelta(days=params.trip_max_days or 30)
            enqueue_for_search(session, params.dest, params.origin, params.date_from, inbound_to)
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


def _fares_fresh(session: Session, origin: str, dest: str, date_from: date, date_to: date) -> bool:
    latest = session.execute(
        select(func.max(Fare.fetched_at)).where(
            Fare.origin == origin,
            Fare.dest == dest,
            Fare.dep_date >= date_from,
            Fare.dep_date <= date_to,
        )
    ).scalar_one_or_none()
    if latest is None:
        return False
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    ttl = timedelta(hours=get_settings().fare_ttl_hours / 2)
    return datetime.now(timezone.utc) - latest < ttl


def _pair_cache_fresh_inner(params: SearchParams) -> bool:
    with session_scope() as session:
        if not _fares_fresh(session, params.origin, params.dest, params.date_from, params.date_to):
            return False
        if not params.round_trip:
            return True
        inbound_to = params.date_to + timedelta(days=params.trip_max_days or 30)
        return _fares_fresh(session, params.dest, params.origin, params.date_from, inbound_to)


async def _wait_for_fares(origin: str, dest: str, month: date, timeout_s: float) -> None:
    """Wait for the crawler to signal the pair's jobs are terminal (agent D's notify)."""
    from layoverlab.crawler.notify import wait_for_pair
    from layoverlab.db.session import get_sessionmaker

    await wait_for_pair(get_sessionmaker(), origin, dest, month, timeout_s=timeout_s)


def _worker_alive() -> bool | None:
    """None means unknown (heartbeat table missing / DB error) — never fails the stream."""
    try:
        with session_scope() as session:
            return worker_alive(session)
    except Exception:  # noqa: BLE001
        log.exception("worker heartbeat check failed")
        return None


def _pair_sources_erroring(params: SearchParams) -> bool:
    """True when the direct pair's crawl jobs all ended in error/dead (no successes)."""
    try:
        with session_scope() as session:
            month = params.date_from.replace(day=1)
            statuses = set(
                session.execute(
                    select(CrawlJob.status).where(
                        CrawlJob.origin == params.origin,
                        CrawlJob.dest == params.dest,
                        CrawlJob.month == month,
                    )
                ).scalars()
            )
        return bool(statuses) and statuses <= {"error", "dead"}
    except Exception:  # noqa: BLE001
        log.exception("crawl job status check failed")
        return False


def _zero_results_reason(
    params: SearchParams, crawl_pending: bool, alive: bool | None
) -> str:
    """Why a finished stream has zero results: crawl_disabled | worker_down |
    sources_erroring | crawl_pending | no_coverage."""
    if not get_settings().crawl_enabled:
        return "crawl_disabled"
    if alive is False:
        return "worker_down"
    if _pair_sources_erroring(params):
        return "sources_erroring"
    if crawl_pending:
        return "crawl_pending"
    return "no_coverage"


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
        have_results = False
        try:
            candidates = await anyio.to_thread.run_sync(_run_search, params)
            have_results = len(candidates) > 0
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
                        params.origin,
                        params.dest,
                        params.date_from.replace(day=1),
                        min(settings.search_stream_poll_s, remaining),
                    )
                    if time.perf_counter() >= deadline:
                        break
                    fresh = await anyio.to_thread.run_sync(_rerun_search, params)
                    improved = _improved(fresh, best_total, best_count)
                    have_results = have_results or len(fresh) > 0
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
        alive = await anyio.to_thread.run_sync(_worker_alive)
        reason = None
        if not have_results:
            reason = await anyio.to_thread.run_sync(_zero_results_reason, params, crawl_pending, alive)
        meta = {
            "crawl_pending": crawl_pending,
            "searched_pairs_covered": covered,
            "worker_alive": alive,
            "zero_results_reason": reason,
        }
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
