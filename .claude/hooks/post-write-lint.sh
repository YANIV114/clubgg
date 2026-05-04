#!/usr/bin/env bash
# Runs linting and formatting after file writes.
# Applies to the file that was just written, not the whole project.
# Receives tool input JSON on stdin.

set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))")

# Resolve project root (directory containing pyproject.toml / package.json)
dir=$(dirname "$file_path")
project_root=""

# Walk up to find project root
search="$dir"
while [[ "$search" != "/" ]]; do
  if [[ -f "$search/pyproject.toml" || -f "$search/package.json" ]]; then
    project_root="$search"
    break
  fi
  search=$(dirname "$search")
done

if [[ -z "$project_root" ]]; then
  exit 0
fi

# ── Python ────────────────────────────────────────────────────────────────────
if [[ -f "$project_root/pyproject.toml" && "$file_path" == *.py ]]; then
  cd "$project_root"
  # Format the specific file — faster than formatting the whole project
  uv run ruff format "$file_path" 2>/dev/null || python -m ruff format "$file_path" 2>/dev/null || true
  # Check the specific file — output issues but don't block (exit 0)
  uv run ruff check "$file_path" --fix 2>/dev/null || python -m ruff check "$file_path" --fix 2>/dev/null || true
fi

# ── JavaScript / TypeScript ───────────────────────────────────────────────────
if [[ -f "$project_root/package.json" && ("$file_path" == *.ts || "$file_path" == *.tsx || "$file_path" == *.js || "$file_path" == *.jsx) ]]; then
  cd "$project_root"
  # Run prettier on the file if available
  if command -v npx &>/dev/null; then
    npx prettier --write "$file_path" 2>/dev/null || true
    npm run lint --if-present 2>/dev/null || true
  fi
fi

exit 0
