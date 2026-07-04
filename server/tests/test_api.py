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
    assert client.get("/api/health").json() == {"status": "ok"}


def test_airports_autocomplete_prefers_exact_iata(client, session):
    add_airport(session, "BER", "DE")
    add_airport(session, "ALC", "ES")
    body = client.get("/api/airports", params={"q": "ber"}).json()
    assert body[0]["iata"] == "BER"


def test_search_sse_event_order(client):
    payload = {"origin": "BER", "dest": "ALC", "date_from": "2026-08-01", "date_to": "2026-08-31"}
    with client.stream("POST", "/api/search", json=payload) as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
    assert events == ["candidates", "verified", "done"]


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
