"""`causalmesh verify` - offline chain verification (spec section 26, 82).

The command that backs the project's central claim. It reads persisted
artifacts and checks them with no relay running and no access to whatever
produced them: hashes link, signatures hold, ordering is sound.

**What is trusted for attribution.** Two modes, and the output says which.

- With `--keys PATH` the key ring is the operator's own (see
  `causalmesh.crypto.keyring` for the file format). A record signed by any
  key other than the one the ring holds for that actor fails, so a log
  re-signed with an attacker's key is rejected. This is the mode that proves
  who wrote the chain.
- Without it the ring is built from the public keys carried on the records
  themselves. That proves the chain is internally consistent and every
  signature matches the key it names. It cannot tell a real log from one an
  attacker rewrote and re-signed with their own key, because the attacker
  replaces the embedded key too. The command therefore says so, in the table
  status ("INTACT", never "VERIFIED"), in a sentence under it, and in the
  JSON (`attribution_checked: false`).

Exit codes are unchanged by the missing ring: a chain that is intact exits 0
either way, because failing by default would break the case the command
exists for (an auditor holding an export and nothing else, spec section 82)
and every script that already calls it. `--require-keys` is the switch for
automation: it exits 2 unless `--keys` was supplied, so a pipeline cannot
mistake an unattributed pass for an attributed one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape

from causalmesh.cli._context import Repo, find_root
from causalmesh.cli._output import Exit, emit, fail, note, out_console, table

UNATTRIBUTED = (
    "attribution NOT checked: signatures were verified against the public keys carried "
    "inside the records, so a log re-signed with someone else's key would pass too. "
    "Pass --keys DIR (public keys you hold independently of the log) to check who signed."
)


def _key_ring_for(records: list[dict[str, Any]]):
    """The ring embedded in the records themselves. Proves consistency, not identity."""
    from causalmesh.crypto import PublicKeyRing

    keys: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        event = record.get("event")
        identity = event.get("identity") if isinstance(event, dict) else None
        actor = identity.get("agent_id") if isinstance(identity, dict) else None
        public_key = record.get("actor_public_key")
        if isinstance(actor, str) and actor and isinstance(public_key, str) and public_key:
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

    result = verify_chain(records, ring if ring is not None else _key_ring_for(records))
    details = [d for d in [prefix_detail] if d]
    if not result.valid:
        details.append("; ".join(str(f.detail) for f in result.failures[:3]))
    return {
        "actors": list(result.actors),
        "arm": arm,
        "detail": "; ".join(details),
        "events": result.events,
        "head_hash": result.head_hash,
        "key_ring_fingerprint": result.key_ring_fingerprint,
        "run": name,
        "valid": result.valid and prefix_ok,
    }


def _verify_one(run_dir: Path, ring: Any = None) -> dict[str, Any]:
    """Verify the chain embedded in one run artifact."""
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
    evidence_path: Annotated[
        Path | None,
        typer.Option(
            "--evidence", help="Verify an SDK evidence file (JSONL) written by CausalMesh."
        ),
    ] = None,
    keys: Annotated[
        Path | None,
        typer.Option(
            "--keys",
            help=(
                "Directory of the operator's own keys (<agent>.pub hex, <agent>.key seed, or "
                "keyring.json), or one keyring.json. Without it attribution is NOT checked."
            ),
        ),
    ] = None,
    require_keys: Annotated[
        bool,
        typer.Option(
            "--require-keys",
            help="Exit 2 unless --keys is given, so a pipeline cannot accept an unattributed pass.",
        ),
    ] = False,
    anchor_head: Annotated[
        str | None,
        typer.Option(
            "--anchor-head",
            help=(
                "With --evidence: a chain head hash recorded earlier (CausalMesh.evidence_head). "
                "Fails if it is not in the log, which is how truncation from the end shows."
            ),
        ),
    ] = None,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Verify signed chains offline, from persisted artifacts."""
    ring = None
    if keys is not None:
        from causalmesh.crypto.keyring import KeyRingError, load_key_ring

        try:
            ring = load_key_ring(keys)
        except KeyRingError as exc:
            fail(f"--keys: {exc}")
            raise typer.Exit(Exit.USAGE) from exc
    elif require_keys:
        fail(
            "--require-keys was given without --keys",
            hint="Pass --keys DIR with the operator's public keys (<agent>.pub).",
        )
        raise typer.Exit(Exit.USAGE)

    if evidence_path is not None and (run_path or experiment_id or verify_all or latest):
        fail("--evidence cannot be combined with --run, --id, --all or --latest")
        raise typer.Exit(Exit.USAGE)
    if anchor_head is not None and evidence_path is None:
        fail("--anchor-head applies to --evidence only")
        raise typer.Exit(Exit.USAGE)

    if evidence_path is not None:
        if not evidence_path.is_file():
            fail(f"no evidence file at {evidence_path}")
            raise typer.Exit(Exit.USAGE)
        results = [_verify_evidence(evidence_path, ring, anchor_head)]
        experiments = {evidence_path.name: results}
    elif run_path is not None:
        if not (run_path / "run.json").is_file():
            fail(f"{run_path} has no run.json")
            raise typer.Exit(Exit.USAGE)
        results = [_verify_one(run_path, ring)]
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
            fail("nothing selected", hint="Pass --id, --latest, --all, --run or --evidence.")
            raise typer.Exit(Exit.USAGE)

        experiments = {}
        for name in selected:
            experiments[name] = [_verify_one(d, ring) for d in repo.run_dirs(name)]

    attributed = ring is not None
    total = sum(len(v) for v in experiments.values())
    verified = sum(1 for v in experiments.values() for r in v if r["valid"])
    payload = {
        "attribution_checked": attributed,
        "experiments": experiments,
        "key_ring": (
            {
                "actors": sorted(ring.keys),
                "fingerprint": ring.fingerprint(),
                "source": "operator",
            }
            if ring is not None
            else {"source": "embedded"}
        ),
        "runs": total,
        "valid": verified == total and total > 0,
        "verified": verified,
        "warnings": [] if attributed else [UNATTRIBUTED],
    }

    if not emit(payload, as_json=as_json):
        # Without an operator ring a passing chain is INTACT, not VERIFIED: the
        # word has to match what was proven.
        passed = "[green]VERIFIED[/green]" if attributed else "[yellow]INTACT[/yellow]"
        for name, results in experiments.items():
            rendered = table(f"verify: {name}", ["run", "arm", "events", "chain"])
            for entry in results:
                status = passed if entry["valid"] else "[red]FAILED[/red]"
                rendered.add_row(
                    entry["run"].rsplit("__", 2)[-1] if "__" in entry["run"] else entry["run"],
                    str(entry.get("arm") or "?"),
                    str(entry["events"]),
                    status,
                )
            out_console.print(rendered)
            for entry in results:
                if not entry["valid"] and entry["detail"]:
                    out_console.print(
                        f"  [red]{escape(entry['run'])}[/red]: {escape(entry['detail'])}"
                    )
        if attributed:
            out_console.print(
                f"attribution checked against the operator's keys: {len(ring.keys)} actor(s), "
                f"ring {ring.fingerprint()[:16]}..."
            )
            note(f"{verified}/{total} chains verified offline")
        else:
            out_console.print(f"[yellow]{escape(UNATTRIBUTED)}[/yellow]")
            note(f"{verified}/{total} chains intact offline; attribution not checked")

    if total == 0:
        fail("no runs to verify")
        raise typer.Exit(Exit.FAILED)
    raise typer.Exit(Exit.OK if verified == total else Exit.FAILED)
