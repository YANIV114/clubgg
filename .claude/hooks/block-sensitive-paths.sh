#!/usr/bin/env bash
# Blocks reads and writes to sensitive files.
# Receives tool input JSON on stdin — does not use positional arguments.

set -euo pipefail

input=$(cat)
tool=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name',''))")

# Extract the relevant path field depending on the tool
file_path=$(echo "$input" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ti = d.get('tool_input', {})
# Write/Edit/Read use file_path; Bash uses command
print(ti.get('file_path', ti.get('command', '')))
")

# ── Sensitive path patterns ───────────────────────────────────────────────────
if echo "$file_path" | grep -qiE '(^|/)\.(env|envrc)($|\s)'; then
  echo "Blocked: .env files may contain secrets. Read .env.example instead." >&2
  exit 2
fi

if echo "$file_path" | grep -qiE '(secret|credential|private.?key|\.pem|\.p12|\.pfx|id_rsa|id_ed25519)'; then
  echo "Blocked: path matches a sensitive file pattern: $file_path" >&2
  exit 2
fi

if echo "$file_path" | grep -qiE '(^|/)prod(uction)?(/|$)'; then
  echo "Blocked: direct access to production path requires explicit confirmation: $file_path" >&2
  exit 2
fi

# Alembic env.py contains the database DSN — allow reads, block writes
if echo "$file_path" | grep -qE 'alembic/env\.py$' && [[ "$tool" == "Write" ]]; then
  echo "Blocked: alembic/env.py contains the database DSN. Use Edit for targeted changes, not full rewrites." >&2
  exit 2
fi

exit 0
