# Standalone adoption: `policy check --stdin` and a real hook example

Status: proposed, not built.

## The problem

`causalmesh doctor`, `experiment run`, `verify` and `analyze` all require
`tasks/` and `fixtures/` on disk — markers of this repository's own
experiment harness (`find_root` in `cli/_context.py`). Someone who clones a
totally unrelated project and wants to gate a real coding agent's writes
there has no working path through those commands.

They do, however, already have one: `Contract.load(...)` +
`Gate(...).check(...)` work in any directory today (verified against a
scratch directory with no CausalMesh checkout in sight), and `causalmesh
policy check` — which calls exactly that — already works the same way.
`causalmesh init` (this session's earlier addition) writes a working
`causalmesh.yaml` in any directory too, optionally reading that
directory's own `AGENTS.md`.

So the substrate for standalone adoption already exists. What's missing is
narrower than it first looked: `policy check` only reads its inputs from
CLI flags (`--agent --kind --name --amount`), never from stdin, so wiring
it into an agent harness's hook mechanism (which passes the tool call as
JSON on stdin) needs a `jq` translation step nobody has written or tested.
And nothing in the docs shows what that wiring actually looks like end to
end.

## What ships

**1. `causalmesh policy check --stdin`.**

When `--stdin` is passed, `check_command` reads one JSON object from stdin
instead of CLI flags:

```json
{"agent_id": "claude-code", "kind": "path", "name": "src/config.py"}
```

Same fields `--agent/--kind/--name/--amount/--unit` already accept, same
`_build()` call, same `Gate.check`, same exit codes (0 allow, 1 refuse),
same `--json` output shape. No new Resource-construction logic — this adds
one more way to reach the code that is already there.

`--agent`/`--kind`/etc. remain the default path (CLI flags win if both are
somehow given — `--stdin` is a mode switch, not a merge). A malformed or
non-object JSON payload on stdin is a usage error (`Exit.USAGE`), not a
crash — matches `_load_or_exit`'s existing "fail with a hint" convention.

**2. A tested example hook adapter, for Claude Code specifically.**

`docs/adoption.md` (new) shows the real, complete wiring for one concrete
harness — Claude Code, since that is the one this session confirmed the
wire format for (`PreToolUse` hooks: `{tool_name, tool_input}` JSON on
stdin, `{hookSpecificOutput: {permissionDecision, permissionDecisionReason}}`
JSON expected back).

The doc is explicit that CausalMesh's own `policy check --stdin` shape is
*not* Claude Code's hook shape — a small adapter script sits between them,
and the doc shows exactly what it does:

```bash
#!/usr/bin/env bash
# .causalmesh/hooks/claude-pretooluse.sh — adapt Claude Code's PreToolUse
# hook input to `causalmesh policy check --stdin`, and its verdict back to
# the permissionDecision shape Claude Code expects.
set -euo pipefail
input="$(cat)"
tool_name="$(echo "$input" | jq -r '.tool_name')"
file_path="$(echo "$input" | jq -r '.tool_input.file_path // empty')"

# This mapping (which tools are path writes) is a property of the harness,
# not of CausalMesh — it lives in the adapter, not the core CLI.
case "$tool_name" in
  Write|Edit) kind=path; name="$file_path" ;;
  *) echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}'; exit 0 ;;
esac

verdict="$(echo "{\"agent_id\":\"claude-code\",\"kind\":\"$kind\",\"name\":\"$name\"}" \
  | causalmesh policy check --stdin --json)"
allowed="$(echo "$verdict" | jq -r '.allowed')"
reason="$(echo "$verdict" | jq -r '.reason')"

if [ "$allowed" = "true" ]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}'
else
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":$(echo "$reason" | jq -Rs .)}}"
fi
```

plus the `.claude/settings.json` `PreToolUse` block that calls it, and the
`causalmesh.yaml` an operator would actually write for their own repo.

The doc states plainly what this does *not* do: no chain, no ledger, no
run — `policy check` is the same purely ephemeral, record-nothing command
it always was (see "What ships" §1). Recording real-world enforcement
history over time is named as real, separate follow-on work, not silently
implied.

## What does not ship

- No new top-level command. `causalmesh gate` was considered and rejected —
  it would duplicate `policy check` almost exactly, for no real gain over
  documenting `policy check --stdin` well.
- No auto-detection of "am I being piped JSON" without `--stdin` — explicit
  is testable and greppable in a hook script; implicit stdin-sniffing is a
  surprise waiting to happen the day someone redirects a file into stdin by
  accident.
- No persistence/ledger of real-world verdicts. Ephemeral only, this pass.
- No adapters for harnesses other than Claude Code. The doc's structure
  (adapter script + settings wiring + contract) is meant to be copied, not
  to enumerate every harness CausalMesh has not tested against.

## Testing

- `tests/integration/test_cli.py` (or a new `TestCheckStdin` class): JSON
  on stdin produces the same verdict `--agent/--kind/--name` flags would,
  for at least one case per resource kind. Malformed JSON on stdin exits
  `Exit.USAGE` with a hint. `--stdin` with no piped input does not hang
  (Typer's `CliRunner` supplies `input=` explicitly in tests either way, so
  this is really about the real CLI's behavior, verified once by hand).
- The example hook script in `docs/adoption.md` is copied into a test
  fixture and actually run against a synthesized Claude Code `PreToolUse`
  payload, asserting the JSON it prints matches the documented shape — the
  same "run the real thing, not an import of it" discipline `AGENTS.md`
  already asks for.
