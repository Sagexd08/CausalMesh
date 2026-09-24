# Standalone Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator gate a real coding agent's writes in their own project, outside a CausalMesh checkout, through three concrete surfaces: `causalmesh policy check --stdin`, a documented Claude Code hook adapter, and a Dockerized `causalmesh serve`.

**Architecture:** No new command and no new core logic. `policy check` gains a second input path (stdin JSON) that feeds the same `_build()`/`Gate.check()` call its CLI flags already do. `docs/adoption.md` documents the full, tested wiring for one real harness. `docker/Dockerfile` and two `docker-compose.yml` files (repo-root smoke test, operator-facing example) package the already-standalone `causalmesh serve`.

**Tech Stack:** Python (typer, existing `causalmesh.policy`), bash + jq (hook adapter), Docker + Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-24-standalone-adoption-design.md`

---

## Task 1: `policy check --stdin`

**Files:**
- Modify: `src/causalmesh/cli/commands_policy.py:89-129` (`check_command`)
- Test: `tests/integration/test_cli.py` (new `TestCheckStdin` class)

- [x] **Step 1: Write the failing tests**

Add to `tests/integration/test_cli.py`, after the existing imports and fixtures (following the file's own `invoke()`/`payload()` helpers already defined near the top):

```python
class TestCheckStdin:
    def test_stdin_json_matches_the_equivalent_flags(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles:\n  - agent_id: agent_a\n    owns: [src/config.py]\n",
            encoding="utf-8",
        )
        from_flags = invoke(
            "policy", "check", "--root", str(tmp_path),
            "--agent", "agent_b", "--kind", "path", "--name", "src/config.py", "--json",
        )
        from_stdin = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin", "--json"],
            input='{"agent_id": "agent_b", "kind": "path", "name": "src/config.py"}',
        )
        assert from_flags.exit_code == from_stdin.exit_code == 1
        assert payload(from_flags) == payload(from_stdin)

    def test_stdin_allows_a_permitted_write(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles:\n  - agent_id: agent_a\n    owns: [src/config.py]\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin", "--json"],
            input='{"agent_id": "agent_a", "kind": "path", "name": "src/config.py"}',
        )
        assert result.exit_code == 0, result.stdout
        assert payload(result)["allowed"] is True

    def test_stdin_supports_spend_with_an_amount(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\n"
            "roles:\n"
            "  - agent_id: buyer\n"
            "    archetype: spender\n"
            "    allow: [api.example.com]\n"
            "    budget: { usd_total: \"5.00\" }\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin", "--json"],
            input='{"agent_id": "buyer", "kind": "spend", "name": "api.example.com", "amount": "1.00"}',
        )
        assert result.exit_code == 0, result.stdout
        assert payload(result)["allowed"] is True

    def test_malformed_json_on_stdin_is_a_usage_error(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text("version: 1\n", encoding="utf-8")
        result = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin"],
            input="not json at all",
        )
        assert result.exit_code == 2

    def test_a_json_object_missing_required_fields_is_a_usage_error(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text("version: 1\n", encoding="utf-8")
        result = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin"],
            input='{"kind": "path"}',
        )
        assert result.exit_code == 2

    def test_stdin_and_flags_together_prefers_flags(self, tmp_path: Path) -> None:
        """`--stdin` is a mode switch; when both are somehow given, the

        explicit CLI flags are what actually ran, not a silent merge with
        whatever also arrived on stdin.
        """
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles:\n  - agent_id: agent_a\n    owns: [src/config.py]\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            [
                "policy", "check", "--root", str(tmp_path), "--stdin", "--json",
                "--agent", "agent_a", "--kind", "path", "--name", "src/config.py",
            ],
            input='{"agent_id": "agent_b", "kind": "path", "name": "src/config.py"}',
        )
        assert result.exit_code == 0, result.stdout
        assert payload(result)["allowed"] is True
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/integration/test_cli.py::TestCheckStdin -v`
Expected: FAIL with `No such option: --stdin` (or similar) for every test — `--stdin` does not exist yet.

- [x] **Step 3: Implement `--stdin` in `check_command`**

Read the current `check_command` first (`src/causalmesh/cli/commands_policy.py:89-129`) so the replacement below lines up with what is actually there. Replace the whole function:

```python
@app.command("check")
def check_command(
    agent: Annotated[str | None, typer.Option("--agent", help="Which agent is asking.")] = None,
    kind: Annotated[str, typer.Option("--kind", help=f"One of: {', '.join(KINDS)}.")] = "path",
    name: Annotated[str, typer.Option("--name", help="Path, host, or budget name.")] = "",
    amount: Annotated[
        str | None, typer.Option("--amount", help="For spend and budget. Quote it.")
    ] = None,
    unit: Annotated[str, typer.Option("--unit")] = "USD",
    stdin: Annotated[
        bool,
        typer.Option(
            "--stdin",
            help='Read {"agent_id", "kind", "name", "amount"?, "unit"?} as JSON from stdin '
            "instead of --agent/--kind/--name/--amount. For wiring into an agent harness's "
            "hook mechanism -- see docs/adoption.md.",
        ),
    ] = False,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Ask the gate whether an action would be allowed. Records nothing.

    Exits 0 when allowed and 1 when refused, so a script can branch on the
    answer without parsing anything.
    """
    from causalmesh.policy import Gate, ResourceError

    contract = _load_or_exit(root_option)

    if stdin and agent is None:
        agent, kind, name, amount, unit = _read_stdin_request(default_unit=unit)

    if not agent:
        fail("nothing to check", hint="Pass --agent, or --stdin with agent_id in the JSON.")
        raise typer.Exit(Exit.USAGE)
    if not name:
        fail("nothing to check", hint="Pass --name with a path, host, or budget name.")
        raise typer.Exit(Exit.USAGE)

    try:
        resource = _build(kind=kind, name=name, amount=amount, unit=unit)
    except ResourceError as exc:
        fail(str(exc))
        raise typer.Exit(Exit.USAGE) from None

    gate = Gate(contract, run_id="policy-check", enforcing=contract.arm == "C3")
    verdict = gate.check(agent_id=agent, resource=resource, now_us=0)

    if emit(verdict.to_dict(), as_json=as_json):
        raise typer.Exit(Exit.OK if verdict.allowed else Exit.FAILED)

    mark = "[green]ALLOW[/green]" if verdict.allowed else "[yellow]REFUSE[/yellow]"
    out_console.print(f"{mark}  {resource.describe()}")
    out_console.print(f"       [dim]{verdict.rule}[/dim]  {verdict.reason}")
    if verdict.detail.get("would_refuse"):
        note(f"arm {contract.arm} does not enforce; C3 would have refused this")
    raise typer.Exit(Exit.OK if verdict.allowed else Exit.FAILED)
```

Add the stdin-parsing helper right after `_load_or_exit` (`src/causalmesh/cli/commands_policy.py`, before `KINDS` is used elsewhere -- place it near `_build`, which it parallels):

```python
def _read_stdin_request(*, default_unit: str) -> tuple[str, str, str, str | None, str]:
    """Parse one JSON object from stdin into the same fields --agent/--kind/

    --name/--amount/--unit already carry. A malformed payload is a usage
    error with a hint, not a crash -- the same discipline `_load_or_exit`
    already applies to a broken `causalmesh.yaml`.
    """
    import json
    import sys

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"stdin is not valid JSON: {exc}", hint='Expected {"agent_id": "...", "kind": "...", "name": "..."}.')
        raise typer.Exit(Exit.USAGE) from None
    if not isinstance(payload, dict):
        fail("stdin JSON must be an object", hint='Expected {"agent_id": "...", "kind": "...", "name": "..."}.')
        raise typer.Exit(Exit.USAGE)

    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        fail("stdin JSON is missing a non-empty `agent_id`")
        raise typer.Exit(Exit.USAGE)
    kind = payload.get("kind", "path")
    name = payload.get("name", "")
    amount = payload.get("amount")
    unit = payload.get("unit", default_unit)
    return agent_id, str(kind), str(name), (str(amount) if amount is not None else None), str(unit)
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_cli.py::TestCheckStdin -v`
Expected: PASS, all 6 tests.

- [x] **Step 5: Run the full existing policy CLI coverage to check nothing broke**

Run: `python -m pytest tests/integration/test_cli.py tests/unit/test_policy.py tests/unit/test_policy_gate.py -v`
Expected: PASS, no regressions (the `--agent` flag became `Optional[str] = None` instead of required -- confirm every existing `policy check` test that relied on `--agent` being required, if any, still passes; if one specifically tested "missing --agent is a Typer usage error before the command body runs," it now needs updating since the option is no longer marked required at the Typer level and the check moved into the function body with the same `Exit.USAGE` result).

- [x] **Step 6: Lint and format**

Run: `python -m ruff check src/causalmesh/cli/commands_policy.py tests/integration/test_cli.py`
Run: `python -m ruff format src/causalmesh/cli/commands_policy.py tests/integration/test_cli.py`
Expected: both clean.

- [x] **Step 7: Commit**

```bash
git add src/causalmesh/cli/commands_policy.py tests/integration/test_cli.py
git commit -m "feat(cli): policy check --stdin, for wiring into an agent harness's hook mechanism"
```

---

## Task 2: `docs/adoption.md` with the Claude Code hook example

**Files:**
- Create: `docs/adoption.md`
- Test: `tests/integration/test_adoption_hook.py`

- [x] **Step 1: Write the failing test**

Create `tests/integration/test_adoption_hook.py`:

```python
"""The Claude Code hook adapter documented in docs/adoption.md, run for

real against a synthesized PreToolUse payload -- not merely present in the
doc, but proven to produce the JSON shape Claude Code actually expects.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO / "docs" / "examples" / "claude-pretooluse.sh"


@pytest.fixture
def contract_dir(tmp_path: Path) -> Path:
    (tmp_path / "causalmesh.yaml").write_text(
        "version: 1\nroles:\n  - agent_id: claude-code\n    owns: [src/allowed.py]\n",
        encoding="utf-8",
    )
    return tmp_path


def run_hook(payload: dict, *, cwd: Path) -> dict:
    if sys.platform == "win32" and not (REPO / "docs" / "examples").exists():
        pytest.skip("hook script not yet created")
    result = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestClaudeCodeHookAdapter:
    def test_allows_a_write_to_an_owned_path(self, contract_dir: Path) -> None:
        output = run_hook(
            {"tool_name": "Write", "tool_input": {"file_path": "src/allowed.py"}},
            cwd=contract_dir,
        )
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_denies_a_write_to_an_unowned_path(self, contract_dir: Path) -> None:
        output = run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/someone_elses.py"}},
            cwd=contract_dir,
        )
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "reason" not in output["hookSpecificOutput"] or output["hookSpecificOutput"].get(
            "permissionDecisionReason"
        )

    def test_a_non_write_tool_is_allowed_without_consulting_the_gate(
        self, contract_dir: Path
    ) -> None:
        output = run_hook({"tool_name": "Read", "tool_input": {"file_path": "anything.py"}}, cwd=contract_dir)
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/integration/test_adoption_hook.py -v`
Expected: FAIL — `docs/examples/claude-pretooluse.sh` does not exist yet.

- [x] **Step 3: Write the hook adapter script**

Create `docs/examples/claude-pretooluse.sh`:

```bash
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
```

Make it executable: `chmod +x docs/examples/claude-pretooluse.sh`

- [x] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/integration/test_adoption_hook.py -v`
Expected: PASS, all 3 tests. (Requires `jq` and `bash` on the test runner; if `jq` is missing, install it first -- `apt-get install -y jq` on Linux CI runners, already present on most macOS/Git-Bash-on-Windows setups. If genuinely unavailable, skip with a clear reason rather than letting the test hang or error unclearly.)

