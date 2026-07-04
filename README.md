# LayoverLab

**The cheapest way from A to B is sometimes three days in a country you have never heard of.**

LayoverLab finds creative cheapest routes between two airports in a flexible date window — routes no normal flight search will show you:

- **Multi-day stopovers** — fly BER→BKK via 3 nights in Kuala Lumpur for a fraction of the direct fare
- **Self-transfer combos** — separate one-way tickets across different airlines, stitched together
- **Nearby-airport swaps** — arrive at Stansted when you searched Gatwick, if it saves real money
- **Ground corridors** — a €29 train from Cologne to Brussels can unlock a €25 flight
- **Flexible dates** — search a whole month; the engine picks the cheapest day combination

Results stream in live: instant candidates from the fare cache, then the top routes are **re-verified against live prices** before you book. Every itinerary gets honest warnings (self-transfer risk, baggage re-check, visa hints) and a shareable permalink.

> **Status: v0.1 fully working.** All core systems shipped and smoke-tested with live data (real Ryanair fares, end-to-end search, streaming UI). See [Roadmap](#roadmap--agent-handoff) for what's next.

---

## How it works

```
                ┌─────────────────────────── server (Python 3.12) ──────────────────────────┐
                │                                                                            │
  Ryanair API ──┤  connectors/          crawler/              engine/            api/       │
  Travelpayouts ┤  polite HTTP client   priority job queue    time-expanded      FastAPI    │
  (+ your next  │  rate-limit, cache,   demand-driven:        (airport, day)     SSE stream │──▶ web (Next.js 14)
   source here) │  kill-switch          searches enqueue      graph, Dijkstra,   permalinks │    streaming results,
                │                       direct+cluster+hub    top-K, warnings                │    timeline cards,
                │                              │                    ▲                        │    share links
                │                              ▼                    │                        │
                │                    Postgres 16 (or SQLite): fares, airports, clusters,     │
                │                    ground_links, routes, crawl_jobs, itinerary snapshots   │
                └────────────────────────────────────────────────────────────────────────────┘
```

1. **Crawl** — a worker politely fetches month-granularity cheapest-per-day fares from free sources into a fare cache. Crawling is *demand-driven*: every user search enqueues jobs for the direct pair, cluster siblings and top hub connections.
2. **Search** — the engine loads a fare slice into memory, builds a time-expanded graph over `(airport, day)` nodes (flight edges, multi-day stay edges, ground/cluster edges) and runs a cost-first Dijkstra for the top-K distinct itineraries. Round trips combine outbound+inbound under stay-length constraints.
3. **Verify** — the best candidates are re-checked live per leg, re-priced, buffer-checked and re-ranked before display. Cached-only results are clearly labeled.

Deep dives: [`docs/PLAN.md`](docs/PLAN.md) (architecture decisions) · [`docs/CONTRACTS.md`](docs/CONTRACTS.md) (frozen interfaces — DB schema, connector protocol, engine dataclasses, API shapes).

---

## Quick start (Docker)

```bash
cp .env.example .env               # optionally add TRAVELPAYOUTS_TOKEN (free)
docker compose up --build
# db  -> localhost:5433 | api -> http://localhost:8000/api/health | web -> http://localhost:3000

docker compose exec api python -m layoverlab.seeds.load_all         # seed airports/clusters/routes (once)
docker compose exec api python scripts/crawl_once.py BER ALC 2026-08  # fill some real fares
```

Open http://localhost:3000, search the route+month you crawled, watch results stream in.

## Quick start (no Docker — SQLite mode)

Works on a bare machine with Python 3.12 + Node 18+. Windows PowerShell shown; use `export`/`source` on Unix.

```powershell
# server
cd server
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:DATABASE_URL = "sqlite:///layoverlab.sqlite3"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m layoverlab.seeds.load_all
.\.venv\Scripts\python.exe scripts\crawl_once.py BER ALC 2026-08
.\.venv\Scripts\python.exe -m uvicorn layoverlab.api.app:app --port 8000   # terminal 1
.\.venv\Scripts\python.exe -m layoverlab.crawler.run                       # terminal 2 (optional worker)

# web (terminal 3)
cd web
npm install
npm run dev        # -> http://localhost:3000
```

Windows notes: if `npm` is blocked by execution policy use `npm.cmd`; if Node is not on PATH prepend it for the session: `$env:Path = "C:\Program Files\nodejs;$env:Path"`.

## Configuration

All config is environment variables — copy `.env.example` to `.env` and edit. **Never commit `.env`** (it is gitignored).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | postgres on `localhost:5433` | SQLAlchemy URL; SQLite works for single-worker dev |
| `CRAWL_ENABLED` | `true` | Global kill-switch for all outbound crawling |
| `CRAWL_MIN_INTERVAL_S` | `2.0` | Per-domain minimum seconds between requests |
| `CRAWL_BREAKER_COOLDOWN_S` | `300` | Per-domain circuit breaker cooldown before a half-open probe |
| `HTTP_CACHE_DIR` | `.cache/http` | On-disk response cache (avoids duplicate hits) |
| `TRAVELPAYOUTS_TOKEN` | *(empty = disabled)* | Free token → all-airline cached fares ([travelpayouts.com](https://www.travelpayouts.com), ~5-minute signup, biggest coverage win) |
| `TEQUILA_API_KEY` | *(empty = disabled)* | Kiwi Tequila free tier — all airlines + self-transfer pricing ([tequila.kiwi.com](https://tequila.kiwi.com)) |
| `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` | *(empty = disabled)* | Amadeus Self-Service free test quota — exact verification prices ([developers.amadeus.com](https://developers.amadeus.com)) |
| `WIZZ_ENABLED` | `true` | Wizz Air public timetable connector (no key) |
| `EASYJET_ENABLED` | `true` | easyJet lowest-daily-fares connector (no key) |
| `GF_ENABLED` | `false` | Google Flights verification connector (stub) |
| `FARE_TTL_HOURS` | `48` | Cached fares expire after this |
| `API_CORS_ORIGINS` | `http://localhost:3000` | Allowed frontend origins |
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8000/api` | API base URL for the web app |

## Tests

```bash
cd server && pytest -q       # 20 tests: engine scenarios, connectors (recorded fixtures), crawler, API SSE, seeds
cd web && npm test           # vitest: SSE parser, formatting
```

CI (`.github/workflows/ci.yml`) runs ruff + pytest + vitest + `next build` on every push/PR.

## Project layout

```
server/
  layoverlab/
    api/          FastAPI app, SSE search endpoint, permalinks
    connectors/   fare sources: ryanair, travelpayouts, google_flights (stub), polite HTTP client
    crawler/      job queue worker, demand-driven prioritizer
    db/           SQLAlchemy models, session, Alembic migrations
    engine/       fare-slice graph, top-K search, round-trips, warnings, live verification
    seeds/        airports/clusters/ground-corridors/routes loaders + curated CSVs
  scripts/        crawl_once.py (manual smoke crawl)
  tests/
web/
  src/app/        pages: search+results (SSE streaming), /r/[id] permalinks
  src/components/ SearchForm, AirportInput, RouteCard (timeline, warnings, share)
  src/lib/        typed API client, SSE parser, formatting
docs/             PLAN (architecture), CONTRACTS (frozen interfaces)
```

## Roadmap (v0.2)

v0.1 is complete and working end-to-end. v0.2 focuses on, in priority order:

1. **Source coverage** — integrate all good fare APIs (Travelpayouts all-airline data, Amadeus, Kiwi Tequila, Wizz Air, easyJet) so every pair is priceable and the cheapest combination is never missed
2. **Time-to-results** — direct-pair-first crawling, per-domain parallelism, live-updating result streams while fresh fares land
3. **Proof on diverse routes** — an automated route-matrix reporting quality + latency across route classes
4. **Verification with real flight times, engine v2 (Pareto ranking, diversity), UI polish, production deployment**

## Legal & fair-use

LayoverLab uses undocumented public endpoints (e.g. Ryanair's fare-finder) **politely**: low request rates with jitter, aggressive caching, per-domain throttling and a global kill-switch (`CRAWL_ENABLED=false`). Intended for personal, non-commercial use. Prices are estimates until marked verified — always confirm the final price on the airline's booking site. Self-transfer itineraries are separate contracts: missed connections are your own risk.
