"""Platform hardening tests: request-id, error envelope, rate limits, admin, metrics, SSE updates."""

import json
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

import layoverlab.api.routes as routes_module
from layoverlab.api.app import app
from layoverlab.api.ratelimit import RateLimiter, limiter
from layoverlab.db.session import get_db
from layoverlab.engine.models import Itinerary, Leg
from layoverlab.settings import get_settings


def _itinerary(cents: int = 1500) -> Itinerary:
    leg = Leg(
        origin="BER", dest="ALC", dep_date=date(2026, 8, 19), mode="flight",
        price_cents=cents, currency="EUR", source="ryanair",
        deep_link="https://example.com", fetched_at=datetime.now(timezone.utc),
    )
    return Itinerary(legs=[leg], total_cents=cents, currency="EUR", stopovers=[], warnings=[])


SEARCH_BODY = {"origin": "BER", "dest": "ALC", "date_from": "2026-08-01", "date_to": "2026-08-31"}


def _sse_events(resp) -> list[tuple[str, str]]:
    events, current = [], None
    for line in resp.iter_lines():
        if line.startswith("event:"):
            current = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and current is not None:
            events.append((current, line.split(":", 1)[1].strip()))
            current = None
    return events


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
    monkeypatch.setattr(routes_module, "_pair_cache_fresh", lambda params: True)
    limiter.reset()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    limiter.reset()


def test_request_id_echoed(client):
    resp = client.get("/api/health")
    rid = resp.headers["x-request-id"]
    assert uuid.UUID(rid)


def test_error_envelope_shape(session, monkeypatch):
    @app.get("/api/_boom", include_in_schema=False)
    def boom():
        raise RuntimeError("secret internal detail")

    try:
        limiter.reset()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/_boom")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "internal_error"
        assert body["error"]["message"] == "Internal server error"
        assert body["error"]["request_id"] == resp.headers["x-request-id"]
        assert "secret internal detail" not in resp.text
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", None) != "/api/_boom"
        ]


def test_rate_limit_429_and_recovery(client, monkeypatch):
    clock = {"now": 0.0}
    fake = RateLimiter(clock=lambda: clock["now"])
    monkeypatch.setattr("layoverlab.api.middleware.limiter", fake)
    monkeypatch.setattr(get_settings(), "rate_default_per_min", 3)

    for _ in range(3):
        assert client.get("/api/health").status_code == 200
    resp = client.get("/api/health")
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert resp.json()["error"]["code"] == "rate_limited"

    clock["now"] += 61.0
    assert client.get("/api/health").status_code == 200


def test_rate_limit_disabled(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", False)
    monkeypatch.setattr(get_settings(), "rate_default_per_min", 1)
    for _ in range(5):
        assert client.get("/api/health").status_code == 200


def test_admin_404_when_env_unset(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "")
    assert client.get("/api/admin/config").status_code == 404
    assert client.get("/api/admin/crawler").status_code == 404


def test_admin_403_wrong_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "correct-token")
    assert client.get("/api/admin/config").status_code == 403
    resp = client.get("/api/admin/config", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


def test_admin_config_redacts_secrets(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "correct-token")
    monkeypatch.setattr(get_settings(), "travelpayouts_token", "tp-super-secret")
    resp = client.get("/api/admin/config", headers={"X-Admin-Token": "correct-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["admin_token"] == "***redacted***"
    assert body["travelpayouts_token"] == "***redacted***"
    assert "correct-token" not in resp.text
    assert "tp-super-secret" not in resp.text


def test_admin_crawler_pending_until_agent_d(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "correct-token")
    resp = client.get("/api/admin/crawler", headers={"X-Admin-Token": "correct-token"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "pending-agent-d"}


def test_metrics_exposes_counters(client):
    client.get("/api/health")
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert "layoverlab_http_requests_total" in resp.text
    assert "layoverlab_http_request_duration_seconds" in resp.text
    assert "layoverlab_sse_searches_started_total" in resp.text


def test_metrics_disabled(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "metrics_enabled", False)
    assert client.get("/api/metrics").status_code == 404


def test_sse_warm_cache_no_update(client):
    with client.stream("POST", "/api/search", json=SEARCH_BODY) as resp:
        events = _sse_events(resp)
    names = [e for e, _ in events]
    assert names == ["candidates", "verified", "done"]
    meta = json.loads(events[-1][1])["meta"]
    assert meta == {"crawl_pending": False, "searched_pairs_covered": True}


def test_sse_update_emitted_on_improvement(client, monkeypatch):
    fresh_states = iter([False, True])
    monkeypatch.setattr(
        routes_module, "_pair_cache_fresh", lambda params: next(fresh_states, True)
    )

    async def fake_wait(origin, dest, timeout_s):
        return None

    monkeypatch.setattr(routes_module, "_wait_for_fares", fake_wait)
    monkeypatch.setattr(routes_module, "_rerun_search", lambda params: [_itinerary(cents=900)])

    with client.stream("POST", "/api/search", json=SEARCH_BODY) as resp:
        events = _sse_events(resp)
    names = [e for e, _ in events]
    assert names == ["candidates", "verified", "update", "done"]
    update_payload = json.loads(dict(events)["update"])
    assert update_payload[0]["total_cents"] == 900
    meta = json.loads(events[-1][1])["meta"]
    assert meta["searched_pairs_covered"] is True


def test_sse_cold_route_times_out_and_closes(client, monkeypatch):
    monkeypatch.setattr(routes_module, "_pair_cache_fresh", lambda params: False)
    monkeypatch.setattr(get_settings(), "search_stream_max_s", 1)
    monkeypatch.setattr(get_settings(), "search_stream_poll_s", 0.05)
    monkeypatch.setattr(routes_module, "_rerun_search", lambda params: [_itinerary()])

    with client.stream("POST", "/api/search", json=SEARCH_BODY) as resp:
        events = _sse_events(resp)
    names = [e for e, _ in events]
    assert names == ["candidates", "verified", "done"]
    meta = json.loads(events[-1][1])["meta"]
    assert meta == {"crawl_pending": True, "searched_pairs_covered": False}
