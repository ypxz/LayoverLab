# LayoverLab E2E, load & benchmark suite

Deterministic end-to-end tests against a local **fixture-connector stack** (SQLite + synthetic
fares, zero live HTTP). Owned by agent H (QA).

## Playwright E2E

```bash
cd e2e
npm install
npx playwright install --with-deps chromium
npx playwright test           # starts API (:8000) + web (:3000) automatically via webServer
npx playwright show-report
```

The config's `webServer` runs `scripts/start-api.sh` (alembic migrate → seed fixture fares →
uvicorn with `FIXTURE_CONNECTOR=true`, `CRAWL_ENABLED=false`, `RATE_LIMIT_ENABLED=false`) and
`scripts/start-web.sh` (production `next build` + `next start`). Both are reused if already
running locally (`reuseExistingServer`), so you can keep a stack up between runs.

- `E2E_MONTH=YYYY-MM` pins the search month (default: +2 months, same as route_matrix).
- `E2E_PYTHON=/path/to/python` overrides the server interpreter (default `server/.venv/bin/python`,
  falling back to `python`).

Scenarios: stopover-beats-direct with verified badge, filters narrowing, share → permalink
roundtrip, API-down friendly error + retry, mobile viewport smoke, and cold-route SSE `update`
events improving the visible list (fresh fares injected mid-stream via `scripts/inject_fares.py`).

## Load test (k6)

20 VUs for 60s against `POST /api/search`. Thresholds: error rate < 1%, p95 first-event
latency (TTFB proxy) < 2s.

```bash
bash e2e/scripts/start-api.sh &          # fixture stack with rate limiting disabled
k6 run e2e/load/search_sse.js            # install: https://k6.io/docs/get-started/installation/
```

In CI this runs only on manual dispatch of the `nightly` workflow (never on PRs).

## Engine benchmarks

```bash
cd server && . .venv/bin/activate
python benchmarks/bench_engine.py --sizes 10000,50000,200000 --searches 20 \
    --assert-p95 50000:1200 --out benchmarks/results.json
```

Seeded synthetic hub-and-spoke slices; reports p50/p95/max per-search latency and peak RSS.
The nightly CI job fails when p95 @ 50k fares exceeds 1200ms. Baseline numbers are committed
at `server/benchmarks/results.json`.
