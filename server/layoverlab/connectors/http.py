"""Polite HTTP client: per-domain min interval + jitter, retries with backoff (honoring
Retry-After), per-domain circuit breaker, on-disk JSON cache, kill-switch, structured
per-request log lines."""

import asyncio
import hashlib
import json
import logging
import random
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from layoverlab.connectors.base import ConnectorDisabled, ConnectorError
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

USER_AGENT = "LayoverLab/0.1 (personal research project; low-volume; contact: local)"

MAX_TRIES = 3
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 30.0
RETRYABLE_STATUSES = (429, 500, 502, 503, 504)
BREAKER_THRESHOLD = 5

_domain_locks: dict[str, asyncio.Lock] = {}
_domain_last: dict[str, float] = {}


class CircuitBreaker:
    """Per-domain breaker: opens after N consecutive failures, half-open probe after cooldown."""

    def __init__(self) -> None:
        self.failures: dict[str, int] = {}
        self.opened_at: dict[str, float] = {}

    def check(self, domain: str, cooldown_s: float) -> None:
        opened = self.opened_at.get(domain)
        if opened is None:
            return
        if time.monotonic() - opened >= cooldown_s:
            return  # half-open: allow a probe request through
        raise ConnectorError(f"circuit breaker open for {domain}")

    def record_success(self, domain: str) -> None:
        self.failures.pop(domain, None)
        self.opened_at.pop(domain, None)

    def record_failure(self, domain: str) -> None:
        count = self.failures.get(domain, 0) + 1
        self.failures[domain] = count
        if count >= BREAKER_THRESHOLD:
            self.opened_at[domain] = time.monotonic()

    def is_open(self, domain: str) -> bool:
        return domain in self.opened_at


_breaker = CircuitBreaker()


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class PoliteClient:
    def __init__(self, cache_ttl_s: int = 6 * 3600) -> None:
        self.settings = get_settings()
        self.cache_ttl_s = cache_ttl_s
        self.cache_dir = Path(self.settings.http_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url: str, params: dict | None) -> Path:
        key = hashlib.sha256(f"{url}|{json.dumps(params or {}, sort_keys=True)}".encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _cache_get(self, url: str, params: dict | None):
        path = self._cache_path(url, params)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if time.time() - entry.get("fetched_at", 0) > self.cache_ttl_s:
            return None
        return entry.get("body")

    def _cache_put(self, url: str, params: dict | None, body) -> None:
        path = self._cache_path(url, params)
        try:
            path.write_text(json.dumps({"fetched_at": time.time(), "body": body}), encoding="utf-8")
        except OSError:
            log.warning("http cache write failed for %s", url)

    async def _respect_domain_interval(self, url: str) -> None:
        domain = urlparse(url).netloc
        lock = _domain_locks.setdefault(domain, asyncio.Lock())
        min_interval = self.settings.crawl_min_interval_s
        async with lock:
            elapsed = time.monotonic() - _domain_last.get(domain, 0.0)
            wait = min_interval - elapsed + random.uniform(0.1, 0.8)
            if wait > 0:
                await asyncio.sleep(wait)
            _domain_last[domain] = time.monotonic()

    async def _send_once(
        self,
        method: str,
        url: str,
        params: dict | None,
        headers: dict,
        json_body: dict | None,
        form_data: dict | None,
    ) -> httpx.Response:
        await self._respect_domain_interval(url)
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.request(
                    method, url, params=params, headers=headers, json=json_body, data=form_data
                )
        except httpx.HTTPError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            log.info(
                "http_request domain=%s method=%s status=network_error cache_hit=false latency_ms=%d",
                urlparse(url).netloc, method, latency_ms,
            )
            raise ConnectorError(f"network error: {exc}") from exc
        latency_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "http_request domain=%s method=%s status=%d cache_hit=false latency_ms=%d",
            urlparse(url).netloc, method, resp.status_code, latency_ms,
        )
        return resp

    async def _request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        json_body: dict | None = None,
        form_data: dict | None = None,
    ) -> httpx.Response:
        if not self.settings.crawl_enabled:
            raise ConnectorDisabled("CRAWL_ENABLED=false")
        domain = urlparse(url).netloc
        req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if headers:
            req_headers.update(headers)
        last_error: ConnectorError | None = None
        for attempt in range(1, MAX_TRIES + 1):
            _breaker.check(domain, self.settings.crawl_breaker_cooldown_s)
            try:
                resp = await self._send_once(method, url, params, req_headers, json_body, form_data)
            except ConnectorError as exc:
                _breaker.record_failure(domain)
                last_error = exc
                if attempt < MAX_TRIES:
                    await asyncio.sleep(self._backoff_delay(attempt))
                continue
            if resp.status_code in RETRYABLE_STATUSES:
                _breaker.record_failure(domain)
                last_error = ConnectorError(f"retryable status {resp.status_code} for {url}")
                if attempt < MAX_TRIES:
                    retry_after = _retry_after_seconds(resp)
                    delay = retry_after if retry_after is not None else self._backoff_delay(attempt)
                    await asyncio.sleep(min(delay, BACKOFF_MAX_S))
                continue
            if resp.status_code >= 400:
                _breaker.record_failure(domain)
                raise ConnectorError(f"status {resp.status_code} for {url}: {resp.text[:200]}")
            _breaker.record_success(domain)
            return resp
        raise last_error or ConnectorError(f"request failed for {url}")

    @staticmethod
    def _backoff_delay(attempt: int) -> float:
        return min(BACKOFF_BASE_S * (2 ** (attempt - 1)), BACKOFF_MAX_S) + random.uniform(0.0, 1.0)

    async def get_json(self, url: str, params: dict | None = None, headers: dict | None = None):
        cached = self._cache_get(url, params)
        if cached is not None:
            log.info(
                "http_request domain=%s method=GET status=cached cache_hit=true latency_ms=0",
                urlparse(url).netloc,
            )
            return cached
        resp = await self._request("GET", url, params=params, headers=headers)
        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise ConnectorError(f"non-JSON response from {url}") from exc
        self._cache_put(url, params, body)
        return body

    async def get_text(self, url: str, params: dict | None = None, headers: dict | None = None) -> str:
        cached = self._cache_get(url, params)
        if isinstance(cached, str):
            log.info(
                "http_request domain=%s method=GET status=cached cache_hit=true latency_ms=0",
                urlparse(url).netloc,
            )
            return cached
        resp = await self._request("GET", url, params=params, headers=headers)
        body = resp.text
        self._cache_put(url, params, body)
        return body

    async def post_json(
        self,
        url: str,
        json_body: dict | None = None,
        form_data: dict | None = None,
        headers: dict | None = None,
        cache: bool = True,
    ):
        cache_key = {"__post__": json_body or form_data or {}}
        if cache:
            cached = self._cache_get(url, cache_key)
            if cached is not None:
                log.info(
                    "http_request domain=%s method=POST status=cached cache_hit=true latency_ms=0",
                    urlparse(url).netloc,
                )
                return cached
        resp = await self._request("POST", url, headers=headers, json_body=json_body, form_data=form_data)
        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise ConnectorError(f"non-JSON response from {url}") from exc
        if cache:
            self._cache_put(url, cache_key, body)
        return body
