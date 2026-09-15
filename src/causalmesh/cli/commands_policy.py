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
from typing import Annotated

import typer

from causalmesh.cli._output import Exit, emit, fail, note, out_console, table

app = typer.Typer(
    help="Read the contract, and ask the gate what it would do.", no_args_is_help=True
)

# How a resource is named on the command line, and how to build one.
KINDS = ("path", "spend", "endpoint", "budget")


def _load_or_exit(root_option: Path | None):
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
    agent: Annotated[str, typer.Option("--agent", help="Which agent is asking.")],
    kind: Annotated[str, typer.Option("--kind", help=f"One of: {', '.join(KINDS)}.")] = "path",
    name: Annotated[str, typer.Option("--name", help="Path, host, or budget name.")] = "",
    amount: Annotated[
        str | None, typer.Option("--amount", help="For spend and budget. Quote it.")
    ] = None,
    unit: Annotated[str, typer.Option("--unit")] = "USD",
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Ask the gate whether an action would be allowed. Records nothing.

    Exits 0 when allowed and 1 when refused, so a script can branch on the
    answer without parsing anything.
    """
    from causalmesh.policy import Gate, ResourceError

    contract = _load_or_exit(root_option)

    if not name:
        fail("nothing to check", hint="Pass --name with a path, host, or budget name.")
        raise typer.Exit(Exit.USAGE)

    try:
        resource = _build(kind=kind, name=name, amount=amount, unit=unit)
    except ResourceError as exc:
        fail(str(exc))
        raise typer.Exit(Exit.USAGE) from None

    # No registry and no ledger: this is a question about the declared
    # contract, asked without a run. Leases and spend-to-date belong to a
    # run, and inventing one here would answer a different question.
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


def _build(*, kind: str, name: str, amount: str | None, unit: str):
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

    Deliberately permissive: it declares structure and leaves the
    restrictions commented out. A generated contract that refused real work
    on the first run would teach people to delete it.
    """
    from causalmesh.policy.contract import CONTRACT_FILENAME

    root = (root_option or Path.cwd()).resolve()
    target = root / CONTRACT_FILENAME
    if target.exists() and not force:
        fail(f"{target} already exists", hint="Pass --force to overwrite it.")
        raise typer.Exit(Exit.USAGE)

    target.write_text(_STARTER, encoding="utf-8")
    out_console.print(f"wrote {target}")
    note("edit `owns` to declare ownership, then run `causalmesh policy show`")
    raise typer.Exit(Exit.OK)


# Written as a literal rather than dumped from a dict so the comments
# survive: the comments are most of the value of a starter file.
_STARTER = """\
# causalmesh.yaml - what agents in this repository may do.
#
# Sibling to AGENTS.md, not a replacement. AGENTS.md says what agents should
# do; this says what they are allowed to do, and the gate holds them to it.
#
# Absent means unrestricted. Declare the parts you care about; the rest keeps
# working. Check any rule with:
#     causalmesh policy check --agent agent_a --kind path --name src/config.py
version: 1

roles:
  - agent_id: agent_a
    archetype: writer
    # Paths this agent owns. A directory covers everything under it, and a
    # longer declaration wins, so you can carve one file out of a directory.
    owns: []

  # An agent that spends money. Uncomment to enforce it.
  # - agent_id: buyer
  #   archetype: spender
  #   allow: [api.example.com]      # hosts it may reach; covers subdomains
  #   budget:
  #     usd_total: "5.00"           # quote money, or use an integer
  #     usd_per_call: "0.10"        # the one catastrophic call, refused

policy:
  # C0 none - C1 transcripts - C2 metadata - C3 metadata + enforced claims.
  # Only C3 refuses; the others record what C3 would have done.
  arm: C3

  # Paths that need an exclusive lease before a write.
  contested: {}

  # Allowances for the whole run, unless a role declares its own.
  budgets: {}
    # tokens: 200000

evidence:
  sign: true
"""