- [x] **Step 5: Write `docs/adoption.md`**

Create `docs/adoption.md`:

```markdown
# Adopting CausalMesh in your own project

CausalMesh's experiment harness (`causalmesh doctor`, `experiment run`,
`verify`, `analyze`) needs a checkout of this repository -- it reads
`tasks/` and `fixtures/`, which are this project's own research material.

The policy plane does not. `Contract.load(...)` and `Gate(...).check(...)`
work in any directory, and so do the CLI commands built on them:
`causalmesh policy init`, `causalmesh policy check`, and `causalmesh
serve`. This page shows two ways to actually gate a real agent's actions in
your own project, using nothing but those.

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
```

- [x] **Step 6: Lint the new script's shell syntax**

Run: `bash -n docs/examples/claude-pretooluse.sh`
Expected: no output (syntax is valid).

- [x] **Step 7: Commit**

```bash
git add docs/adoption.md docs/examples/claude-pretooluse.sh tests/integration/test_adoption_hook.py
git commit -m "docs(adoption): a real, tested Claude Code hook adapter for policy check --stdin"
```

---

## Task 3: Dockerfile and Docker Compose for `causalmesh serve`

**Files:**
- Create: `docker/Dockerfile`
- Create: `docker-compose.yml` (repo root)
- Create: `docker/.dockerignore`

