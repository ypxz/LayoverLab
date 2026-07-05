# LayoverLab — Frozen Contracts

Binding interfaces between all components. Changes require orchestrator approval — never diverge silently.

## Repo layout

```
LayoverLab/
  docker-compose.yml          # postgres, api, worker, web
  .env.example
  docs/PLAN.md  docs/CONTRACTS.md
  server/                     # one Python package: layoverlab
    pyproject.toml
    layoverlab/
      db/         # models, alembic migrations, session
      seeds/      # airports, clusters, ground corridors loaders + data
      connectors/ # base.py + ryanair.py + travelpayouts.py + google_flights.py
      crawler/    # scheduler, prioritizer, politeness
      engine/     # graph build + search + verify
      api/        # FastAPI app, routers, schemas
    tests/
  web/                        # Next.js app
```

## DB schema (`server/layoverlab/db/models.py`)

- `airports(iata PK, name, city, country_code, lat, lon, cluster_id?)`
- `airport_clusters(id PK, name)`
- `ground_links(id PK, from_iata, to_iata, mode, minutes, price_cents, currency)`
- `routes(origin, dest, carriers, frequency_score float, last_seen)` PK(origin,dest)
- `fares(origin, dest, dep_date, min_price_cents, currency, source, deep_link?, fetched_at, expires_at)` PK(origin,dest,dep_date,source)
- `crawl_jobs(id PK, connector, origin, dest, month, priority int, status, run_after, last_error?)`
- `itineraries(id UUID PK, created_at, payload JSONB)`

## Connector interface (`connectors/base.py`)

```python
class DayFare(TypedDict):
    origin: str; dest: str; dep_date: date
    price_cents: int; currency: str; deep_link: str | None

class Connector(Protocol):
    name: str
    async def fetch_month(self, origin: str, dest: str, month: date) -> list[DayFare]: ...
    async def routes_from(self, origin: str) -> list[str]: ...   # may return []
    async def verify_day(self, origin: str, dest: str, dep_date: date) -> DayFare | None: ...
```

Implemented: `ryanair` (no key), `travelpayouts` (free token), `google_flights` (verify only, `GF_ENABLED`).
Optional future drop-ins (same interface): `easyjet`, `wizzair`, `amadeus`, `kiwi_tequila`, `flightapi`, `ignav`, `scrappa_gf`.

## Engine interface (`engine/search.py`)

```python
class SearchParams(BaseModel):
    origin: str; dest: str
    date_from: date; date_to: date          # window; exact date => same value
    round_trip: bool = False
    trip_min_days: int | None = None; trip_max_days: int | None = None
    stop_min_hours: int = 4; stop_max_days: int = 7
    max_stops: int = 3; top_k: int = 10

class Leg(BaseModel):
    origin: str; dest: str; dep_date: date; mode: str   # "flight" | "ground"
    price_cents: int; currency: str; source: str; deep_link: str | None
    fetched_at: datetime

class Itinerary(BaseModel):
    id: str | None = None
    legs: list[Leg]; total_cents: int; currency: str
    stopovers: list[Stopover]     # {iata, nights}
    warnings: list[str]
    verified: bool

def search(params: SearchParams) -> list[Itinerary]
async def verify_top(itins: list[Itinerary], n: int = 5) -> list[Itinerary]
```

## API (FastAPI, prefix `/api`)

- `GET  /api/health` → `{status:"ok"}` (extended additively: `worker: {alive: bool|null, last_heartbeat_age_s: number|null}`)
- `GET  /api/airports?q=` → `[{iata, name, city, country_code}]`
- `POST /api/search` body=SearchParams → **SSE**: `candidates` → `verified` → zero or more `update` (same payload shape as `candidates`, emitted while a cold route's fare cache fills and the result set improves) → `done` with `meta` object `{"crawl_pending": bool, "searched_pairs_covered": bool}` (extended additively: `"worker_alive": bool|null`, `"zero_results_reason": null | "no_coverage" | "crawl_pending" | "crawl_disabled" | "worker_down" | "sources_erroring"` — set only when the stream ends with zero results)
- `POST /api/itineraries` body=Itinerary → `{id}`
- `GET  /api/r/{id}` → Itinerary (re-verified on read)

Web generates its types from the committed `web/openapi.json`.

## Conventions

- Money: integer cents + ISO currency (default EUR, convert at ingest). Dates: UTC ISO. Airports: uppercase IATA.
- Engine plans at day granularity; real flight times resolved in verification only.
- Self-transfer buffers: warn <3h same airport, <6h cross-airport/ground.
- Crawler politeness: per-domain min interval ≥2s + jitter, retries w/ backoff, on-disk cache, `CRAWL_ENABLED` kill-switch.
- No secrets in code; every env var documented in `.env.example`.
