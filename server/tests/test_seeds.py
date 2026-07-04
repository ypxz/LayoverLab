from sqlalchemy import select

from layoverlab.db.models import Airport, GroundLink, Route
from layoverlab.seeds.loaders import load_airports, load_clusters, load_ground_links, load_routes

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
