"""Prometheus metrics on a dedicated registry (safe across repeated app imports)."""

from fastapi import APIRouter, HTTPException, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from layoverlab.settings import get_settings

registry = CollectorRegistry()

http_requests_total = Counter(
    "layoverlab_http_requests_total",
    "HTTP requests by path/method/status",
    ["path", "method", "status"],
    registry=registry,
)
http_request_duration_seconds = Histogram(
    "layoverlab_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["path"],
    registry=registry,
)
sse_searches_started_total = Counter(
    "layoverlab_sse_searches_started_total",
    "SSE search streams started",
    registry=registry,
)
sse_searches_completed_total = Counter(
    "layoverlab_sse_searches_completed_total",
    "SSE search streams completed",
    registry=registry,
)
crawler_jobs = Gauge(
    "layoverlab_crawler_jobs",
    "Crawler jobs by status (from crawler stats when available)",
    ["status"],
    registry=registry,
)

router = APIRouter()


def _refresh_crawler_gauge() -> None:
    try:
        from layoverlab.crawler.stats import get_stats  # provided by agent D
    except ImportError:
        return
    try:
        stats = get_stats()
    except Exception:  # noqa: BLE001 - metrics must never fail the endpoint
        return
    jobs = stats.get("jobs") if isinstance(stats, dict) else None
    if isinstance(jobs, dict):
        for status, count in jobs.items():
            if isinstance(count, (int, float)):
                crawler_jobs.labels(status=str(status)).set(count)


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    if not get_settings().metrics_enabled:
        raise HTTPException(status_code=404, detail="not found")
    _refresh_crawler_gauge()
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
