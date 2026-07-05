"""Data-quality gates for the curated seed CSVs and the static visa table."""

import re
from collections import Counter

from layoverlab.engine.data.visa_rules import VISA_RULES, get_stopover_hint
from layoverlab.seeds.loaders import _read_data_csv

ISO_3166_ALPHA2 = {
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT", "AU", "AW",
    "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI", "BJ", "BL", "BM", "BN",
    "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY", "BZ", "CA", "CC", "CD", "CF", "CG",
    "CH", "CI", "CK", "CL", "CM", "CN", "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ",
    "DE", "DJ", "DK", "DM", "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI",
    "FJ", "FK", "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL",
    "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM", "HN", "HR",
    "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR", "IS", "IT", "JE", "JM",
    "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN", "KP", "KR", "KW", "KY", "KZ", "LA",
    "LB", "LC", "LI", "LK", "LR", "LS", "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME",
    "MF", "MG", "MH", "MK", "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU",
    "MV", "MW", "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP",
    "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM", "PN", "PR",
    "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW", "SA", "SB", "SC", "SD",
    "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM", "SN", "SO", "SR", "SS", "ST", "SV",
    "SX", "SY", "SZ", "TC", "TD", "TF", "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO",
    "TR", "TT", "TV", "TW", "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE",
    "VG", "VI", "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW",
}

IATA_RE = re.compile(r"^[A-Z]{3}$")


def test_cluster_csv_shape():
    rows = _read_data_csv("clusters.csv")
    assert len({r["cluster_id"] for r in rows}) >= 40
    members: Counter[str] = Counter()
    seen_iata: set[str] = set()
    for r in rows:
        assert IATA_RE.match(r["iata"]), r
        assert r["cluster_name"].strip(), r
        assert r["source"].startswith("http"), f"missing source citation: {r}"
        assert r["iata"] not in seen_iata, f"airport in two clusters: {r['iata']}"
        seen_iata.add(r["iata"])
        members[r["cluster_id"]] += 1
    assert all(n >= 2 for n in members.values()), members


def test_cluster_members_exist_in_airports(session):
    from layoverlab.db.models import Airport
    from layoverlab.seeds.loaders import load_airports, load_clusters

    header = (
        "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,iso_country,"
        "iso_region,municipality,scheduled_service,icao_code,iata_code,gps_code,local_code,"
        "home_link,wikipedia_link,keywords"
    )
    rows = _read_data_csv("clusters.csv")
    lines = [header]
    for i, r in enumerate(rows):
        lines.append(
            f"{i},X{i},large_airport,{r['iata']} Airport,0.0,0.0,0,EU,DE,DE-X,"
            f"{r['cluster_name']},yes,XXXX,{r['iata']},,,,,"
        )
    load_clusters(session)
    load_airports(session, csv_text="\n".join(lines) + "\n")
    for r in rows:
        airport = session.get(Airport, r["iata"])
        assert airport is not None and airport.cluster_id == r["cluster_id"], r


def test_ground_links_csv_quality():
    rows = _read_data_csv("ground_links.csv")
    directed: set[tuple[str, str]] = set()
    for r in rows:
        a, b = r["from_iata"].upper(), r["to_iata"].upper()
        assert IATA_RE.match(a) and IATA_RE.match(b), r
        assert a != b, f"self-loop: {r}"
        assert r["mode"] in {"train", "bus"}, r
        assert 15 <= int(r["minutes"]) <= 720, r
        assert 0 <= int(r["price_cents"]) <= 30000, r
        for pair in ((a, b), (b, a)):
            assert pair not in directed, f"duplicate directed pair: {pair}"
            directed.add(pair)
    assert len(directed) >= 120


def test_visa_rules_table():
    assert len(VISA_RULES) >= 60
    for code, rule in VISA_RULES.items():
        assert code in ISO_3166_ALPHA2, code
        assert rule["country"].strip() and rule["note"].strip(), code

    hint = get_stopover_hint("MA")
    assert hint is not None and hint.startswith("Morocco:")
    assert hint.endswith("check rules for your passport.")
    assert get_stopover_hint("ma") == hint
    assert get_stopover_hint("XX") is None
    assert get_stopover_hint("") is None
