"""Pure-ASGI middleware: X-Request-ID, access logging, metrics, rate limiting, error envelope."""

import json
import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from layoverlab.api import metrics
from layoverlab.api.logging_config import ACCESS_LOGGER
from layoverlab.api.ratelimit import limiter
from layoverlab.settings import get_settings

access_log = logging.getLogger(ACCESS_LOGGER)

REQUEST_ID_HEADER = b"x-request-id"


def _client_ip(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            return value.decode().split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


def _route_path(scope: Scope) -> str:
    route = scope.get("route")
    return getattr(route, "path", None) or scope.get("path", "")


class RequestContextMiddleware:
    """Adds X-Request-ID, logs one JSON line per request, records metrics, envelopes 500s."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = message.setdefault("headers", [])
                headers.append((REQUEST_ID_HEADER, request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            access_log.exception(
                "unhandled error",
                extra={"request_id": request_id, "method": scope["method"], "path": scope["path"]},
            )
            body = json.dumps(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Internal server error",
                        "request_id": request_id,
                    }
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (REQUEST_ID_HEADER, request_id.encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
        finally:
            elapsed = time.perf_counter() - start
            status = status_holder["status"]
            path = scope["path"]
            access_log.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "path": path,
                    "status": status,
                    "ms": round(elapsed * 1000, 2),
                },
            )
            route_path = _route_path(scope)
            metrics.http_requests_total.labels(
                path=route_path, method=scope["method"], status=str(status)
            ).inc()
            metrics.http_request_duration_seconds.labels(path=route_path).observe(elapsed)


class RateLimitMiddleware:
    """In-process token bucket per client IP; 429 with Retry-After when exhausted."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = get_settings()
        if scope["type"] != "http" or not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path == "/api/search":
            name, per_min = "search", settings.rate_search_per_min
        else:
            name, per_min = "default", settings.rate_default_per_min

        allowed, retry_after = limiter.allow(_client_ip(scope), name, per_min)
        if allowed:
            await self.app(scope, receive, send)
            return

        request_id = scope.get("state", {}).get("request_id", "")
        body = json.dumps(
            {
                "error": {
                    "code": "rate_limited",
                    "message": "Too many requests",
                    "request_id": request_id,
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(max(1, round(retry_after))).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
