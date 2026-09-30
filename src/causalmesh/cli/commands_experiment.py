"""`causalmesh experiment` — plan and execute collections (spec §62, §79).

`plan` is separate from `run` on purpose. A plan is a decision about the
design — which arms, how many repetitions, in what order — and it is worth
being able to look at that before spending the compute. `run` is then
resumable and idempotent: the index holds the progress, so a second
invocation continues rather than restarts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

import typer

from causalmesh.cli._context import Repo, find_root
from causalmesh.cli._output import Exit, emit, fail, note, out_console, table

app = typer.Typer(help="Plan and run experiments.", no_args_is_help=True)

DEFAULT_SEED = "causalmesh-default-collection-01"


def _repo_or_exit(root_option: Path | None) -> Repo:
    root = root_option.resolve() if root_option else find_root()
    if root is None:
        fail("no CausalMesh checkout found", hint="Run from inside the repository, or pass --root.")
        raise typer.Exit(Exit.USAGE)
    return Repo(root)


def _seed_bytes(seed: str) -> bytes:
    """Seeds are fixed-width because the randomizer requires 32 bytes.

    Padding a short seed rather than rejecting it keeps `--seed mine` usable
    while still producing a reproducible, recorded value.
    """
    raw = seed.encode("utf-8")
    if len(raw) > 32:
        fail(f"seed is {len(raw)} bytes; the maximum is 32")
        raise typer.Exit(Exit.USAGE)
    return raw.ljust(32, b"\0")


def _build_plan(repo: Repo, *, experiment_id: str, profile_name: str, seed: str, allow_gated: bool):
    from causalmesh.experiments import ProfileError, plan_experiment, profile
    from causalmesh.tasks import TaskError, load_tasks
    from causalmesh.tasks.definition import TaskFamily

    try:
        selected = profile(profile_name, allow_gated=allow_gated)
    except ProfileError as exc:
        fail(str(exc), hint="Pass --allow-gated only with a preregistered analysis.")
        raise typer.Exit(Exit.USAGE) from exc

    try:
        tasks = load_tasks(repo.tasks_dir)
    except TaskError as exc:
        fail(str(exc))
        raise typer.Exit(Exit.ERROR) from exc

    # An imported task's coordination shape is discovered, not declared, and
    # it has to pass its own section 37 gate before it can join a preregistered
    # design (backlog section 54). Never plan one implicitly.
    tasks = [task for task in tasks if task.family != TaskFamily.COOPERBENCH_IMPORT]

    if not tasks:
        fail("no tasks found", hint=f"Expected task YAML in {repo.tasks_dir}.")
        raise typer.Exit(Exit.ERROR)

    if selected.max_tasks is not None:
        tasks = tasks[: selected.max_tasks]

    plan = plan_experiment(
        experiment_id=experiment_id,
        profile=selected,
        task_ids=[task.task_id for task in tasks],
        master_seed=_seed_bytes(seed),
        task_hashes={task.task_id: task.content_hash() for task in tasks},
    )
    return plan, {task.task_id: task for task in tasks}


@app.command("plan")
def plan_command(
    profile_name: Annotated[
        str, typer.Option("--profile", help="smoke, pilot, small, medium.")
    ] = "smoke",
    experiment_id: Annotated[str | None, typer.Option("--id", help="Experiment id.")] = None,
    seed: Annotated[str, typer.Option("--seed")] = DEFAULT_SEED,
    allow_gated: Annotated[
        bool, typer.Option("--allow-gated", help="Permit a gated profile (confirmatory).")
    ] = False,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Produce a run schedule without executing anything."""
    repo = _repo_or_exit(root_option)
    name = experiment_id or f"exp_{profile_name}"
    plan, _ = _build_plan(
        repo, experiment_id=name, profile_name=profile_name, seed=seed, allow_gated=allow_gated
    )

    per_arm: dict[str, int] = {}
    for run in plan.runs:
        per_arm[run.arm] = per_arm.get(run.arm, 0) + 1

    payload = {
        "arms": list(plan.arms),
        "balanced": plan.is_balanced(),
        "experiment_id": plan.experiment_id,
        "per_arm": per_arm,
        "profile": plan.profile,
        "repetitions": plan.repetitions,
        "runs": len(plan),
        "tasks": list(plan.task_ids),
    }
    if not emit(payload, as_json=as_json):
        rendered = table(f"plan: {plan.experiment_id}", ["property", "value"])
        rendered.add_row("profile", plan.profile)
        rendered.add_row("tasks", ", ".join(plan.task_ids))
        rendered.add_row("arms", ", ".join(plan.arms))
        rendered.add_row("repetitions", str(plan.repetitions))
        rendered.add_row("total runs", str(len(plan)))
        rendered.add_row("balanced", "yes" if plan.is_balanced() else "no")
        out_console.print(rendered)
        order = ", ".join(f"{run.task_id}:{run.arm}" for run in plan.runs[:8])
        suffix = " ..." if len(plan.runs) > 8 else ""
        note(f"execution order (randomized): {order}{suffix}")
    raise typer.Exit(Exit.OK)


