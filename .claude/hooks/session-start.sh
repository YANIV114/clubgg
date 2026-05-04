#!/usr/bin/env bash
# Runs at session start. Outputs a reminder to read CLAUDE.md and project rules.
# SessionStart hooks do not receive tool input — no stdin to parse.

set -euo pipefail

# Locate CLAUDE.md relative to cwd (the project root when invoked from the project)
if [[ -f "CLAUDE.md" ]]; then
  echo "Read CLAUDE.md before starting any work in this session."
  echo ""
  echo "Key rules for this project:"
  echo "  - All chip amounts: Decimal (never float)"
  echo "  - All metrics: wrapped in LabeledMetric (observed/derived/inferred/speculative)"
  echo "  - Module boundaries: parsing → normalization → services → analytics (no cross-layer imports)"
  echo "  - Schema changes: Alembic migrations only, always reversible"
  echo "  - Tests must pass before any git commit or push"
else
  echo "CLAUDE.md not found in cwd ($(pwd)). Navigate to the project root before starting work."
fi

# Auto-start dev server if not already running on port 8000
if [[ -f "pyproject.toml" ]] && ! lsof -ti :8000 > /dev/null 2>&1; then
  echo ""
  echo "Starting uvicorn dev server on port 8000..."
  nohup uv run uvicorn app.main:app --reload --port 8000 > /tmp/clubgg-uvicorn.log 2>&1 &
  disown
  echo "Server starting in background. Logs: /tmp/clubgg-uvicorn.log"
fi

exit 0
