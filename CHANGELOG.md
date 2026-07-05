# Changelog

## v0.2 — 2026-07-05

Eight parallel agent workstreams merged across three waves, each gated on the route-matrix harness, the full test suite, and a live full-stack smoke.

### Wave 1
- **Connectors (B, PR #4):** Travelpayouts (all-airline cached fares), Wizz Air and easyJet public endpoints, Kiwi Tequila and Amadeus scaffolds (disabled by default, graceful degradation), source coverage registry (`connectors/coverage.py`), ECB FX conversion, per-source enablement via env.
- **Smart crawler (D, PR #1):** per-domain request budgets, demand-weighted refresh scheduler, retry/dead-letter job lifecycle, crawl notifications so searches wake as soon as a cold pair's fares land, crawler stats.
- **Platform (G, PR #3):** SSE `update` event while cold routes fill, `done` meta (`crawl_pending`, `searched_pairs_covered`), admin endpoints (`X-Admin-Token`), Prometheus metrics, per-IP rate limiting, production Docker images.
- **QA phase 1 (H, PR #2):** deterministic fixture connector + `scripts/route_matrix.py` harness exercising 8 route classes (cold/warm) — the gate for every wave.

### Wave 2
- **Verification (C, PR #5):** Google Flights times for top candidates, real-time connection-buffer enforcement (`SELF_TRANSFER_MIN_H`), price-drift notes, `VERIFY_TOP_K` verify budget.
- **UI (E, PR #7):** full product overhaul — shadcn design system, live search status strip (fetching / long-running / error + retry), "found cheaper routes" update notices, route detail page, honest cached-vs-verified labeling, landing page. 36 unit tests.
- **Data (F, PR #6):** 49 worldwide airport clusters, 118 ground corridors, IANA timezone per airport (`airports.tz`), visa hints v2, optional fresher route topology (`ROUTES_SOURCE=jonty`).

### Wave 3
- **Engine v2 (A, PR #8):** Pareto multi-criteria search (`sort=cheapest|fastest|best`), result diversity, O(n log n) round-trip pairing fixing the round-trip zero-results bug, fare-expiry filtering, EUR-only guard, perf benchmark suite.
- **QA phase 2 (H, PR #9):** Playwright E2E suite (6 specs incl. mid-stream SSE update), engine benchmarks with CI-gated p95 budgets, k6 load test, chaos/degradation tests, coverage reporting, nightly CI.

### Orchestrator fixes (from data-analytics review + QA load test)
- Ryanair connector now converts non-EUR fares to EUR cents via ECB FX (P0 correctness).
- Concurrent-search enqueue race fixed: partial unique index on active crawl jobs + tolerant upsert (migration 0004) — previously duplicate jobs could permanently break `/api/search` for a pair.

## v0.1

Initial working system: Ryanair connector, polite crawler, time-expanded-graph engine, SSE search API, Next.js UI, SQLite/Postgres migrations.