- [x] **Step 1: Write `docker/Dockerfile`**

```dockerfile
# CausalMesh's policy plane, containerized. Generic and project-agnostic:
# no causalmesh.yaml is baked in here -- docker-compose.yml (or an
# operator's own) bind-mounts one at run time. See docs/adoption.md.
FROM python:3.12-slim AS base

WORKDIR /app

# Only the four runtime dependencies (cryptography, PyYAML, typer, rich) --
# the analysis extra is deliberately not installed here, matching this
# project's own "the runtime core is deliberately light" rule (AGENTS.md).
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

EXPOSE 8420

# --host 0.0.0.0 so Docker's port mapping actually reaches the process
# inside the container; --root . resolves against /app, where the
# operator's causalmesh.yaml is bind-mounted by docker-compose.yml.
ENTRYPOINT ["causalmesh", "serve", "--host", "0.0.0.0"]
```

- [x] **Step 2: Write `docker/.dockerignore`**

```
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
data/
fixtures/
tests/
frontend/
docs/
.git/
```

- [x] **Step 3: Write the repo-root `docker-compose.yml`**

```yaml
# Builds and runs the image against this repository's own causalmesh.yaml
# -- a smoke test for docker/Dockerfile before anyone outside this repo
# uses it. See docs/adoption.md for the shape an operator's own project uses.
services:
  causalmesh:
    build:
      context: .
      dockerfile: docker/Dockerfile
    ports:
      - "8420:8420"
    volumes:
      - ./causalmesh.yaml:/app/causalmesh.yaml:ro
```

