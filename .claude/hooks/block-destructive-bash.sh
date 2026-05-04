#!/usr/bin/env bash
# Blocks destructive shell commands before they execute.
# Receives tool input JSON on stdin.

set -euo pipefail

input=$(cat)
command=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))")

# git force push to main or master
if echo "$command" | grep -qE 'git push.*(--force|-f).*(main|master)'; then
  echo "Blocked: force push to main/master is not allowed." >&2
  exit 2
fi

# git reset --hard
if echo "$command" | grep -qE 'git reset --hard'; then
  echo "Blocked: git reset --hard requires explicit user confirmation." >&2
  exit 2
fi

# rm -rf on non-trivial paths
if echo "$command" | grep -qE 'rm\s+-[^ ]*r[^ ]*\s+/|rm\s+-[^ ]*r[^ ]*\s+\.\s*$|rm\s+-[^ ]*r[^ ]*\s+\*'; then
  echo "Blocked: recursive rm on root, cwd, or glob requires explicit user confirmation." >&2
  exit 2
fi

# DROP TABLE / DROP DATABASE via psql or direct SQL
if echo "$command" | grep -qiE '(psql|pg_dump|pgcli).*DROP\s+(TABLE|DATABASE|SCHEMA)'; then
  echo "Blocked: DROP TABLE/DATABASE requires explicit user confirmation." >&2
  exit 2
fi

# Direct ALTER TABLE (bypasses Alembic)
if echo "$command" | grep -qiE '(psql|pgcli).*ALTER\s+TABLE'; then
  echo "Blocked: schema changes must go through Alembic migrations, not direct ALTER TABLE." >&2
  exit 2
fi

exit 0
