# LayoverLab — Creative Cheapest-Route Flight Finder

Build a local-first web app that finds the absolute cheapest way between two airports in a flexible date window — including multi-day stopovers in random countries, self-transfer ticket combos, nearby-airport swaps and curated ground corridors — powered by a continuously crawled fare cache (free sources) plus live verification of top results.

## Confirmed Decisions (from Q&A)

| Topic | Decision |
|---|---|
| Data sources | All of: free/official APIs, LCC direct APIs, Google Flights scraping, public route data; Skyscanner scraping deferred (hardest anti-bot) |
| Execution model | Hybrid: cached fare graph → instant candidates → live re-verify top ~5 |
| Route types | Self-transfer combos + nearby-airport clusters + curated ground corridors (~50 train/bus links) |
| Stopovers | User-configurable (min/max stopover duration, max stops) |
| Scope v1 | Departures from Europe, destinations worldwide |
| Trip types | One-way + month-range (core), exact dates, round-trip |
| Budget / Infra | ~0€, local-first via docker-compose on your PC |
| Legal stance | Gray-zone polite scraping OK |
| Booking | Deep links only (airline site / Google Flights per leg) |
| Stack | My pick: Next.js + Python (see below) |
| Features | Pure search, self-transfer warnings, shareable permalinks — no accounts |
| Ambition | Personal tool / portfolio |

## Research Findings (your follow-up questions)

**Where Skyscanner gets its data:** Direct commercial partnerships with ~1,200 airlines and OTAs (direct airline APIs/NDC feeds, not primarily GDS). Partners hand over price feeds *for free* because Skyscanner sends them paid referral traffic (CPC model). → Not replicable without being an aggregator with traffic. **Closest free equivalent:** the Travelpayouts/Aviasales **Data API** — free with a token, serves cached prices from real Aviasales user searches (last ~48h), incl. month-matrix and price-calendar endpoints. Caveat: cache skews toward RU/CIS-market searches, so it's a *supplement*, not the backbone.

**Flightradar24-style route data:** FR24 has no free API. Free equivalents we'll use instead:
- **OurAirports / OpenFlights** — airport master data + route topology (free CSV dumps)
- **Airline network APIs** — Ryanair/Wizz publish their live route networks via their public JSON endpoints
- **OpenSky Network** — free REST API (research use) with live/historical ADS-B data → optional route-frequency weighting for crawl prioritization

**Confirmed free fare sources (no key or free key):**
- **Ryanair** `services-api.ryanair.com/farfnd/v4` — cheapest fare **per day for a whole month in one call**, round-trip search, route network. No API key. This is the crown jewel for a Europe-departure MVP.
- **Wizz Air / easyJet** — similar unofficial JSON endpoints (more fragile, phase 5)
- **Travelpayouts Data API** — cached market-wide prices (free token)
- **Amadeus Self-Service** — free monthly production quota, structured data; used as verifier/gap-filler
- **Google Flights** — no official API; scrape via `fast-flights`-style protobuf requests (no browser needed), Playwright fallback. Low volume only: verification + full-service-carrier gaps.
- **Kiwi Tequila** — natively returns self-transfer itineraries; partner approval uncertain → opportunistic, apply and integrate if accepted.

## System Architecture

```
┌─────────────┐   ┌──────────────────────────────────────────────┐
│  Next.js UI │──▶│ FastAPI                                       │
│  (search,   │   │  /airports  /search (SSE progress)  /r/{id}  │
│  results,   │   └──────┬───────────────────────┬───────────────┘
│  permalink) │          │ reads                 │ on-demand
└─────────────┘   ┌──────▼───────┐    ┌──────────▼──────────┐
                  │  Postgres    │    │  Search Engine (py)  │
                  │  fares cache │───▶│  time-expanded graph │
                  │  topology    │    │  top-K cheapest      │
                  │  itineraries │    │  + live verification │
                  └──────▲───────┘    └──────────▲──────────┘
                         │ writes                │ live checks
                  ┌──────┴────────────────────────┴──────┐
                  │  Worker (py): connector framework     │
                  │  Ryanair · Travelpayouts · GoogleFl.  │
                  │  scheduler + politeness + prioritizer │
                  └───────────────────────────────────────┘
```

**Stack:** Next.js 14+ (TS, Tailwind, shadcn/ui) · FastAPI + Python 3.12 worker (httpx/curl_cffi, APScheduler, Playwright fallback) · Postgres (docker named volume — avoid OneDrive bind-mount issues) · docker-compose. No Redis/Celery at this scale — Postgres-backed job table.

