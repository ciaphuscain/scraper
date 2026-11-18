#!/usr/bin/env bash
# Run backend and frontend test suites (Linux/macOS/CI).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/backend" && "$ROOT/.venv/bin/python" -m pytest -q)
(cd "$ROOT/frontend" && npx tsc -b && npx vitest run)
