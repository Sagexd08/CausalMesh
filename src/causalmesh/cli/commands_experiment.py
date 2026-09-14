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
from typing import Annotated

import typer

from causalmesh.cli._context import Repo, find_root
from causalmesh.cli._output import Exit, emit, fail, note, out_console, table

app = typer.Typer(help="Plan and run experiments.", no_args_is_help=True)

# The seed is an input to the design, not a secret, and it is recorded in
# the plan. A default makes the quickstart one command; `--seed` makes a
# different collection possible without editing anything.
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

    if not tasks:
        fail("no tasks found", hint=f"Expected task YAML in {repo.tasks_dir}.")
        raise typer.Exit(Exit.ERROR)

    # `max_tasks` is part of the profile's definition of scale, so the
    # truncation happens here rather than being pushed into the planner.
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
    profile_name: Annotated[str, typer.Option("--profile", help="smoke, pilot, small, medium.")] = "smoke",
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


@app.command("run")
def run_command(
    profile_name: Annotated[str, typer.Option("--profile")] = "smoke",
    experiment_id: Annotated[str | None, typer.Option("--id")] = None,
    seed: Annotated[str, typer.Option("--seed")] = DEFAULT_SEED,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Stop after this many runs; the rest stay planned.")
    ] = None,
    allow_gated: Annotated[bool, typer.Option("--allow-gated")] = False,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Execute a collection. Resumable: re-running continues where it stopped."""
    from causalmesh.provenance import Environment
    from causalmesh.scheduler import ExperimentRunner, RunEnvironment

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

    # §30: which code ran, on what, run by whom. These three RunConfig
    # fields existed and defaulted to "unknown" because nothing populated
    # them, so every run produced before this was unattributable.
    captured = Environment.capture(repo.root)

    note(f"{name}: {len(plan)} runs planned ({plan.profile} profile)")
    if captured.git.dirty:
        note("working tree is dirty; these runs will not be attributable to a commit")
    with ExperimentRunner(
        plan=plan,
        tasks=tasks,
        environment=environment,
        master_seed=_seed_bytes(seed),
        run_config=captured.to_run_config(),
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
        rendered.add_row("already done", str(report.already_done))
        rendered.add_row("task successes", f"{report.succeeded_tasks} of {report.planned}")
        out_console.print(rendered)
        for error in report.errors:
            out_console.print(f"  [red]error[/red] {error}")
        note(f"artifacts: {repo.experiment_dir(name)}")
        note(f"verify with: causalmesh verify --id {name}")

    # A failed *run* is evidence, not a CLI failure (§81): the collection
    # did what it was asked to do. Only an incomplete collection is a
    # non-zero exit, because that means work is still outstanding.
    raise typer.Exit(Exit.OK if report.is_complete else Exit.FAILED)


@app.command("status")
def status_command(
    experiment_id: Annotated[str | None, typer.Option("--id")] = None,
    latest: Annotated[bool, typer.Option("--latest", help="Use the most recent experiment.")] = False,
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
        # Success lives on the outcome, not the result. Reading a missing key
        # here would report a confident zero — the exact failure mode that
        # made enforcement unmeasurable (docs/backlog.md), so an absent
        # outcome is counted as unknown rather than as a failure.
        outcome = result.get("outcome")
        if isinstance(outcome, dict) and "succeeded" in outcome:
            bucket["successes"] += 1 if outcome["succeeded"] else 0
        else:
            bucket["unknown"] += 1
        bucket["denials"] += len(result.get("denials") or ())
        bucket["bytes"] += int(result.get("coordination_bytes") or 0)

    payload = {"experiment_id": experiment_id, "per_arm": per_arm, "runs": len(run_dirs)}
    if not emit(payload, as_json=as_json):
        rendered = table(f"status: {experiment_id}", ["arm", "runs", "passed", "denials", "mean bytes"])
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