### Components

1. **Topology seed** — airports (OurAirports), airport clusters (LON = LHR/LGW/STN/LTN…, FRA/HHN, MIL = MXP/LIN/BGY…), ~50 curated ground corridors (Köln↔Brüssel, Wien↔Bratislava…) as static seed data with rough price/duration, route graph from airline network endpoints + OpenFlights.
2. **Crawler worker** — pluggable `Connector` interface (`fetch_month(origin, dest, month) -> [DayFare]`). Politeness layer: per-domain rate limits, jitter, retries, response caching, kill-switch per connector. Prioritizer: hot routes (popular + recently searched by you) daily, cold routes weekly; user searches enqueue crawl jobs for missing coverage (feedback loop).
3. **Fare cache** — `fares(origin, dest, date, min_price, currency, source, deep_link, fetched_at, expires_at)`. Day granularity keeps it small: cheapest price per O-D-day.
4. **Search engine** — time-expanded graph over `(airport, day)` nodes:
   - Edges: cached day-fares, stay edges (stopover length within user min/max), intra-cluster + ground-corridor transfer edges, virtual source across the month range.
   - Multi-criteria label-correcting Dijkstra with dominance pruning (price, time, #legs) → top-K itineraries; constraints: max stops, stopover bounds.
   - Round-trip = outbound + inbound searches combined under trip-length constraint.
   - **Verification pass:** top ~5 candidates get live-checked leg by leg (Ryanair API, Google Flights); resolves actual flight times, validates self-transfer buffers (default ≥3h same airport / ≥6h cross-airport), re-ranks, tags each result `verified now` vs `cached Xh ago`.
5. **API** — `POST /search` (origin, dest, dateMode exact|month-range, roundTrip, stopoverMin/Max, maxStops) with SSE progress (candidates instantly, verification streaming in), `GET /airports` autocomplete, `GET /r/{id}` permalinks (re-verifies on open).
6. **Frontend** — search form with stopover sliders; results as visual route timelines (legs + stopover-day badges, per-leg price breakdown, freshness badge, savings vs. direct); route detail with per-leg deep links (airline booking URL or Google Flights link) and **self-transfer warnings**: separate-tickets risk, baggage re-check, connection buffer, static visa-hint table per layover country (with disclaimer).

## Data Model (core tables)

`airports` · `airport_clusters` · `ground_links` · `routes` (topology + frequency score) · `fares` (the cache) · `crawl_jobs` · `itineraries` (permalink JSON snapshots)

## Phased Roadmap

| Phase | Deliverable |
|---|---|
| **0. Scaffold** | Monorepo (`web/`, `server/` with api+worker+engine as one Python package), docker-compose (postgres, api, worker, web), seed data loaders, README, `.env` for tokens |
| **1. Data in** | Connector framework + politeness layer; **Ryanair** + **Travelpayouts** connectors; scheduler + prioritizer; fares flowing into Postgres; small CLI to inspect coverage |
| **2. Engine** | Graph builder + top-K search with unit tests on synthetic fare fixtures (known-cheapest scenarios incl. multi-day stopovers, clusters, ground links); `POST /search` + `GET /airports` |
| **3. UI** | Next.js search page, streaming results, route timeline viz, detail view with warnings + deep links, permalinks |
| **4. Verify** | Live verification pass (Ryanair live + Google Flights via fast-flights-style requests), freshness badges, buffer validation |
| **5. Stretch** | Wizz/easyJet connectors, Amadeus verifier, OpenSky frequency weighting, Kiwi Tequila (if approved), round-trip polish, Skyscanner endpoint experiments |

## Risks & Mitigations

- **Unofficial APIs break** → connectors isolated, health-checked, disabled individually; engine works with whatever sources are up.
- **Travelpayouts RU-market skew** → treat as supplemental; Ryanair/LCC data is the backbone for Europe.
- **Google Flights anti-bot** → tiny request volume (verification only), request-level scraping before Playwright, easy to disable.
- **Stale cache misleads** → verification pass + visible freshness on every result.
- **Docker on Windows/OneDrive** → Postgres on a named volume, code mounted read-only or run outside OneDrive if file-watching hurts.
- **Day-granularity cache hides bad connections** → verification resolves real times and enforces buffers before showing final prices.

## Testing

- Engine: deterministic unit tests on synthetic graphs (pytest).
- Connectors: contract tests against recorded JSON fixtures.
- UI: Playwright smoke test (search → results → detail) in phase 3/4.
