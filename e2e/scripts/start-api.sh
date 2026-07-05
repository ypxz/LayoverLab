#!/usr/bin/env bash
# Fixture-connector API for the E2E suite: SQLite, deterministic fares, zero live HTTP.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/server"

PY="${E2E_PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x .venv/bin/python ]; then PY="$ROOT/server/.venv/bin/python"; else PY="python"; fi
fi

STACK_DIR="$ROOT/e2e/.stack"
mkdir -p "$STACK_DIR"
rm -f "$STACK_DIR"/layoverlab-e2e.sqlite3*

export DATABASE_URL="sqlite:///$STACK_DIR/layoverlab-e2e.sqlite3"
export FIXTURE_CONNECTOR=true
export CRAWL_ENABLED=false
export RATE_LIMIT_ENABLED=false
export WIZZ_ENABLED=false EASYJET_ENABLED=false GF_ENABLED=false
export SEARCH_STREAM_MAX_S=30 SEARCH_STREAM_POLL_S=1.0

"$PY" -m alembic upgrade head
"$PY" "$ROOT/e2e/scripts/seed_stack.py"
exec "$PY" -m uvicorn layoverlab.api.app:app --port 8000
