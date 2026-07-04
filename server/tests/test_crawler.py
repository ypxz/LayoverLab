from datetime import date

from sqlalchemy import select

from layoverlab.connectors.base import DayFare
from layoverlab.crawler.prioritizer import enqueue_for_search
from layoverlab.crawler.service import upsert_fares
from layoverlab.db.models import CrawlJob, Fare, Route, utcnow
from tests.conftest import add_airport

D = date(2026, 8, 1)


def _fare(origin: str, dest: str, dep: date, cents: int) -> DayFare:
    return DayFare(
        origin=origin, dest=dest, dep_date=dep, price_cents=cents,
        currency="EUR", deep_link=None,
    )


def test_upsert_fares_inserts_then_updates(session):
    n = upsert_fares(session, [_fare("BER", "ALC", D, 1999)], source="ryanair")
    assert n == 1
    upsert_fares(session, [_fare("BER", "ALC", D, 1500)], source="ryanair")
    rows = session.execute(select(Fare)).scalars().all()
    assert len(rows) == 1
    assert rows[0].min_price_cents == 1500


def test_enqueue_for_search_creates_direct_and_hub_jobs(session):
    add_airport(session, "BER", "DE")
    add_airport(session, "BKK", "TH")
    add_airport(session, "IST", "TR")
    session.add(Route(origin="BER", dest="IST", carriers=["TK"], frequency_score=5.0, last_seen=utcnow()))
    session.add(Route(origin="IST", dest="BKK", carriers=["TK"], frequency_score=5.0, last_seen=utcnow()))
    session.flush()

    created = enqueue_for_search(session, "BER", "BKK", date(2026, 8, 1), date(2026, 8, 31))
    jobs = session.execute(select(CrawlJob)).scalars().all()

    assert created == len(jobs) > 0
    pairs = {(j.origin, j.dest) for j in jobs}
    assert ("BER", "BKK") in pairs          # direct
    assert ("BER", "IST") in pairs          # origin -> hub
    assert ("IST", "BKK") in pairs          # hub -> dest
    direct = [j for j in jobs if (j.origin, j.dest) == ("BER", "BKK")]
    assert all(j.priority == 100 for j in direct)


def test_enqueue_is_idempotent_and_bumps_priority(session):
    add_airport(session, "BER", "DE")
    add_airport(session, "ALC", "ES")
    first = enqueue_for_search(session, "BER", "ALC", D, D)
    second = enqueue_for_search(session, "BER", "ALC", D, D)
    assert first > 0
    assert second == 0  # same coverage -> no duplicate jobs
