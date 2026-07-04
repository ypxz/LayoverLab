"""Polite HTTP client: per-domain min interval + jitter, retries, on-disk JSON cache, kill-switch."""

import asyncio
import hashlib
import json
import logging
import random
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from layoverlab.connectors.base import ConnectorDisabled, ConnectorError
from layoverlab.settings import get_settings

log = logging.getLogger(__name__)

USER_AGENT = "LayoverLab/0.1 (personal research project; low-volume; contact: local)"

_domain_locks: dict[str, asyncio.Lock] = {}
_domain_last: dict[str, float] = {}


class PoliteClient:
    def __init__(self, cache_ttl_s: int = 6 * 3600) -> None:
        self.settings = get_settings()
        self.cache_ttl_s = cache_ttl_s
        self.cache_dir = Path(self.settings.http_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url: str, params: dict | None) -> Path:
        key = hashlib.sha256(f"{url}|{json.dumps(params or {}, sort_keys=True)}".encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _cache_get(self, url: str, params: dict | None) -> dict | list | None:
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

    def _cache_put(self, url: str, params: dict | None, body: dict | list) -> None:
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

    @retry(
        retry=retry_if_exception_type(ConnectorError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def get_json(self, url: str, params: dict | None = None, headers: dict | None = None):
        cached = self._cache_get(url, params)
        if cached is not None:
            return cached
        if not self.settings.crawl_enabled:
            raise ConnectorDisabled("CRAWL_ENABLED=false")
        await self._respect_domain_interval(url)
        req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if headers:
            req_headers.update(headers)
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(url, params=params, headers=req_headers)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"network error: {exc}") from exc
        if resp.status_code in (429, 500, 502, 503, 504):
            raise ConnectorError(f"retryable status {resp.status_code} for {url}")
        if resp.status_code >= 400:
            raise ConnectorError(f"status {resp.status_code} for {url}: {resp.text[:200]}")
        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise ConnectorError(f"non-JSON response from {url}") from exc
        self._cache_put(url, params, body)
        return body
