#!/usr/bin/env bash
# Injects the leak report format requirements when the user's prompt
# mentions leaks, analysis, or reports. Fires on UserPromptSubmit.
# stdout is injected as additional context before Claude processes the prompt.

set -euo pipefail

input=$(cat)
prompt=$(echo "$input" | python3 -c "
import sys, json
d = json.load(sys.stdin)
# UserPromptSubmit provides the prompt in different fields depending on version
print(d.get('prompt', d.get('user_message', d.get('tool_input', {}).get('prompt', ''))))
" 2>/dev/null || echo "")

# Only inject when the prompt is about leaks, analysis, or reporting
if ! echo "$prompt" | grep -qiE '(leak|analysis|analyse|analyze|report|detect|weakness|study|finding|frequency|severity|recommend|evidence)'; then
  exit 0
fi

cat <<'EOF'
REMINDER — Leak report format. Every detected leak must include all six fields:

  name          — kebab-case identifier
  description   — what the player is doing wrong
  evidence      — specific hand IDs and action sequences (never vague summaries)
  confidence    — OBSERVED | DERIVED | INFERRED | SPECULATIVE
  severity      — critical | major | minor
  frequency     — n / N = X% (always INFERRED)
  limitations   — why this finding might be wrong
  suggested_fix — position + stack depth + specific action (no generic advice)

Confidence rules:
  n=0          → do not emit
  n=1–4        → SPECULATIVE
  n=5–19       → INFERRED, low confidence_note
  n=20+        → INFERRED, is_reliable() = True
  SPECULATIVE  → severity caps at major (never critical)
  Frequency    → always INFERRED, never DERIVED
EOF

exit 0
