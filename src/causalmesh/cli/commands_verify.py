"""`causalmesh verify` — offline chain verification (spec §26, §82).

The command that backs the project's central claim. It reads persisted
artifacts and checks them with no relay running and no access to whatever
produced them: hashes link, signatures hold, ordering is sound.

The key ring is built from the public keys carried on the records
themselves. That is the right input here because it is what an auditor
receiving an export actually has, and because it changes nothing about what
is being proven: a forged record would need a signature valid under the key
it names, over a payload whose hash is already committed to by the next
link in the chain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from causalmesh.cli._context import Repo, find_root
from causalmesh.cli._output import Exit, emit, fail, note, out_console, table


def _key_ring_for(records: list[dict[str, Any]]):
    from causalmesh.crypto import PublicKeyRing

    keys: dict[str, str] = {}
    for record in records:
        identity = ((record.get("event") or {}).get("identity")) or {}
        actor = identity.get("agent_id")
        public_key = record.get("actor_public_key")
        if actor and public_key:
            keys[actor] = public_key
    return PublicKeyRing(keys=keys)


def _pinned_key_ring(run_dir: Path):
    """The key ring in `keyring.json` beside `run.json`, when there is one.

    Returns `(ring, None)`, `(None, None)` when the file is absent, or
    `(None, reason)` when it is present but unusable. A present-but-broken
    ring must fail the run: falling back to the keys embedded in the records
    would let whoever damaged the file choose the weaker check.
    """
    from causalmesh.crypto import PublicKeyRing

    path = run_dir / "keyring.json"
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"keyring.json is unreadable: {exc}"
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        return None, "keyring.json must be an object of agent id to hex public key"
    return PublicKeyRing.from_dict(data), None


def _verify_one(run_dir: Path) -> dict[str, Any]:
    """Verify the chain embedded in one run artifact.

    Keys come from a `keyring.json` beside `run.json` when present, which is
    independent of the records; otherwise from the records themselves.
    """
    from causalmesh.verifier import verify_chain

    artifact = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    records = artifact.get("chain") or []
    if not records:
        return {
            "arm": artifact.get("arm"),
            "detail": "no chain in artifact",
            "events": 0,
            "run": run_dir.name,
            "valid": False,
        }

    pinned, problem = _pinned_key_ring(run_dir)
    if problem is not None:
        return {
            "arm": artifact.get("arm"),
            "detail": problem,
            "events": len(records),
            "run": run_dir.name,
            "valid": False,
        }
    result = verify_chain(records, pinned if pinned is not None else _key_ring_for(records))
    return {
        "arm": artifact.get("arm"),
        "keys": "keyring.json" if pinned is not None else "embedded",
        "detail": "" if result.valid else "; ".join(str(f.detail) for f in result.failures[:3]),
        "events": result.events,
        "head_hash": result.head_hash,
        "run": run_dir.name,
        "valid": result.valid,
    }


def verify_command(
    experiment_id: Annotated[str | None, typer.Option("--id", help="Experiment to verify.")] = None,
    verify_all: Annotated[bool, typer.Option("--all", help="Verify every experiment.")] = False,
    latest: Annotated[
        bool, typer.Option("--latest", help="Verify the most recent experiment.")
    ] = False,
    run_path: Annotated[
        Path | None, typer.Option("--run", help="Verify one run directory, anywhere on disk.")
    ] = None,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Verify signed chains offline, from persisted artifacts."""
    if run_path is not None:
        if not (run_path / "run.json").is_file():
            fail(f"{run_path} has no run.json")
            raise typer.Exit(Exit.USAGE)
        results = [_verify_one(run_path)]
        experiments = {run_path.name: results}
    else:
        root = root_option.resolve() if root_option else find_root()
        if root is None:
            fail("no CausalMesh checkout found", hint="Pass --root, or --run for a single export.")
            raise typer.Exit(Exit.USAGE)
        repo = Repo(root)
        available = repo.experiments()
        if not available:
            fail("no experiments found", hint="Run `causalmesh experiment run` first.")
            raise typer.Exit(Exit.FAILED)

        if verify_all:
            selected = available
        elif latest:
            selected = available[:1]
        elif experiment_id:
            if experiment_id not in available:
                fail(
                    f"unknown experiment {experiment_id!r}",
                    hint=f"Available: {', '.join(available)}",
                )
                raise typer.Exit(Exit.USAGE)
            selected = [experiment_id]
        else:
            fail("nothing selected", hint="Pass --id, --latest, --all or --run.")
            raise typer.Exit(Exit.USAGE)

        experiments = {}
        for name in selected:
            experiments[name] = [_verify_one(d) for d in repo.run_dirs(name)]

    total = sum(len(v) for v in experiments.values())
    verified = sum(1 for v in experiments.values() for r in v if r["valid"])
    payload = {
        "experiments": experiments,
        "runs": total,
        "valid": verified == total and total > 0,
        "verified": verified,
    }

    if not emit(payload, as_json=as_json):
        for name, results in experiments.items():
            rendered = table(f"verify: {name}", ["run", "arm", "events", "chain"])
            for entry in results:
                status = "[green]VERIFIED[/green]" if entry["valid"] else "[red]FAILED[/red]"
                rendered.add_row(
                    entry["run"].rsplit("__", 2)[-1] if "__" in entry["run"] else entry["run"],
                    str(entry.get("arm") or "?"),
                    str(entry["events"]),
                    status,
                )
            out_console.print(rendered)
            for entry in results:
                if not entry["valid"] and entry["detail"]:
                    out_console.print(f"  [red]{entry['run']}[/red]: {entry['detail']}")
        note(f"{verified}/{total} chains verified offline")

    if total == 0:
        fail("no runs to verify")
        raise typer.Exit(Exit.FAILED)
    raise typer.Exit(Exit.OK if verified == total else Exit.FAILED)
