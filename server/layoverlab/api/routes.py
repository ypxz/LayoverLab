import json
import logging

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from layoverlab.crawler.prioritizer import enqueue_for_search
from layoverlab.db.models import Airport, ItinerarySnapshot
from layoverlab.db.session import get_db, session_scope
from layoverlab.engine.models import Itinerary, SearchParams
from layoverlab.engine.search import search
from layoverlab.engine.verify import verify_top

log = logging.getLogger(__name__)
router = APIRouter()


class AirportOut(BaseModel):
    iata: str
    name: str
    city: str
    country_code: str


class ItineraryId(BaseModel):
    id: str


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/airports", response_model=list[AirportOut])
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


@router.post("/search")
async def search_endpoint(params: SearchParams):
    async def event_stream():
        try:
            candidates = await anyio.to_thread.run_sync(_run_search, params)
            yield {
                "event": "candidates",
                "data": json.dumps([i.model_dump(mode="json") for i in candidates]),
            }
            verified = await verify_top(candidates, n=5)
            yield {
                "event": "verified",
                "data": json.dumps([i.model_dump(mode="json") for i in verified]),
            }
        except Exception:  # noqa: BLE001 - stream errors to the client instead of dropping the SSE
            log.exception("search failed")
            yield {"event": "error", "data": json.dumps({"message": "search failed"})}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())


@router.post("/itineraries", response_model=ItineraryId)
def save_itinerary(itin: Itinerary, db: Session = Depends(get_db)):
    snapshot = ItinerarySnapshot(payload=itin.model_dump(mode="json"))
    db.add(snapshot)
    db.flush()
    return ItineraryId(id=snapshot.id)


@router.get("/r/{itinerary_id}", response_model=Itinerary)
async def get_itinerary(itinerary_id: str, db: Session = Depends(get_db)):
    snapshot = db.get(ItinerarySnapshot, itinerary_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="itinerary not found")
    itin = Itinerary.model_validate(snapshot.payload)
    verified = await verify_top([itin], n=1)
    result = verified[0]
    result.id = snapshot.id
    return result