def _attach_checkpoint_prompt(run_config: dict[str, Any], *, has_checkpoints: bool) -> None:
    """Install the terminal handler, only when a person can actually answer.

    Without an interactive stdin the flag does nothing and the default
    `AutoDenyHandler` stays: a prompt nobody is there to read must not be
    answered by whatever happens to be piped in. It is also said aloud, so an
    operator is not left believing a person approved something.
    """
    import sys

    from causalmesh.policy.terminal_handler import TerminalCheckpointHandler

    if not has_checkpoints:
        note("--checkpoint-prompt: the contract declares no policy.checkpoints; nothing to ask")
        return
    if not sys.stdin.isatty():
        note("--checkpoint-prompt ignored: stdin is not interactive; checkpoints are refused")
        return
    run_config["checkpoint_handler"] = TerminalCheckpointHandler(
        input_stream=sys.stdin, require_tty=True
    )
    note(
        "--checkpoint-prompt: matched checkpoints will be put to you here "
        "(asked on every arm, enforced only on C3; the run is not reproducible)"
    )


@app.command("run")
def run_command(
    profile_name: Annotated[str, typer.Option("--profile")] = "smoke",
    experiment_id: Annotated[str | None, typer.Option("--id")] = None,
    seed: Annotated[str, typer.Option("--seed")] = DEFAULT_SEED,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Stop after this many runs; the rest stay planned."),
    ] = None,
    allow_gated: Annotated[bool, typer.Option("--allow-gated")] = False,
    run_timeout: Annotated[
        float | None,
        typer.Option(
            "--run-timeout",
            help=(
                "Wall-clock budget per run, in seconds. A run that exceeds it is interrupted "
                "at its next await, keeps its partial evidence and is recorded timed out "
                "(never retried). Default: no timeout."
            ),
        ),
    ] = None,
    use_contract: Annotated[
        bool,
        typer.Option(
            "--contract/--no-contract",
            help=(
                "Discover causalmesh.yaml and install ContractGate if found. "
                "Off skips discovery entirely, so the arms' own gate is always what runs."
            ),
        ),
    ] = True,
    record_host: Annotated[
        bool,
        typer.Option(
            "--record-host",
            help=(
                "Record the real hostname and OS username in each run's envelope. "
                "Default: a keyed digest of each, or unknown."
            ),
        ),
    ] = False,
    checkpoint_prompt: Annotated[
        bool,
        typer.Option(
            "--checkpoint-prompt",
            help=(
                "Ask a person at this terminal to decide each matched policy.checkpoints "
                "rule. Needs a contract and an interactive stdin; otherwise checkpoints "
                "keep being refused automatically. The run is then not reproducible."
            ),
        ),
    ] = False,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Execute a collection. Resumable: re-running continues where it stopped."""
    from causalmesh.policy.contract import Contract, ContractError
    from causalmesh.provenance import Environment
    from causalmesh.scheduler import ExperimentRunner, RunEnvironment

    if run_timeout is not None and not run_timeout > 0:
        fail("--run-timeout must be greater than zero", hint="Omit it for no timeout.")
        raise typer.Exit(Exit.USAGE)

    repo = _repo_or_exit(root_option)
    name = experiment_id or f"exp_{profile_name}"
    plan, tasks = _build_plan(
        repo, experiment_id=name, profile_name=profile_name, seed=seed, allow_gated=allow_gated
    )

    environment = RunEnvironment(
        fixtures_root=repo.fixtures_dir,
        raw_root=repo.experiment_dir(name),
        workspace_root=repo.workspace_dir / name,
        index_path=repo.index_path(name),
    )

    captured = Environment.capture(repo.root, record_host=record_host)
    run_config = captured.to_run_config()

    if use_contract:
        try:
            contract = Contract.find(repo.root)
        except ContractError as exc:
            fail(str(exc), hint="Fix causalmesh.yaml, then run this again.")
            raise typer.Exit(Exit.USAGE) from None
        if contract is not None:
            run_config["contract_path"] = str(contract.source)
            note(f"causalmesh.yaml found; ContractGate installed (arm={contract.arm})")
            if checkpoint_prompt:
                _attach_checkpoint_prompt(run_config, has_checkpoints=bool(contract.checkpoints))
        else:
            note("no causalmesh.yaml found; arms install their own gate")
            if checkpoint_prompt:
                note("--checkpoint-prompt ignored: no contract, so there are no checkpoints")
    else:
        note("--no-contract: skipping causalmesh.yaml discovery")
        if checkpoint_prompt:
            note("--checkpoint-prompt ignored: there is no contract, so there are no checkpoints")

    note(f"{name}: {len(plan)} runs planned ({plan.profile} profile)")
    if captured.git.dirty:
        note("working tree is dirty; these runs will not be attributable to a commit")
    with ExperimentRunner(
        plan=plan,
        tasks=tasks,
        environment=environment,
        master_seed=_seed_bytes(seed),
        run_config=run_config,
        run_timeout_s=run_timeout,
    ) as runner:
        registered = runner.prepare()
        if registered:
            note(f"registered {registered} new run(s)")
        else:
            note("nothing new to register; resuming")
        report = asyncio.run(runner.run(limit=limit))

    payload = report.to_dict()
    payload["raw_directory"] = str(repo.experiment_dir(name))
    if not emit(payload, as_json=as_json):
        rendered = table(f"run: {report.experiment_id}", ["outcome", "runs"])
        rendered.add_row("executed", str(report.executed))
        rendered.add_row("completed", str(report.completed))
        rendered.add_row("failed", str(report.failed))
        rendered.add_row("timed out", str(report.timed_out))
        rendered.add_row("already done", str(report.already_done))
        rendered.add_row("task successes", f"{report.succeeded_tasks} of {report.planned}")
        out_console.print(rendered)
        for error in report.errors:
            out_console.print(f"  [red]error[/red] {error}")
        note(f"artifacts: {repo.experiment_dir(name)}")
        note(f"verify with: causalmesh verify --id {name}")

    raise typer.Exit(Exit.OK if report.is_complete else Exit.FAILED)


@app.command("scalability")
def scalability_command(
    profile_name: Annotated[
        str,
        typer.Option("--profile", help="scalability, scalability_smoke."),
    ] = "scalability_smoke",
    seed: Annotated[str, typer.Option("--seed")] = "causalmesh-scalability-seed-0001",
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Measure delivery cost against agent count (broadcast vs path-scoped).

    Runs scripted mock agents on a generated N-agent task, in a scratch
    directory that is removed afterwards, and prints what was measured on
    this machine. Nothing is written to the repository and no gate applies:
    the profile registers no hypothesis and says nothing about real agents.
    """
    import tempfile

    from causalmesh.experiments.scalability import scalability_profile
    from causalmesh.tasks.scalability import render_scalability, run_scalability

    try:
        selected = scalability_profile(profile_name)
    except ValueError as exc:
        fail(str(exc), hint="Try scalability_smoke for a quick check.")
        raise typer.Exit(Exit.USAGE) from exc

    note(f"{selected.name}: {selected.run_count()} runs (scripted mock agents)")
    with tempfile.TemporaryDirectory(prefix="causalmesh_scal_") as scratch:
        report = asyncio.run(
            run_scalability(selected, workspace_root=Path(scratch), seed=_seed_bytes(seed))
        )

    if not emit(report.to_dict(), as_json=as_json):
        typer.echo(render_scalability(report))
    bad = [run for run in report.runs if not run.chain_valid]
    raise typer.Exit(Exit.OK if not bad else Exit.FAILED)


