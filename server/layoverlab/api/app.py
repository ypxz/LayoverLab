from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from layoverlab.api.admin import router as admin_router
from layoverlab.api.logging_config import setup_json_logging
from layoverlab.api.metrics import router as metrics_router
from layoverlab.api.middleware import RateLimitMiddleware, RequestContextMiddleware
from layoverlab.api.routes import router
from layoverlab.connectors.base import load_default_connectors
from layoverlab.settings import get_settings

try:
    _version = version("layoverlab")
except PackageNotFoundError:
    _version = "0.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_json_logging()
    load_default_connectors()
    yield


app = FastAPI(
    title="LayoverLab API",
    version=_version,
    description="Creative cheapest-route flight finder: cached candidates, live verification, "
    "streaming updates.",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "search", "description": "Streaming route search (SSE)."},
        {"name": "airports", "description": "Airport autocomplete."},
        {"name": "itineraries", "description": "Itinerary permalinks."},
        {"name": "ops", "description": "Health and operational endpoints."},
    ],
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().api_cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
