import asyncio
import time
from datetime import date, datetime, timezone

import pytest

from layoverlab.connectors.base import DayFare
from layoverlab.engine import verify as verify_module
from layoverlab.engine.models import Itinerary, Leg
from layoverlab.engine.verify import verify_top

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)
DEP = date(2026, 8, 15)


def make_leg(origin: str, dest: str, cents: int, source: str = "fake", **extra) -> Leg:
    return Leg(
        origin=origin, dest=dest, dep_date=DEP, mode="flight",
        price_cents=cents, currency="EUR", source=source,
        deep_link=None, fetched_at=NOW, **extra,
    )


def make_itin(legs: list[Leg], warnings: list[str] | None = None) -> Itinerary:
    return Itinerary(
        legs=legs, total_cents=sum(leg.price_cents for leg in legs), currency="EUR",
        stopovers=[], warnings=warnings or [], verified=False,
    )


class FakeConnector:
    name = "fake"

    def __init__(self, prices: dict[tuple[str, str], int | None], latency_s: float = 0.0):
        self.prices = prices
        self.latency_s = latency_s
        self.calls = 0

    async def fetch_month(self, origin, dest, month):
        return []

    async def routes_from(self, origin):
        return []

    async def verify_day(self, origin, dest, dep_date) -> DayFare | None:
        self.calls += 1
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        cents = self.prices.get((origin, dest))
        if cents is None:
            return None
        return DayFare(
            origin=origin, dest=dest, dep_date=dep_date,
            price_cents=cents, currency="EUR", deep_link=None,
        )


class DownConnector:
    name = "fake"

    async def fetch_month(self, origin, dest, month):
        return []

    async def routes_from(self, origin):
        return []

    async def verify_day(self, origin, dest, dep_date):
        raise RuntimeError("source down")


@pytest.fixture()
def use_connectors(monkeypatch):
    def _use(connectors: dict):
        monkeypatch.setattr(verify_module, "all_connectors", lambda: connectors)
        monkeypatch.setattr(verify_module, "load_default_connectors", lambda: None)

    return _use


async def test_price_drift_note_and_rerank(use_connectors):
    fake = FakeConnector({("BER", "PMI"): 5200, ("AMS", "ALC"): 2000})
    use_connectors({"fake": fake})
    cheap_but_drifting = make_itin([make_leg("BER", "PMI", 4055)])  # verifies to 52.00 (+28%)
    stable = make_itin([make_leg("AMS", "ALC", 2000)])
    stable = stable.model_copy(update={"total_cents": 2000})
    result = await verify_top([cheap_but_drifting.model_copy(update={"total_cents": 4055}), stable])
    assert [i.total_cents for i in result] == [2000, 5200]
    drifted = result[1]
    assert drifted.verified is True
    assert any("Price changed since cached: 40.55 -> 52.00 EUR" in w for w in drifted.warnings)
    assert not any("Price changed" in w for w in result[0].warnings)


async def test_small_drift_no_note(use_connectors):
    fake = FakeConnector({("BER", "PMI"): 4200})
    use_connectors({"fake": fake})
    result = await verify_top([make_itin([make_leg("BER", "PMI", 4055)])])
    assert result[0].verified is True
    assert not any("Price changed" in w for w in result[0].warnings)


async def test_buffer_drop_with_fabricated_times(use_connectors, monkeypatch):
    fake = FakeConnector({("BER", "AMS"): 3000, ("AMS", "ALC"): 3000})
    use_connectors({"fake": fake})

    async def fake_times(leg):
        if leg.origin == "BER":
            return datetime(2026, 8, 15, 8, 0), datetime(2026, 8, 15, 10, 0)
        return datetime(2026, 8, 15, 11, 30), datetime(2026, 8, 15, 14, 0)  # 1.5h gap

    monkeypatch.setattr(verify_module, "_fetch_times", fake_times)
    itin = make_itin([make_leg("BER", "AMS", 3000), make_leg("AMS", "ALC", 3000)])
    result = await verify_top([itin])
    out = result[0]
    assert out.verified is False  # dropped from verified, kept as candidate
    assert any("below the 3h self-transfer minimum" in w for w in out.warnings)
    assert out.legs[0].dep_time == datetime(2026, 8, 15, 8, 0)
    assert out.legs[1].arr_time == datetime(2026, 8, 15, 14, 0)


