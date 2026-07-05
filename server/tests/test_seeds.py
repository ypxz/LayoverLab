from sqlalchemy import select

from layoverlab.db.models import Airport, GroundLink, Route
from layoverlab.seeds import load_all as load_all_module
from layoverlab.seeds.load_all import is_seeded
from layoverlab.seeds.loaders import (
    load_airports,
    load_clusters,
    load_ground_links,
    load_routes,
    load_routes_auto,
    load_routes_jonty,
)

AIRPORTS_CSV = """id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,iso_country,iso_region,municipality,scheduled_service,icao_code,iata_code,gps_code,local_code,home_link,wikipedia_link,keywords
1,EDDB,large_airport,Berlin Brandenburg,52.36,13.5,157,EU,DE,DE-BB,Berlin,yes,EDDB,BER,EDDB,,,,
2,EGSS,large_airport,London Stansted,51.88,0.23,348,EU,GB,GB-ENG,London,yes,EGSS,STN,EGSS,,,,
3,XXXX,small_airport,Tiny Field,10.0,10.0,10,EU,DE,DE-XX,Nowhere,no,XXXX,,XXXX,,,,
4,LEAL,medium_airport,Alicante,38.28,-0.55,142,EU,ES,ES-V,Alicante,yes,LEAL,ALC,LEAL,,,,
"""

ROUTES_DAT = """FR,4296,BER,123,ALC,456,,0,738
FR,4296,BER,123,STN,789,,0,738
U2,2297,BER,123,ALC,456,,0,320
ZZ,999,QQQ,1,WWW,2,,0,738
"""

TZ_CSV = """"icao","iata","name","city","subd","country","elevation","lat","lon","tz","lid"
"EDDB","BER","Berlin Brandenburg","Berlin","","DE",157,52.36,13.5,"Europe/Berlin",""
"LEAL","ALC","Alicante","Alicante","","ES",142,38.28,-0.55,"Europe/Madrid",""
"""

JONTY_JSON = """{
  "BER": {"iata": "BER", "routes": [
    {"iata": "ALC", "km": 1800, "min": 170,
     "carriers": [{"iata": "FR", "name": "Ryanair"}, {"iata": "U2", "name": "easyJet"}]},
    {"iata": "STN", "km": 930, "min": 105, "carriers": [{"iata": "FR", "name": "Ryanair"}]},
    {"iata": "QQQ", "km": 1, "min": 1, "carriers": [{"iata": "ZZ", "name": "Nobody"}]},
    {"iata": "BER", "km": 0, "min": 0, "carriers": []}
  ]},
  "ALC": {"iata": "ALC", "routes": [{"iata": "BER", "km": 1800, "min": 175, "carriers": []}]}
}"""


def test_seed_pipeline(session):
    n_clusters = load_clusters(session)
    assert n_clusters > 10

    n_airports = load_airports(session, csv_text=AIRPORTS_CSV)
    assert n_airports == 3  # small_airport / no-iata rows filtered out
    stn = session.get(Airport, "STN")
    assert stn.cluster_id == "LON"

    n_links = load_ground_links(session)
    assert n_links == 0  # none of the corridor airports exist in this tiny fixture

    n_routes = load_routes(session, dat_text=ROUTES_DAT)
    assert n_routes == 2  # QQQ/WWW filtered (unknown airports); BER-ALC deduped across carriers
    ber_alc = session.get(Route, ("BER", "ALC"))
    assert ber_alc.frequency_score == 2.0
    assert ber_alc.carriers == ["FR", "U2"]

    # idempotency
    load_clusters(session)
    load_airports(session, csv_text=AIRPORTS_CSV)
    load_routes(session, dat_text=ROUTES_DAT)
    assert len(session.execute(select(Airport)).scalars().all()) == 3
    assert len(session.execute(select(Route)).scalars().all()) == 2
    assert len(session.execute(select(GroundLink)).scalars().all()) == 0


def test_airport_tz_join(session):
    load_clusters(session)
    load_airports(session, csv_text=AIRPORTS_CSV, tz_csv_text=TZ_CSV)
    assert session.get(Airport, "BER").tz == "Europe/Berlin"
    assert session.get(Airport, "ALC").tz == "Europe/Madrid"
    assert session.get(Airport, "STN").tz is None  # missing in tz dataset -> null

    load_airports(session, csv_text=AIRPORTS_CSV, tz_csv_text=TZ_CSV)  # idempotent
    assert len(session.execute(select(Airport)).scalars().all()) == 3


def test_load_routes_jonty(session, monkeypatch):
    load_clusters(session)
    load_airports(session, csv_text=AIRPORTS_CSV)
    n = load_routes_jonty(session, json_text=JONTY_JSON)
    assert n == 3  # QQQ + self-loop dropped
    ber_alc = session.get(Route, ("BER", "ALC"))
    assert ber_alc.carriers == ["FR", "U2"]
    assert ber_alc.frequency_score == 2.0
    assert session.get(Route, ("ALC", "BER")).carriers == ["??"]  # carrier-less route kept

    load_routes_jonty(session, json_text=JONTY_JSON)  # idempotent
    assert len(session.execute(select(Route)).scalars().all()) == 3

    monkeypatch.setenv("ROUTES_SOURCE", "jonty")
    monkeypatch.setattr(
        "layoverlab.seeds.loaders._download", lambda url, timeout=120.0: JONTY_JSON
    )
    assert load_routes_auto(session) == 3

    monkeypatch.setenv("ROUTES_SOURCE", "openflights")
    monkeypatch.setattr(
        "layoverlab.seeds.loaders._download", lambda url, timeout=120.0: ROUTES_DAT
    )
    assert load_routes_auto(session) == 2


def _fake_scope(session):
    from contextlib import contextmanager

    @contextmanager
    def scope():
        yield session

    return scope


def test_load_all_skips_when_already_seeded(session, monkeypatch):
    assert is_seeded(session) is False
    load_clusters(session)
    load_airports(session, csv_text=AIRPORTS_CSV)
    assert is_seeded(session) is False  # routes still empty
    load_routes(session, dat_text=ROUTES_DAT)
    assert is_seeded(session) is True

    monkeypatch.setattr(load_all_module, "session_scope", _fake_scope(session))
    calls: list[str] = []
    for name in ("load_clusters", "load_airports", "load_ground_links", "load_routes_auto"):
        monkeypatch.setattr(load_all_module, name, lambda s, _n=name: calls.append(_n) or 1)

    assert load_all_module.run() is False  # already seeded -> no loader runs, no downloads
    assert calls == []

    assert load_all_module.run(force=True) is True
    assert calls == ["load_clusters", "load_airports", "load_ground_links", "load_routes_auto"]


def test_load_all_runs_on_empty_db(session, monkeypatch):
    monkeypatch.setattr(load_all_module, "session_scope", _fake_scope(session))
    calls: list[str] = []
    for name in ("load_clusters", "load_airports", "load_ground_links", "load_routes_auto"):
        monkeypatch.setattr(load_all_module, name, lambda s, _n=name: calls.append(_n) or 1)
    assert load_all_module.run() is True
    assert len(calls) == 4
