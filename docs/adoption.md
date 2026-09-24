# Adopting CausalMesh in your own project

CausalMesh's experiment harness (`causalmesh doctor`, `experiment run`,
`verify`, `analyze`) needs a checkout of this repository -- it reads
`tasks/` and `fixtures/`, which are this project's own research material.

The policy plane does not. `Contract.load(...)` and `Gate(...).check(...)`
work in any directory, and so do the CLI commands built on them:
`causalmesh init`, `causalmesh policy check`, and `causalmesh serve`. This
page shows two ways to actually gate a real agent's actions in your own
project, using nothing but those.

## 1. Declare a contract

In your own project's root:

```bash
pip install causalmesh
causalmesh init
```

Reads your project's own `AGENTS.md` (if you have one) and writes one role
per top-level path its Layout table names. With no `AGENTS.md`, it writes
a starter template with one empty `agent_a` role for you to fill in. Either
way, it is deliberately permissive: nothing is refused until you declare
`owns`, `contested`, or a `budget`.

Check what it decided: `causalmesh policy show`.

## 2. Gate a real agent's tool calls (per-call hook)

For a harness like Claude Code that calls a hook before every tool use.

**`causalmesh policy check --stdin`** reads one JSON object from stdin --

```bash
echo '{"agent_id": "claude-code", "kind": "path", "name": "src/config.py"}' \
  | causalmesh policy check --stdin --json
```

-- and prints a verdict, exiting 0 (allowed) or 1 (refused). That JSON
shape is CausalMesh's own, not any particular harness's hook protocol, so
a small adapter script sits between them. For Claude Code specifically,
whose `PreToolUse` hooks send `{tool_name, tool_input}` on stdin and expect
`{hookSpecificOutput: {permissionDecision, permissionDecisionReason}}`
back: [`docs/examples/claude-pretooluse.sh`](examples/claude-pretooluse.sh).

Wire it into `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{ "type": "command", "command": "docs/examples/claude-pretooluse.sh" }]
      }
    ]
  }
}
```

This is purely ephemeral: no chain, no ledger, no run. It answers one
question and exits, the same as `causalmesh policy check` always has.
Recording a durable history of what was gated over time is real, future
work -- not something this path does today.

## 3. Gate a real agent's model traffic (OpenAI-compatible endpoint)

For anything that speaks the OpenAI chat-completions wire protocol for its
whole model traffic, rather than calling a per-tool-call hook.

**`causalmesh serve`** starts a gate-and-record endpoint against your
`causalmesh.yaml`, standalone, no experiment harness required:

```bash
causalmesh serve --upstream https://api.openai.com
```

### With Docker Compose

In your own project, next to your `causalmesh.yaml`:

```yaml
# docker-compose.yml
services:
  causalmesh:
    build:
      context: https://github.com/Sagexd08/CausalMesh.git
      dockerfile: docker/Dockerfile
    # Once a published image exists, this replaces the build: block:
    #   image: causalmesh/causalmesh:latest
    ports:
      - "8420:8420"
    volumes:
      - ./causalmesh.yaml:/app/causalmesh.yaml:ro
    environment:
      - CAUSALMESH_UPSTREAM_API_KEY=${CAUSALMESH_UPSTREAM_API_KEY:-}
    command: ["causalmesh", "serve", "--host", "0.0.0.0", "--upstream", "https://api.openai.com"]
```

```bash
docker compose up
```

Point your agent's OpenAI-compatible client at `http://localhost:8420` and
its calls are gated and recorded against your contract before they reach
the real API.

The contract is bind-mounted read-only from your own project directory --
never baked into the image, so editing `causalmesh.yaml` never requires a
rebuild, and the same image works for every project that adopts it.

## What this does not do yet

- No published registry image (`causalmesh/causalmesh:latest`) -- the
  Compose example above builds from the Git repository until one exists.
- No persistence of verdicts from either path above. `policy check` (and
  the hook that wraps it) is stateless by design; `serve` gates and
  forwards but this adoption path does not yet wire its recording to a
  location outside a CausalMesh checkout.
- No adapter for any harness other than Claude Code. The `PreToolUse`
  JSON shape in `docs/examples/claude-pretooluse.sh` is specific to it;
  another harness's hook protocol needs its own adapter script, following
  the same pattern.
