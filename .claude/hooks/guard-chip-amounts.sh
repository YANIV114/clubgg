#!/usr/bin/env bash
# Blocks writing Python files that use float for chip amounts.
# float is banned for all monetary/chip values — must use Decimal.
# Receives tool input JSON on stdin.

set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))")
content=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('content',''))")

# Only check Python files
if [[ "$file_path" != *.py ]]; then
  exit 0
fi

# Skip test files — test fixtures may use float for convenience
if [[ "$file_path" == */tests/* ]]; then
  exit 0
fi

# Detect float type annotations for chip/amount/stack/pot fields
if echo "$content" | grep -qE '(chips|amount|stack|pot|rake|bet|prize|bounty|payout)\s*:\s*float'; then
  echo "Blocked: chip/amount/stack fields must use Decimal, not float. (file: $file_path)" >&2
  echo "Replace 'float' with 'Decimal' and import from decimal import Decimal." >&2
  exit 2
fi

# Detect float() calls on chip-related variables
if echo "$content" | grep -qE 'float\((chips|amount|stack|pot|rake|bet|prize|bounty)'; then
  echo "Blocked: float() cast on chip/monetary value in $file_path — use Decimal." >&2
  exit 2
fi

exit 0