async def test_buffer_strong_warning_3_to_6h(use_connectors, monkeypatch):
    fake = FakeConnector({("BER", "AMS"): 3000, ("AMS", "ALC"): 3000})
    use_connectors({"fake": fake})

    async def fake_times(leg):
        if leg.origin == "BER":
            return datetime(2026, 8, 15, 8, 0), datetime(2026, 8, 15, 10, 0)
        return datetime(2026, 8, 15, 14, 0), datetime(2026, 8, 15, 16, 0)  # 4h gap

    monkeypatch.setattr(verify_module, "_fetch_times", fake_times)
    result = await verify_top([make_itin([make_leg("BER", "AMS", 3000), make_leg("AMS", "ALC", 3000)])])
    out = result[0]
    assert out.verified is True
    assert any("tight for a self-transfer" in w for w in out.warnings)


async def test_overnight_stopover_unaffected(use_connectors, monkeypatch):
    fake = FakeConnector({("BER", "AMS"): 3000, ("AMS", "ALC"): 3000})
    use_connectors({"fake": fake})

    async def fake_times(leg):
        if leg.origin == "BER":
            return datetime(2026, 8, 15, 8, 0), datetime(2026, 8, 15, 10, 0)
        return datetime(2026, 8, 16, 11, 0), datetime(2026, 8, 16, 13, 0)  # next day

    monkeypatch.setattr(verify_module, "_fetch_times", fake_times)
    result = await verify_top([make_itin([make_leg("BER", "AMS", 3000), make_leg("AMS", "ALC", 3000)])])
    out = result[0]
    assert out.verified is True
    assert not any("Connection in" in w for w in out.warnings)


async def test_times_unknown_keeps_heuristics_untouched(use_connectors):
    fake = FakeConnector({("BER", "AMS"): 3000, ("AMS", "ALC"): 3000})
    use_connectors({"fake": fake})
    heuristic = "Tight same-day self-transfer in AMS: verify actual flight times"
    itin = make_itin(
        [make_leg("BER", "AMS", 3000), make_leg("AMS", "ALC", 3000)], warnings=[heuristic]
    )
    result = await verify_top([itin])
    out = result[0]
    assert out.verified is True
    assert heuristic in out.warnings
    assert not any("Connection in" in w for w in out.warnings)


async def test_source_down_keeps_cached_unverified(use_connectors):
    use_connectors({"fake": DownConnector()})
    itin = make_itin([make_leg("BER", "PMI", 4055)])
    result = await verify_top([itin])
    out = result[0]
    assert out.verified is False
    assert out.total_cents == 4055
    assert out.legs[0].price_cents == 4055


async def test_unknown_source_unverified(use_connectors):
    use_connectors({})
    result = await verify_top([make_itin([make_leg("BER", "PMI", 4055, source="nope")])])
    assert result[0].verified is False


async def test_verify_budget_top_k(use_connectors, monkeypatch):
    monkeypatch.setenv("VERIFY_TOP_K", "2")
    from layoverlab.settings import get_settings

    get_settings.cache_clear()
    try:
        fake = FakeConnector({("BER", "PMI"): 4000})
        use_connectors({"fake": fake})
        itins = [make_itin([make_leg("BER", "PMI", 4000)]) for _ in range(5)]
        result = await verify_top(itins, n=5)
        assert fake.calls == 2
        assert sum(1 for i in result if i.verified) == 2
    finally:
        get_settings.cache_clear()


async def test_verify_wall_clock_budget(use_connectors):
    fake = FakeConnector(
        {("BER", "AMS"): 3000, ("AMS", "ALC"): 3000}, latency_s=1.0
    )
    use_connectors({"fake": fake})
    itins = [
        make_itin([make_leg("BER", "AMS", 3000), make_leg("AMS", "ALC", 3000)])
        for _ in range(5)
    ]
    start = time.perf_counter()
    result = await verify_top(itins, n=5)
    elapsed = time.perf_counter() - start
    assert fake.calls == 10
    assert all(i.verified for i in result)
    assert elapsed < 12.0
    assert elapsed < 5.0  # 10 legs x 1s mocked latency must overlap, not serialize
