"""Admin surface guarded by X-Admin-Token; hidden (404) when ADMIN_TOKEN is unset."""

import re
import secrets

from fastapi import APIRouter, Header, HTTPException

from layoverlab.settings import get_settings

router = APIRouter(prefix="/admin", include_in_schema=False)

_SENSITIVE_MARKERS = ("token", "secret", "password", "key")


def _require_admin(x_admin_token: str | None) -> None:
    configured = get_settings().admin_token
    if not configured:
        raise HTTPException(status_code=404, detail="not found")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, configured):
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/crawler")
def crawler_stats(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_token)
    try:
        from layoverlab.crawler.stats import get_stats  # provided by agent D
    except ImportError:
        return {"status": "pending-agent-d"}
    return get_stats()


@router.get("/config")
def config_dump(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_token)
    dump = get_settings().model_dump()
    for name, value in dump.items():
        if any(marker in name for marker in _SENSITIVE_MARKERS) and value:
            dump[name] = "***redacted***"
        elif isinstance(value, str) and "://" in value:
            dump[name] = re.sub(r"://[^@/]+@", "://***redacted***@", value)
    return dump
