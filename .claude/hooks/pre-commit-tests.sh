#!/usr/bin/env bash
# Runs the test suite before git commit or git push.
# Blocks the operation if tests fail.
# Receives tool input JSON on stdin.

set -euo pipefail

input=$(cat)
command=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))")

# Only run on git commit or git push
if ! echo "$command" | grep -qE 'git\s+(commit|push)'; then
  exit 0
fi

# Resolve project root from cwd
cwd=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd','.'))")
cd "$cwd"

# Walk up to find project root
project_root=""
search="$cwd"
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

cd "$project_root"
failed=0

# ── Python ────────────────────────────────────────────────────────────────────
if [[ -f "pyproject.toml" ]]; then
  echo "Running pytest..." >&2
  if command -v uv &>/dev/null; then
    uv run pytest -x -q 2>&1 || failed=1
  else
    python -m pytest -x -q 2>&1 || failed=1
  fi
fi

# ── JavaScript / TypeScript ───────────────────────────────────────────────────
if [[ -f "package.json" ]]; then
  echo "Running JS tests..." >&2
  npm run test --if-present 2>&1 || failed=1

  echo "Running JS build check..." >&2
  npm run build --if-present 2>&1 || failed=1
fi

if [[ $failed -ne 0 ]]; then
  echo "" >&2
  echo "Blocked: tests failed. Fix failing tests before committing." >&2
  exit 2
fi

exit 0