- [x] **Step 4: Build the image and verify it starts**

Run: `docker build -t causalmesh-test -f docker/Dockerfile .`
Expected: build succeeds (no Docker available in this environment means this step is verified by whoever has Docker installed -- state this plainly rather than silently skipping if `docker` is not on PATH here).

Run: `docker compose up -d`
Run: `curl -s http://localhost:8420/healthz`
Expected: a 200 response.
Run: `curl -s -X POST http://localhost:8420/v1/chat/completions -H "content-type: application/json" -d '{"model":"gpt-4","messages":[]}'`
Expected: a gated response (allowed or refused, per this repo's own `causalmesh.yaml` and the C3 arm it declares) -- not a connection error.
Run: `docker compose down`

- [x] **Step 5: Commit**

```bash
git add docker/Dockerfile docker/.dockerignore docker-compose.yml
git commit -m "feat(docker): a Dockerfile and docker-compose.yml for causalmesh serve"
```

---

## Task 4: Final verification pass

- [x] **Step 1: Run the full fast suite**

Run: `python -m pytest -m unit -q`
Expected: all pass, no new failures.

- [x] **Step 2: Run the full integration suite (this task's new tests plus everything existing)**

Run: `python -m pytest tests/integration -q`
Expected: all pass, no new failures. (`test_adoption_hook.py` may skip if `jq`/`bash` are unavailable on this runner -- that is an acceptable, clearly-labeled skip, not a silent gap.)

- [x] **Step 3: Lint and format the whole diff**

Run: `python -m ruff check src tests`
Run: `python -m ruff format --check src tests`
Expected: both clean.

- [x] **Step 4: Update `docs/backlog.md`**

Add an entry (following the file's existing style -- see neighboring "Status: resolved" entries) recording that standalone adoption is now real: `policy check --stdin`, the Claude Code hook example, and the Docker packaging, with a pointer to `docs/adoption.md` and this plan's spec. Name what remains open per the spec's "What does not ship": no published registry image, no persistence of real-world verdicts, no adapters for harnesses other than Claude Code.

- [x] **Step 5: Final commit**

```bash
git add docs/backlog.md
git commit -m "docs(backlog): record standalone adoption as shipped"
```
