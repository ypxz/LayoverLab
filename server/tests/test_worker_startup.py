from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from layoverlab.crawler.heartbeat import beat, last_heartbeat_age_s, worker_alive
from layoverlab.crawler.run import wait_for_migrations
from layoverlab.db.models import Base, utcnow


def _engine():
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


def test_wait_for_migrations_returns_when_schema_ready():
    engine = _engine()
    Base.metadata.create_all(engine)
    wait_for_migrations(engine, timeout_s=1.0, poll_s=0.01)


def test_wait_for_migrations_times_out_when_tables_missing():
    engine = _engine()
    with pytest.raises(TimeoutError, match="request_budgets|crawl_jobs|route_coverage|fares"):
        wait_for_migrations(engine, timeout_s=0.05, poll_s=0.01)


def test_wait_for_migrations_unblocks_once_tables_appear():
    engine = _engine()
    Base.metadata.create_all(engine)
    Base.metadata.drop_all(engine, tables=[Base.metadata.tables["request_budgets"]])
    with pytest.raises(TimeoutError):
        wait_for_migrations(engine, timeout_s=0.05, poll_s=0.01)
    Base.metadata.create_all(engine)
    wait_for_migrations(engine, timeout_s=1.0, poll_s=0.01)


def test_heartbeat_beat_and_alive(session):
    assert last_heartbeat_age_s(session) is None
    assert worker_alive(session) is False

    beat(session)
    age = last_heartbeat_age_s(session)
    assert age is not None and age < 5.0
    assert worker_alive(session) is True

    stale = utcnow() + timedelta(seconds=3600)
    assert worker_alive(session, now=stale) is False

    beat(session)  # idempotent upsert of the same row
    assert worker_alive(session) is True
