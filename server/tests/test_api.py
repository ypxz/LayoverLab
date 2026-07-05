import json
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

import layoverlab.api.routes as routes_module
from layoverlab.api.app import app
from layoverlab.db.session import get_db
from layoverlab.engine.models import Itinerary, Leg
from tests.conftest import add_airport


def _itinerary() -> Itinerary:
    leg = Leg(
        origin="BER", dest="ALC", dep_date=date(2026, 8, 19), mode="flight",
        price_cents=1500, currency="EUR", source="ryanair",
        deep_link="https://example.com", fetched_at=datetime.now(timezone.utc),
    )
    return Itinerary(legs=[leg], total_cents=1500, currency="EUR", stopovers=[], warnings=[])


@pytest.fixture()
def client(session, monkeypatch):
    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    async def fake_verify(itins, n=5):
        return [i.model_copy(update={"verified": True}) for i in itins]

    def fake_run_search(params):
        return [_itinerary()]

    monkeypatch.setattr(routes_module, "verify_top", fake_verify)
    monkeypatch.setattr(routes_module, "_run_search", fake_run_search)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["worker"] == {"alive": False, "last_heartbeat_age_s": None}


def test_health_reports_worker_heartbeat(client, session):
    from layoverlab.crawler.heartbeat import beat

    beat(session)
    body = client.get("/api/health").json()
    assert body["worker"]["alive"] is True
    assert body["worker"]["last_heartbeat_age_s"] is not None


def test_airports_autocomplete_prefers_exact_iata(client, session):
    add_airport(session, "BER", "DE")
    add_airport(session, "ALC", "ES")
    body = client.get("/api/airports", params={"q": "ber"}).json()
    assert body[0]["iata"] == "BER"


def _stream_events(client, payload=None):
    payload = payload or {
        "origin": "BER", "dest": "ALC", "date_from": "2026-08-01", "date_to": "2026-08-31",
    }
    events: list[tuple[str, str]] = []
    with client.stream("POST", "/api/search", json=payload) as resp:
        assert resp.status_code == 200
        event = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event is not None:
                events.append((event, line.split(":", 1)[1].strip()))
    return events


def _done_meta(events) -> dict:
    return json.loads(dict(events)["done"])["meta"]


def test_search_sse_event_order(client):
    events = [e for e, _ in _stream_events(client)]
    assert events == ["candidates", "verified", "done"]


def test_done_meta_with_results_has_no_zero_reason(client, monkeypatch):
    monkeypatch.setattr(routes_module, "_worker_alive", lambda: True)
    meta = _done_meta(_stream_events(client))
    assert meta["zero_results_reason"] is None
    assert meta["worker_alive"] is True
    assert meta["crawl_pending"] is False


def test_done_meta_zero_results_no_coverage(client, monkeypatch):
    monkeypatch.setattr(routes_module, "_run_search", lambda params: [])
    monkeypatch.setattr(routes_module, "_pair_cache_fresh", lambda params: True)
    monkeypatch.setattr(routes_module, "_pair_sources_erroring", lambda params: False)
    monkeypatch.setattr(routes_module, "_worker_alive", lambda: True)
    meta = _done_meta(_stream_events(client))
    assert meta["zero_results_reason"] == "no_coverage"


def test_done_meta_zero_results_worker_down(client, monkeypatch):
    monkeypatch.setattr(routes_module, "_run_search", lambda params: [])
    monkeypatch.setattr(routes_module, "_pair_cache_fresh", lambda params: True)
    monkeypatch.setattr(routes_module, "_worker_alive", lambda: False)
    meta = _done_meta(_stream_events(client))
    assert meta["zero_results_reason"] == "worker_down"
    assert meta["worker_alive"] is False


def test_done_meta_zero_results_sources_erroring(client, monkeypatch):
    monkeypatch.setattr(routes_module, "_run_search", lambda params: [])
    monkeypatch.setattr(routes_module, "_pair_cache_fresh", lambda params: True)
    monkeypatch.setattr(routes_module, "_pair_sources_erroring", lambda params: True)
    monkeypatch.setattr(routes_module, "_worker_alive", lambda: True)
    meta = _done_meta(_stream_events(client))
    assert meta["zero_results_reason"] == "sources_erroring"


def test_done_meta_zero_results_crawl_disabled(client, monkeypatch):
    from layoverlab.settings import get_settings

    monkeypatch.setenv("CRAWL_ENABLED", "false")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(routes_module, "_run_search", lambda params: [])
        monkeypatch.setattr(routes_module, "_pair_cache_fresh", lambda params: True)
        monkeypatch.setattr(routes_module, "_worker_alive", lambda: True)
        meta = _done_meta(_stream_events(client))
        assert meta["zero_results_reason"] == "crawl_disabled"
    finally:
        get_settings.cache_clear()


def test_itinerary_permalink_roundtrip(client):
    itin = _itinerary()
    created = client.post("/api/itineraries", json=json.loads(itin.model_dump_json()))
    assert created.status_code == 200
    itin_id = created.json()["id"]

    fetched = client.get(f"/api/r/{itin_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["id"] == itin_id
    assert body["verified"] is True
    assert body["legs"][0]["origin"] == "BER"

    assert client.get("/api/r/does-not-exist").status_code == 404
