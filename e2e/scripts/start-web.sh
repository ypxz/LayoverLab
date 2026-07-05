#!/usr/bin/env bash
# Production Next.js build for the E2E suite (dev-mode on-demand compiles are flaky in CI).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/web"

export NEXT_PUBLIC_API_BASE="http://localhost:8000/api"
if [ ! -d node_modules ]; then npm install; fi
npm run build
exec npm run start
