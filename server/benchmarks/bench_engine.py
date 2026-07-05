"""Engine benchmark harness: seeded synthetic fare slices, timed searches, JSON results.

Builds an in-memory SQLite DB with a hub-and-spoke synthetic network sized to N fares,
runs a fixed set of seeded searches through the full engine path (load_slice + Dijkstra)
and reports p50/p95/max latency plus peak RSS.

Usage (from server/, venv active):
  python benchmarks/bench_engine.py [--sizes 10000,50000,200000] [--searches 20]
      [--out benchmarks/results.json] [--assert-p95 50000:1200]

--assert-p95 SIZE:MS makes the run exit non-zero when p95 for that slice size exceeds
the budget — used by the nightly CI job (budget: 1200ms @ 50k fares).
"""

import argparse
import json
import platform
import random
import resource
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from layoverlab.db.models import Airport, AirportCluster, Base, Fare
from layoverlab.engine.models import SearchParams
from layoverlab.engine.search import search

HORIZON_DAYS = 45
N_HUBS = 10
N_SPOKES = 110
BASE_DATE = date(2027, 3, 1)
SEED = 1337


def _airport_codes() -> tuple[list[str], list[str]]:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    hubs = [f"H{letters[i // 26]}{letters[i % 26]}" for i in range(N_HUBS)]
    spokes = [f"S{letters[i // 26]}{letters[i % 26]}" for i in range(N_SPOKES)]
    return hubs, spokes


def _pairs(rng: random.Random) -> list[tuple[str, str]]:
    """Deterministic pair universe: hub<->hub plus spoke<->hub, shuffled."""
    hubs, spokes = _airport_codes()
    pairs: list[tuple[str, str]] = []
    for a in hubs:
        for b in hubs:
            if a != b:
                pairs.append((a, b))
    for s in spokes:
        for h in hubs:
            pairs.append((s, h))
            pairs.append((h, s))
    rng.shuffle(pairs)
    return pairs


def build_db(n_fares: int) -> sessionmaker:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    rng = random.Random(SEED)
    hubs, spokes = _airport_codes()
    now = datetime.now(timezone.utc)
    with factory() as session:
        session.add(AirportCluster(id="HUB0", name="Hub cluster"))
        for iata in [*hubs, *spokes]:
            session.add(
                Airport(
                    iata=iata, name=f"{iata} Airport", city=iata, country_code="DE",
                    lat=0.0, lon=0.0, cluster_id="HUB0" if iata in ("H00", "H01") else None,
                )
            )
        session.flush()
        pairs = _pairs(rng)
        pair_count = max(1, -(-n_fares // HORIZON_DAYS))  # ceil
        inserted = 0
        for i in range(pair_count):
            origin, dest = pairs[i % len(pairs)]
            source = f"bench{i // len(pairs)}"  # wrap: extra sources keep (pair, day) rows unique
            for offset in range(HORIZON_DAYS):
                if inserted >= n_fares:
                    break
                dep = BASE_DATE + timedelta(days=offset)
                session.add(
                    Fare(
                        origin=origin, dest=dest, dep_date=dep, source=source,
                        min_price_cents=rng.randint(1500, 40000), currency="EUR",
                        deep_link=None, fetched_at=now, expires_at=now + timedelta(hours=48),
                    )
                )
                inserted += 1
        session.commit()
    return factory


def bench_size(n_fares: int, n_searches: int) -> dict:
    factory = build_db(n_fares)
    rng = random.Random(SEED + 1)
    _, spokes = _airport_codes()
    timings_ms: list[float] = []
    result_counts: list[int] = []
    with factory() as session:
        for _ in range(n_searches):
            origin, dest = rng.sample(spokes, 2)
            params = SearchParams(
                origin=origin,
                dest=dest,
                date_from=BASE_DATE + timedelta(days=3),
                date_to=BASE_DATE + timedelta(days=9),
                round_trip=False,
                max_stops=2,
                top_k=10,
            )
            start = time.perf_counter()
            itins = search(params, session)
            timings_ms.append((time.perf_counter() - start) * 1000)
            result_counts.append(len(itins))
    timings_ms.sort()
    p95_index = max(0, int(len(timings_ms) * 0.95) - 1)
    return {
        "fares": n_fares,
        "searches": n_searches,
        "p50_ms": round(statistics.median(timings_ms), 1),
        "p95_ms": round(timings_ms[p95_index], 1),
        "max_ms": round(timings_ms[-1], 1),
        "mean_results": round(statistics.mean(result_counts), 1),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="10000,50000,200000")
    parser.add_argument("--searches", type=int, default=20)
    parser.add_argument("--out", default="benchmarks/results.json")
    parser.add_argument(
        "--assert-p95", default=None, metavar="SIZE:MS",
        help="fail (exit 1) when p95 for SIZE fares exceeds MS milliseconds",
    )
    args = parser.parse_args()

    sizes = [int(s) for s in args.sizes.split(",") if s]
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seed": SEED,
        "sizes": [],
    }
    for size in sizes:
        row = bench_size(size, args.searches)
        results["sizes"].append(row)
        print(
            f"[{size} fares] p50={row['p50_ms']}ms p95={row['p95_ms']}ms "
            f"max={row['max_ms']}ms rss={row['peak_rss_mb']}MB",
            file=sys.stderr,
        )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    print(f"results written to {args.out}", file=sys.stderr)

    if args.assert_p95:
        size_s, budget_s = args.assert_p95.split(":")
        size, budget = int(size_s), float(budget_s)
        row = next((r for r in results["sizes"] if r["fares"] == size), None)
        if row is None:
            print(f"assert-p95: size {size} was not benchmarked", file=sys.stderr)
            return 1
        if row["p95_ms"] > budget:
            print(f"assert-p95 FAILED: p95@{size}={row['p95_ms']}ms > {budget}ms", file=sys.stderr)
            return 1
        print(f"assert-p95 ok: p95@{size}={row['p95_ms']}ms <= {budget}ms", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
