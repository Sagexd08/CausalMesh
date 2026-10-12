#!/usr/bin/env bash
# Adapts Claude Code's PreToolUse hook input to `causalmesh policy check
# --stdin`, and the verdict back to the permissionDecision shape Claude
# Code expects. See docs/adoption.md for the full wiring (settings.json,
# a real causalmesh.yaml).
#
# Fails closed. A gate that exits non-zero with no output, or denies with no
# reason, leaves the harness to guess; every way this script can go wrong
# below ends in an explicit deny on stdout, with a reason, and exit 0.
set -u

deny() {
  local out r
  if out="$(jq -nc --arg reason "$1" \
    '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}' \
    2>/dev/null)" && [ -n "$out" ]; then
    printf '%s\n' "$out"
  else
    # No working jq to escape with: strip what would break the JSON string.
    r=${1//\"/}; r=${r//\\/}; r=${r//$'\n'/ }; r=${r//$'\r'/ }
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$r"
  fi
  exit 0
}

allow() {
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}'
  exit 0
}

command -v jq >/dev/null 2>&1 \
  || deny "causalmesh hook: jq is not on PATH, so the tool call cannot be read; refusing it. Install jq (see docs/adoption.md)."

read -rd '' input || true

printf '%s' "$input" | jq -e 'type == "object" and (.tool_name | type == "string" and length > 0)' >/dev/null 2>&1 \
  || deny "causalmesh hook: stdin is not a JSON object with a tool_name; refusing the tool call."

tool_name="$(printf '%s' "$input" | jq -r '.tool_name')"
tool_name=${tool_name%$'\r'}

# Which tools are path writes is a property of the harness, not of
# CausalMesh -- that mapping lives here, in the adapter, not the core CLI.
case "$tool_name" in
  Write|Edit) kind=path ;;
  *) allow ;;
esac

name="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)" || name=""
name=${name%$'\r'}
[ -n "$name" ] \
  || deny "causalmesh hook: $tool_name call carries no tool_input.file_path, so it cannot be checked; refusing it."

command -v causalmesh >/dev/null 2>&1 \
  || deny "causalmesh hook: the causalmesh CLI is not on PATH, so $tool_name of $name cannot be checked; refusing it. Install causalmesh (see docs/adoption.md)."

verdict="$(jq -nc --arg agent_id "claude-code" --arg kind "$kind" --arg name "$name" \
  '{agent_id: $agent_id, kind: $kind, name: $name}' \
  | causalmesh policy check --stdin --json 2>/dev/null)"
rc=$?

# 0 is allowed and 1 is refused; anything else means the check did not run
# (no causalmesh.yaml at or above the working directory, an invalid one, ...).
case "$rc" in
  0|1) ;;
  *) deny "causalmesh hook: causalmesh policy check exited $rc, so $tool_name of $name was not checked (is there a valid causalmesh.yaml at or above $PWD? try: causalmesh policy show); refusing it." ;;
esac

allowed="$(printf '%s' "$verdict" | jq -r '.allowed' 2>/dev/null)" || allowed=""
allowed=${allowed%$'\r'}
reason="$(printf '%s' "$verdict" | jq -r '.reason // empty' 2>/dev/null)" || reason=""
reason=${reason%$'\r'}

if [ "$rc" = 0 ] && [ "$allowed" = "true" ]; then
  allow
fi

[ -n "$reason" ] || reason="causalmesh refused $tool_name of $name without giving a reason (exit $rc)"
deny "$reason"
