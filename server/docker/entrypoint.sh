#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  attempt=0
  until alembic upgrade head; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
      echo "database not ready after $attempt attempts, giving up" >&2
      exit 1
    fi
    echo "database not ready (attempt $attempt), retrying in 2s..." >&2
    sleep 2
  done
fi

if [ "${RUN_SEEDS:-false}" = "true" ]; then
  python -m layoverlab.seeds.load_all
fi

exec "$@"
