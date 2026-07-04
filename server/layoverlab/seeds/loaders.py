"""Idempotent seed loaders: airports (OurAirports), clusters, ground links, routes (OpenFlights)."""

import csv
import io
import logging
from importlib.resources import files

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from layoverlab.db.models import Airport, AirportCluster, GroundLink, Route, utcnow

log = logging.getLogger(__name__)

OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OPENFLIGHTS_ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"

_ALLOWED_TYPES = {"large_airport", "medium_airport"}


def _read_data_csv(name: str) -> list[dict]:
    text = files("layoverlab.seeds").joinpath("data", name).read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def _download(url: str, timeout: float = 120.0) -> str:
    log.info("downloading %s", url)
    resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def load_clusters(session: Session) -> int:
    rows = _read_data_csv("clusters.csv")
    seen: dict[str, str] = {}
    for row in rows:
        seen[row["cluster_id"]] = row["cluster_name"]
    for cid, name in seen.items():
        existing = session.get(AirportCluster, cid)
        if existing:
            existing.name = name
        else:
            session.add(AirportCluster(id=cid, name=name))
    session.flush()
    return len(seen)


def load_airports(session: Session, csv_text: str | None = None) -> int:
    csv_text = csv_text or _download(OURAIRPORTS_URL)
    cluster_by_iata = {r["iata"]: r["cluster_id"] for r in _read_data_csv("clusters.csv")}
    reader = csv.DictReader(io.StringIO(csv_text))
    count = 0
    for row in reader:
        iata = (row.get("iata_code") or "").strip().upper()
        if len(iata) != 3:
            continue
        if row.get("type") not in _ALLOWED_TYPES:
            continue
        if row.get("scheduled_service") != "yes":
            continue
        try:
            lat, lon = float(row["latitude_deg"]), float(row["longitude_deg"])
        except (KeyError, ValueError):
            continue
        existing = session.get(Airport, iata)
        values = dict(
            name=(row.get("name") or "")[:128],
            city=(row.get("municipality") or "")[:96],
            country_code=(row.get("iso_country") or "")[:2],
            lat=lat,
            lon=lon,
            cluster_id=cluster_by_iata.get(iata),
        )
        if existing:
            for k, v in values.items():
                setattr(existing, k, v)
        else:
            session.add(Airport(iata=iata, **values))
        count += 1
    session.flush()
    return count


def load_ground_links(session: Session) -> int:
    session.execute(delete(GroundLink))
    known = {a for (a,) in session.execute(select(Airport.iata))}
    count = 0
    for row in _read_data_csv("ground_links.csv"):
        a, b = row["from_iata"].upper(), row["to_iata"].upper()
        if known and (a not in known or b not in known):
            log.warning("skipping ground link %s-%s (unknown airport)", a, b)
            continue
        for x, y in ((a, b), (b, a)):
            session.add(
                GroundLink(
                    from_iata=x,
                    to_iata=y,
                    mode=row["mode"],
                    minutes=int(row["minutes"]),
                    price_cents=int(row["price_cents"]),
                    currency="EUR",
                )
            )
            count += 1
    session.flush()
    return count


def load_routes(session: Session, dat_text: str | None = None) -> int:
    """OpenFlights routes.dat -> routes table. Stale (2014) but fine for topology weighting."""
    dat_text = dat_text or _download(OPENFLIGHTS_ROUTES_URL)
    known = {a for (a,) in session.execute(select(Airport.iata))}
    pairs: dict[tuple[str, str], set[str]] = {}
    for line in dat_text.splitlines():
        parts = line.split(",")
        if len(parts) < 5:
            continue
        carrier, origin, dest = parts[0].strip(), parts[2].strip().upper(), parts[4].strip().upper()
        if len(origin) != 3 or len(dest) != 3 or origin == dest:
            continue
        if known and (origin not in known or dest not in known):
            continue
        pairs.setdefault((origin, dest), set()).add(carrier)
    session.execute(delete(Route))
    now = utcnow()
    for (origin, dest), carriers in pairs.items():
        session.add(
            Route(
                origin=origin,
                dest=dest,
                carriers=sorted(carriers),
                frequency_score=float(len(carriers)),
                last_seen=now,
            )
        )
    session.flush()
    return len(pairs)
