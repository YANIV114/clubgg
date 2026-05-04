#!/usr/bin/env bash
# Validates that new Alembic migration files contain both upgrade() and downgrade().
# A migration without downgrade() cannot be rolled back.
# Receives tool input JSON on stdin.

set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))")
content=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('content',''))")

# Only check Alembic migration files
if [[ "$file_path" != */alembic/versions/*.py ]]; then
  exit 0
fi

# Must define upgrade()
if ! echo "$content" | grep -qE 'def upgrade\(\)'; then
  echo "Blocked: migration $file_path is missing upgrade() function." >&2
  exit 2
fi

# Must define downgrade()
if ! echo "$content" | grep -qE 'def downgrade\(\)'; then
  echo "Blocked: migration $file_path is missing downgrade() function. All migrations must be reversible." >&2
  exit 2
fi

# downgrade() must not be a bare pass or no-op comment
downgrade_body=$(echo "$content" | python3 -c "
import sys, re
text = sys.stdin.read()
m = re.search(r'def downgrade\(\)[^:]*:\s*(.*?)(?=\ndef |\Z)', text, re.DOTALL)
if m:
    body = m.group(1).strip()
    # Strip comments
    body = re.sub(r'#.*', '', body).strip()
    print(body)
")

if [[ -z "$downgrade_body" || "$downgrade_body" == "pass" ]]; then
  echo "Blocked: migration $file_path has a no-op downgrade(). Implement a real rollback." >&2
  exit 2
fi

exit 0
