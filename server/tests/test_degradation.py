"""Chaos/degradation tests: the API must degrade gracefully, never hang or drop the SSE."""

import asyncio
import json
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import layoverlab.api.routes as routes_module
import layoverlab.engine.verify as verify_module
from layoverlab.api.app import app
from layoverlab.db.session import get_db
from layoverlab.engine.models import Itinerary, Leg, SearchParams
from layoverlab.engine.search import search
from layoverlab.engine.verify import verify_top
from tests.conftest import add_airport, add_fare


class RaisingConnector:
    name = "ryanair"

    async def fetch_month(self, origin, dest, month):
        raise RuntimeError("connector down")

    async def routes_from(self, origin):
        raise RuntimeError("connector down")

    async def verify_day(self, origin, dest, dep_date):
        raise RuntimeError("connector down")


class TimeoutConnector(RaisingConnector):
    async def verify_day(self, origin, dest, dep_date):
        raise asyncio.TimeoutError


def _leg(source: str = "ryanair") -> Leg:
    return Leg(
        origin="BER", dest="ALC", dep_date=date(2027, 3, 10), mode="flight",
        price_cents=2500, currency="EUR", source=source,
        deep_link="https://example.com", fetched_at=datetime.now(timezone.utc),
    )


def _itinerary() -> Itinerary:
    leg = _leg()
    return Itinerary(legs=[leg], total_cents=2500, currency="EUR", stopovers=[], warnings=[])


@pytest.fixture()
def degraded_client(session, monkeypatch):
    """API client over a seeded fare cache where every connector raises."""
    add_airport(session, "BER", "DE")
    add_airport(session, "ALC", "ES")
    add_fare(session, "BER", "ALC", date(2027, 3, 10), 2500)

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(
        routes_module, "_run_search", lambda params: search(params, session)
    )
    monkeypatch.setattr(routes_module, "_pair_cache_fresh", lambda params: True)
    monkeypatch.setattr(verify_module, "load_default_connectors", lambda: None)
    monkeypatch.setattr(
        verify_module, "all_connectors", lambda: {"ryanair": RaisingConnector()}
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def _stream_events(client, payload) -> list[tuple[str, object]]:
    events: list[tuple[str, object]] = []
    name = ""
    with client.stream("POST", "/api/search", json=payload) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                raw = line.split(":", 1)[1].strip()
                events.append((name, json.loads(raw) if raw else None))
    return events


def test_all_connectors_down_still_serves_cached_candidates(degraded_client):
    payload = {"origin": "BER", "dest": "ALC", "date_from": "2027-03-08", "date_to": "2027-03-14"}
    events = _stream_events(degraded_client, payload)
    names = [n for n, _ in events]
    assert names == ["candidates", "verified", "done"]
    candidates = dict(events)["candidates"]
    assert len(candidates) >= 1
    verified = dict(events)["verified"]
    assert all(itin["verified"] is False for itin in verified)
    assert all(itin["total_cents"] > 0 for itin in verified)


def test_db_error_returns_500_envelope_not_hang(session):
    def broken_db():
        raise OperationalError("SELECT 1", {}, Exception("database is locked"))
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = broken_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/airports", params={"q": "ber"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"]


async def test_verify_timeout_keeps_candidates_unverified(monkeypatch):
    monkeypatch.setattr(verify_module, "load_default_connectors", lambda: None)
    monkeypatch.setattr(
        verify_module, "all_connectors", lambda: {"ryanair": TimeoutConnector()}
    )
    itin = _itinerary()
    result = await verify_top([itin], n=5)
    assert len(result) == 1
    assert result[0].verified is False
    assert result[0].total_cents == itin.total_cents


async def test_unknown_source_stays_unverified(monkeypatch):
    monkeypatch.setattr(verify_module, "load_default_connectors", lambda: None)
    monkeypatch.setattr(verify_module, "all_connectors", lambda: {})
    leg = _leg(source="gone-source")
    itin = Itinerary(legs=[leg], total_cents=2500, currency="EUR", stopovers=[], warnings=[])
    result = await verify_top([itin], n=5)
    assert result[0].verified is False


def test_search_engine_unavailable_streams_error_then_done(session, monkeypatch):
    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    def boom(params: SearchParams):
        raise OperationalError("SELECT 1", {}, Exception("database is locked"))

    monkeypatch.setattr(routes_module, "_run_search", boom)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            payload = {
                "origin": "BER", "dest": "ALC",
                "date_from": "2027-03-08", "date_to": "2027-03-14",
            }
            events = _stream_events(client, payload)
    finally:
        app.dependency_overrides.clear()
    names = [n for n, _ in events]
    assert names == ["error", "done"]
