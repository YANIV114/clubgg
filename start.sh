#!/usr/bin/env bash
set -euo pipefail

echo "Running database migrations..."
uv run alembic upgrade head

echo "Starting server on port ${PORT:-8000}..."
exec uv run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
