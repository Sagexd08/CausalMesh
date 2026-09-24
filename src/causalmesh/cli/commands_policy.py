"""`causalmesh policy` — read the contract, and ask the gate what it would do.

Two commands, and the second is the important one.

`policy check` puts a hypothetical to the gate and prints the verdict. It is
how an operator answers "would this have been refused, and by which rule"
without running an agent, spending money, or waiting for a collection. A
policy you cannot interrogate is a policy you find out about in production.

Nothing here writes. `check` never records a denial, because the denial count
measures blocked *work* rather than questions asked — the distinction the
claim registry draws between `may_write` and `record_denial`, and the reason
an earlier build reported a confident zero for enforcement.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from causalmesh.cli._output import Exit, emit, fail, note, out_console, table

if TYPE_CHECKING:
    from causalmesh.policy import Contract, Resource

app = typer.Typer(
    help="Read the contract, and ask the gate what it would do.", no_args_is_help=True
)

KINDS = ("path", "spend", "endpoint", "budget")


def _load_or_exit(root_option: Path | None) -> Contract:
    from causalmesh.policy import Contract, ContractError

    try:
        contract = Contract.find(root_option or Path.cwd())
    except ContractError as exc:
        fail(str(exc), hint="Fix causalmesh.yaml, then run this again.")
        raise typer.Exit(Exit.USAGE) from None
    if contract is None:
        fail(
            "no causalmesh.yaml found",
            hint="Run `causalmesh policy init` to write one, or pass --root.",
        )
        raise typer.Exit(Exit.USAGE)
    return contract


def _read_stdin_request(*, default_unit: str) -> tuple[str, str, str, str | None, str]:
    """Parse one JSON object from stdin into the same fields --agent/--kind/--name/--amount/--unit already carry.

    A malformed payload is a usage error with a hint, not a crash -- the
    same discipline `_load_or_exit` already applies to a broken
    `causalmesh.yaml`. A field present but explicitly `null` is treated the
    same as an absent field, falling back to its default rather than
    becoming the literal string `"None"` -- a hook payload built by string
    templating is exactly the kind of caller that leaves a field `null`
    instead of omitting it.
    """
    import json
    import sys

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(
            f"stdin is not valid JSON: {exc}",
            hint='Expected {"agent_id": "...", "kind": "...", "name": "..."}.',
        )
        raise typer.Exit(Exit.USAGE) from None
    if not isinstance(payload, dict):
        fail(
            "stdin JSON must be an object",
            hint='Expected {"agent_id": "...", "kind": "...", "name": "..."}.',
        )
        raise typer.Exit(Exit.USAGE)

    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        fail("stdin JSON is missing a non-empty `agent_id`")
        raise typer.Exit(Exit.USAGE)
    kind = payload.get("kind")
    kind = "path" if kind is None else kind
    name = payload.get("name")
    name = "" if name is None else name
    amount = payload.get("amount")
    unit = payload.get("unit")
    unit = default_unit if unit is None else unit
    return agent_id, str(kind), str(name), (str(amount) if amount is not None else None), str(unit)


@app.command("show")
def show_command(
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Print the contract as the gate understands it."""
    contract = _load_or_exit(root_option)

    if emit(contract.to_dict(), as_json=as_json):
        raise typer.Exit(Exit.OK)

    rendered = table(
        f"contract - arm {contract.arm}", ["agent", "archetype", "owns", "may reach", "budget"]
    )
    for role in contract.roles:
        allow = "anywhere" if role.allow is None else (", ".join(sorted(role.allow)) or "nothing")
        budget = ", ".join(f"{key}={value:f}" for key, value in sorted(role.budget.items()))
        rendered.add_row(
            role.agent_id,
            role.archetype or "-",
            "\n".join(role.owns) or "-",
            allow,
            budget or "-",
        )
    out_console.print(rendered)

    if contract.contested:
        note(f"contested: {', '.join(sorted(contract.contested))}")
    if contract.budgets:
        shared = ", ".join(f"{key}={value:f}" for key, value in sorted(contract.budgets.items()))
        note(f"run budgets: {shared}")
    if contract.source is not None:
        note(f"read from {contract.source}")
    raise typer.Exit(Exit.OK)


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
            "hook mechanism -- see docs/adoption.md. Reads until EOF; do not invoke "
            "interactively with nothing piped in.",
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


def _build(*, kind: str, name: str, amount: str | None, unit: str) -> Resource:
    from causalmesh.policy import Resource, ResourceError

    if kind not in KINDS:
        raise ResourceError(f"unknown kind {kind!r}; expected one of {', '.join(KINDS)}")
    if kind == "path":
        return Resource.path(name)
    if kind == "endpoint":
        return Resource.endpoint(name)
    if amount is None:
        raise ResourceError(f"--kind {kind} needs --amount")
    if kind == "spend":
        return Resource.spend(to=name, amount=amount, unit=unit)
    return Resource.budget(name=name, amount=amount, unit="" if unit == "USD" else unit)


@app.command("init")
def init_command(
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing contract.")] = False,
) -> None:
    """Write a starter `causalmesh.yaml` for this repository.

    Reads `AGENTS.md`'s own Layout table when one exists, and generates one
    role per top-level path it names -- owning exactly that path, nothing
    contested, no budget. A repository with no AGENTS.md, or no parseable
    Layout table, gets the same empty `agent_a` template this command
    always wrote. Either way, deliberately permissive: a generated contract
    that refused real work on the first run would teach people to delete it.
    """
    from causalmesh.policy.contract import CONTRACT_FILENAME
    from causalmesh.policy.generate import generate_contract_yaml

    root = (root_option or Path.cwd()).resolve()
    target = root / CONTRACT_FILENAME
    if target.exists() and not force:
        fail(f"{target} already exists", hint="Pass --force to overwrite it.")
        raise typer.Exit(Exit.USAGE)

    contract_yaml = generate_contract_yaml(root)
    target.write_text(contract_yaml, encoding="utf-8")
    out_console.print(f"wrote {target}")
    if (root / "AGENTS.md").is_file():
        note("roles were read from AGENTS.md's Layout table; edit them where they don't fit")
    else:
        note("edit `owns` to declare ownership, then run `causalmesh policy show`")
    raise typer.Exit(Exit.OK)
