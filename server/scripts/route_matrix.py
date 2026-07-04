"""Route-matrix harness: run a matrix of searches against a running API, print a markdown report.

Modes:
  --fixture  deterministic run against a FIXTURE_CONNECTOR=true stack; seeds the DB
             (unless --no-seed), asserts baseline expectations, non-zero exit on failure.
  --live     low-volume observational run against real connectors; never in CI.

Usage (from server/, venv active):
  python scripts/route_matrix.py --fixture [--base-url http://localhost:8000/api]
      [--month YYYY-MM] [--out route_matrix_report.md] [--no-seed]
  python scripts/route_matrix.py --live [--base-url ...] [--month YYYY-MM] [--out ...]

The report buckets latencies so repeated runs on identical data stay diff-friendly;
exact timings go to stderr.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx

DEFAULT_BASE_URL = "http://localhost:8000/api"
LATENCY_BUCKETS_MS = [250, 1000, 2000, 5000, 15000, 60000]


@dataclass
class MatrixRow:
    route_class: str
    origin: str
    dest: str
    round_trip: bool = False
    window_days: int = 6


MATRIX: list[MatrixRow] = [
    MatrixRow("LCC intra-EU", "BER", "ALC"),
    MatrixRow("cluster pair", "LHR", "MXP"),
    MatrixRow("ground corridor", "CGN", "PMI"),
    MatrixRow("long-haul", "BER", "BKK"),
    MatrixRow("domestic", "BER", "MUC"),
    MatrixRow("island", "MAD", "PMI"),
    MatrixRow("round trip", "BER", "ALC", round_trip=True),
    MatrixRow("stopover beats direct", "HAM", "ALC"),
]


@dataclass
class RunResult:
    events: list[tuple[str, object]] = field(default_factory=list)
    first_event_ms: float | None = None
    done_ms: float | None = None
    error: str | None = None

    def final_itineraries(self) -> list[dict]:
        latest: list[dict] = []
        for name, payload in self.events:
            if name in ("candidates", "verified", "update") and isinstance(payload, list):
                latest = payload
        return latest

    def candidates(self) -> list[dict]:
        for name, payload in self.events:
            if name == "candidates" and isinstance(payload, list):
                return payload
        return []


def stream_search(base_url: str, params: dict, timeout: float) -> RunResult:
    result = RunResult()
    start = time.perf_counter()
    event_name = ""
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, read=timeout)) as client:
            with client.stream("POST", f"{base_url}/search", json=params) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        now_ms = (time.perf_counter() - start) * 1000
                        raw = line.split(":", 1)[1].strip()
                        try:
                            payload = json.loads(raw) if raw else {}
                        except json.JSONDecodeError:
                            payload = raw
                        result.events.append((event_name, payload))
                        if result.first_event_ms is None:
                            result.first_event_ms = now_ms
                        if event_name == "done":
                            result.done_ms = now_ms
    except httpx.HTTPError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def bucket(ms: float | None) -> str:
    if ms is None:
        return "n/a"
    for limit in LATENCY_BUCKETS_MS:
        if ms < limit:
            return f"<{limit / 1000:g}s" if limit >= 1000 else f"<{limit:g}ms"
    return f">={LATENCY_BUCKETS_MS[-1] / 1000:g}s"


def euros(cents: int | None) -> str:
    return "n/a" if cents is None else f"{cents / 100:.2f}"


def describe_best(itins: list[dict]) -> tuple[int | None, str, str]:
    if not itins:
        return None, "n/a", "n/a"
    best = itins[0]
    legs = best.get("legs", [])
    path = "->".join([legs[0]["origin"], *[leg["dest"] for leg in legs]]) if legs else "?"
    modes = "+".join(leg["mode"][0].upper() for leg in legs)
    stopovers = ",".join(f"{s['iata']}x{s['nights']}" for s in best.get("stopovers", [])) or "-"
    return best.get("total_cents"), f"{path} ({modes})", stopovers


def run_matrix(base_url: str, month: date, timeout: float) -> list[dict]:
    rows: list[dict] = []
    for row in MATRIX:
        params: dict = {
            "origin": row.origin,
            "dest": row.dest,
            "date_from": month.isoformat(),
            "date_to": (month + timedelta(days=row.window_days)).isoformat(),
            "round_trip": row.round_trip,
        }
        if row.round_trip:
            params["trip_min_days"] = 3
            params["trip_max_days"] = 7
        for phase in ("cold", "warm"):
            result = stream_search(base_url, params, timeout)
            itins = result.final_itineraries()
            cheapest, best_path, stopovers = describe_best(itins)
            verified_count = sum(1 for itin in itins if itin.get("verified"))
            warnings_present = any(itin.get("warnings") for itin in itins)
            has_error_event = any(name == "error" for name, _ in result.events)
            rows.append(
                {
                    "class": row.route_class,
                    "pair": f"{row.origin}-{row.dest}" + ("-rt" if row.round_trip else ""),
                    "phase": phase,
                    "candidates": len(result.candidates()),
                    "cheapest_cents": cheapest,
                    "best": best_path,
                    "stopovers": stopovers,
                    "first_event_ms": result.first_event_ms,
                    "done_ms": result.done_ms,
                    "verified": verified_count,
                    "warnings": warnings_present,
                    "error": result.error or ("error event" if has_error_event else None),
                    "itins": itins,
                }
            )
            print(
                f"[{row.route_class} {phase}] {row.origin}->{row.dest} "
                f"first={result.first_event_ms and round(result.first_event_ms)}ms "
                f"done={result.done_ms and round(result.done_ms)}ms "
                f"candidates={len(result.candidates())} error={result.error}",
                file=sys.stderr,
            )
    return rows


def render_report(rows: list[dict], mode: str, month: date) -> str:
    lines = [
        "# Route-matrix report",
        "",
        f"- mode: `{mode}`",
        f"- search window start: `{month.isoformat()}`",
        "",
        "| class | pair | phase | candidates | cheapest EUR | best route | stopovers "
        "| first event | done | verified | warnings | error |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['class']} | {r['pair']} | {r['phase']} | {r['candidates']} "
            f"| {euros(r['cheapest_cents'])} | {r['best']} | {r['stopovers']} "
            f"| {bucket(r['first_event_ms'])} | {bucket(r['done_ms'])} "
            f"| {r['verified']} | {'yes' if r['warnings'] else 'no'} | {r['error'] or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def assert_fixture_baseline(rows: list[dict]) -> list[str]:
    from layoverlab.connectors.fixture import fixture_price_cents

    failures: list[str] = []
    by_key = {(r["class"], r["phase"]): r for r in rows}

    def check(cond: bool, message: str) -> None:
        if not cond:
            failures.append(message)

    for phase in ("cold", "warm"):
        for cls in [r.route_class for r in MATRIX]:
            r = by_key[(cls, phase)]
            check(r["error"] is None, f"{cls}/{phase}: stream error: {r['error']}")
            check(r["candidates"] >= 1, f"{cls}/{phase}: no candidates")
            check(r["done_ms"] is not None, f"{cls}/{phase}: no done event")

        r = by_key[("LCC intra-EU", phase)]
        check(
            bool(r["itins"]) and len(r["itins"][0]["legs"]) == 1,
            f"LCC/{phase}: best BER-ALC should be direct",
        )
        check(
            r["cheapest_cents"] is not None and r["cheapest_cents"] < 5000,
            f"LCC/{phase}: BER-ALC cheapest {r['cheapest_cents']} not < 5000",
        )
        check(r["verified"] >= 1, f"LCC/{phase}: nothing verified (fixture connector missing?)")

        r = by_key[("cluster pair", phase)]
        check(
            bool(r["itins"]) and r["itins"][0]["legs"][-1]["dest"] in ("MXP", "BGY"),
            f"cluster/{phase}: LHR-MXP best should end in Milan cluster",
        )

        r = by_key[("ground corridor", phase)]
        check(
            bool(r["itins"]) and any(leg["mode"] == "ground" for leg in r["itins"][0]["legs"]),
            f"ground/{phase}: CGN-PMI best should include a ground leg",
        )

        r = by_key[("long-haul", phase)]
        if r["itins"]:
            best = r["itins"][0]
            dep = date.fromisoformat(best["legs"][0]["dep_date"])
            direct = fixture_price_cents("BER", "BKK", dep)
            check(
                len(best["legs"]) >= 2 and direct is not None and best["total_cents"] < direct,
                f"long-haul/{phase}: stopover combo should beat direct",
            )
        else:
            failures.append(f"long-haul/{phase}: no itineraries")

        r = by_key[("stopover beats direct", phase)]
        if r["itins"]:
            best = r["itins"][0]
            dep = date.fromisoformat(best["legs"][0]["dep_date"])
            direct = fixture_price_cents("HAM", "ALC", dep)
            check(
                len(best["legs"]) >= 2 and direct is not None and best["total_cents"] < direct,
                f"stopover/{phase}: HAM-ALC combo should beat direct",
            )
        else:
            failures.append(f"stopover/{phase}: no itineraries")

        r = by_key[("round trip", phase)]
        check(
            bool(r["itins"]) and len(r["itins"][0]["legs"]) >= 2,
            f"round trip/{phase}: BER-ALC-rt best should have outbound+inbound legs",
        )

    return failures


def seed(month: date) -> None:
    from layoverlab.connectors.fixture import seed_fixture_stack
    from layoverlab.db.session import session_scope

    months = [month.replace(day=1), (month.replace(day=1) + timedelta(days=32)).replace(day=1)]
    with session_scope() as session:
        n = seed_fixture_stack(session, months)
    print(f"seeded {n} fixture fares for {[m.isoformat() for m in months]}", file=sys.stderr)


def default_month() -> date:
    today = date.today()
    return (today.replace(day=1) + timedelta(days=62)).replace(day=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", action="store_true", help="deterministic fixture-stack mode")
    mode.add_argument("--live", action="store_true", help="observational low-volume live mode")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--month", help="search window start, YYYY-MM (default: +2 months)")
    parser.add_argument("--out", help="write markdown report to this file (default: stdout)")
    parser.add_argument("--no-seed", action="store_true", help="skip DB seeding in fixture mode")
    parser.add_argument("--timeout", type=float, default=None, help="per-search timeout seconds")
    args = parser.parse_args()

    month = date.fromisoformat(f"{args.month}-01") if args.month else default_month()
    timeout = args.timeout or (60.0 if args.fixture else 300.0)

    if args.fixture and not args.no_seed:
        seed(month)

    rows = run_matrix(args.base_url, month, timeout)
    report = render_report(rows, "fixture" if args.fixture else "live", month)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"report written to {args.out}", file=sys.stderr)
    else:
        print(report)

    if args.fixture:
        failures = assert_fixture_baseline(rows)
        if failures:
            print("\nBASELINE FAILURES:", file=sys.stderr)
            for failure in failures:
                print(f"  - {failure}", file=sys.stderr)
            return 1
        print("baseline expectations: all green", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
