#!/usr/bin/env bash
# Adapts Claude Code's PreToolUse hook input to `causalmesh policy check
# --stdin`, and the verdict back to the permissionDecision shape Claude
# Code expects. See docs/adoption.md for the full wiring (settings.json,
# a real causalmesh.yaml).
set -euo pipefail

input="$(cat)"
tool_name="$(echo "$input" | jq -r '.tool_name')"
file_path="$(echo "$input" | jq -r '.tool_input.file_path // empty')"

allow() {
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}'
  exit 0
}

# Which tools are path writes is a property of the harness, not of
# CausalMesh -- that mapping lives here, in the adapter, not the core CLI.
case "$tool_name" in
  Write|Edit) kind=path; name="$file_path" ;;
  *) allow ;;
esac

if [ -z "$name" ]; then
  allow
fi

verdict="$(jq -n --arg agent_id "claude-code" --arg kind "$kind" --arg name "$name" \
  '{agent_id: $agent_id, kind: $kind, name: $name}' \
  | causalmesh policy check --stdin --json || true)"

allowed="$(echo "$verdict" | jq -r '.allowed // false')"
reason="$(echo "$verdict" | jq -r '.reason // "no verdict"')"

if [ "$allowed" = "true" ]; then
  allow
fi

jq -n --arg reason "$reason" \
  '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}'
