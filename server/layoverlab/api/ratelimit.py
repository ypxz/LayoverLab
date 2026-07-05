"""In-process per-IP token buckets (no external dependency)."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class RateLimiter:
    """Token bucket keyed by (client, bucket-name); refill rate = capacity per minute."""

    clock: Callable[[], float] = time.monotonic
    _buckets: dict[tuple[str, str], _Bucket] = field(default_factory=dict)

    def allow(self, client: str, name: str, per_min: int) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        now = self.clock()
        key = (client, name)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=float(per_min), updated=now)
            self._buckets[key] = bucket
        rate = per_min / 60.0
        bucket.tokens = min(float(per_min), bucket.tokens + (now - bucket.updated) * rate)
        bucket.updated = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0.0
        return False, (1.0 - bucket.tokens) / rate

    def reset(self) -> None:
        self._buckets.clear()


limiter = RateLimiter()
