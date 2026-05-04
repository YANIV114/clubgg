#!/usr/bin/env bash
# Guards module layer separation rules.
# Detects the most common violations:
#   - AsyncSession in features/ or analysis/ (analytics must be pure)
#   - DB imports in features/ or analysis/
#   - Business logic in routers/ (inline ORM calls)
# Receives tool input JSON on stdin.

set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))")
content=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('content',''))")

# Only check Python files in app/
if [[ "$file_path" != */app/*.py ]]; then
  exit 0
fi

# ── features/ and analysis/ must be pure — no DB imports ─────────────────────
if echo "$file_path" | grep -qE '/app/(features|analysis)/'; then
  if echo "$content" | grep -qE 'from sqlalchemy|import sqlalchemy|AsyncSession|from app\.db|from app\.services'; then
    echo "Blocked: $file_path imports DB/service code." >&2
    echo "features/ and analysis/ must be pure functions — no SQLAlchemy, no sessions, no service imports." >&2
    exit 2
  fi
fi

# ── routers/ must not contain inline ORM calls ───────────────────────────────
if echo "$file_path" | grep -qE '/app/routers/'; then
  if echo "$content" | grep -qE 'session\.execute|session\.scalar|select\(|insert\(|update\(|delete\('; then
    echo "Warning: $file_path appears to contain inline ORM calls in a router." >&2
    echo "Routers must delegate DB work to services/. Move the query to app/services/." >&2
    # Warning only (exit 0) — don't block, flag for review
    exit 0
  fi
fi

# ── services/ must not import from features/ analytics ────────────────────────
if echo "$file_path" | grep -qE '/app/services/'; then
  if echo "$content" | grep -qE 'from app\.(features|analysis)'; then
    echo "Warning: $file_path imports from features/ or analysis/." >&2
    echo "Services should not depend on analytics. Analytics call services, not the reverse." >&2
    # Warning only — there may be legitimate label/schema imports
    exit 0
  fi
fi

exit 0