@app.command("status")
def status_command(
    experiment_id: Annotated[str | None, typer.Option("--id")] = None,
    latest: Annotated[
        bool, typer.Option("--latest", help="Use the most recent experiment.")
    ] = False,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show what a collection has produced so far."""
    repo = _repo_or_exit(root_option)
    experiments = repo.experiments()

    if experiment_id is None:
        if latest and experiments:
            experiment_id = experiments[0]
        elif not experiments:
            fail("no experiments found", hint="Run `causalmesh experiment run` first.")
            raise typer.Exit(Exit.FAILED)
        else:
            payload = {"experiments": experiments}
            if not emit(payload, as_json=as_json):
                rendered = table("experiments", ["id", "runs"])
                for name in experiments:
                    rendered.add_row(name, str(len(repo.run_dirs(name))))
                out_console.print(rendered)
                note("pass --id or --latest for detail")
            raise typer.Exit(Exit.OK)

    run_dirs = repo.run_dirs(experiment_id)
    if not run_dirs:
        fail(f"no runs found for {experiment_id}")
        raise typer.Exit(Exit.FAILED)

    import json

    per_arm: dict[str, dict[str, int]] = {}
    for directory in run_dirs:
        artifact = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        arm = artifact.get("arm", "?")
        result = artifact.get("result") or {}
        bucket = per_arm.setdefault(
            arm, {"runs": 0, "successes": 0, "denials": 0, "bytes": 0, "unknown": 0}
        )
        bucket["runs"] += 1
        outcome = result.get("outcome")
        if isinstance(outcome, dict) and "succeeded" in outcome:
            bucket["successes"] += 1 if outcome["succeeded"] else 0
        else:
            bucket["unknown"] += 1
        bucket["denials"] += len(result.get("denials") or ())
        bucket["bytes"] += int(result.get("coordination_bytes") or 0)

    status_payload: dict[str, Any] = {
        "experiment_id": experiment_id,
        "per_arm": per_arm,
        "runs": len(run_dirs),
    }
    if not emit(status_payload, as_json=as_json):
        rendered = table(
            f"status: {experiment_id}", ["arm", "runs", "passed", "denials", "mean bytes"]
        )
        for arm in sorted(per_arm):
            bucket = per_arm[arm]
            mean = bucket["bytes"] / bucket["runs"] if bucket["runs"] else 0
            passed = f"{bucket['successes']}/{bucket['runs']}"
            if bucket["unknown"]:
                passed += f" (+{bucket['unknown']} unknown)"
            rendered.add_row(
                arm,
                str(bucket["runs"]),
                passed,
                str(bucket["denials"]),
                f"{mean:.0f}",
            )
        out_console.print(rendered)
    raise typer.Exit(Exit.OK)
