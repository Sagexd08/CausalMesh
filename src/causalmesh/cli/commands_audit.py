"""`causalmesh manifest` and `causalmesh audit` (spec §31, §33, §83).

`manifest write` records what a collection produced. `audit` is the check
that the project's traceability commitment actually holds: raw data
unmutated, every chain verifying, and the source attributable to a commit.

`audit` deliberately re-verifies the chains rather than trusting the
manifest. A manifest says the bytes are unchanged since it was written; it
says nothing about whether those bytes were ever valid. Checking only the
manifest would pass a collection whose chains never verified in the first
place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from causalmesh.cli._context import Repo, find_root
from causalmesh.cli._output import Exit, emit, fail, note, out_console, table

app = typer.Typer(help="Record and check artifact provenance.", no_args_is_help=True)

MANIFEST_SUFFIX = ".manifest.json"


def _repo_or_exit(root_option: Path | None) -> Repo:
    root = root_option.resolve() if root_option else find_root()
    if root is None:
        fail("no CausalMesh checkout found", hint="Run from inside the repository, or pass --root.")
        raise typer.Exit(Exit.USAGE)
    return Repo(root)


def _manifest_path(repo: Repo, experiment_id: str) -> Path:
    return repo.root / "data" / "manifests" / f"{experiment_id}{MANIFEST_SUFFIX}"


def _resolve(repo: Repo, experiment_id: str | None, latest: bool) -> str:
    available = repo.experiments()
    if not available:
        fail("no experiments found", hint="Run `causalmesh experiment run` first.")
        raise typer.Exit(Exit.FAILED)
    if experiment_id is None:
        if not latest:
            fail(
                "nothing selected", hint=f"Pass --latest or --id. Available: {', '.join(available)}"
            )
            raise typer.Exit(Exit.USAGE)
        return available[0]
    if experiment_id not in available:
        fail(f"unknown experiment {experiment_id!r}", hint=f"Available: {', '.join(available)}")
        raise typer.Exit(Exit.USAGE)
    return experiment_id


@app.command("write")
def write_command(
    experiment_id: Annotated[str | None, typer.Option("--id")] = None,
    latest: Annotated[bool, typer.Option("--latest")] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing manifest.")] = False,
    record_host: Annotated[
        bool,
        typer.Option(
            "--record-host",
            help=(
                "Record the real hostname and OS username. Manifests are tracked, so "
                "committing one written with this flag publishes both. Default: a "
                "keyed digest of each, or unknown."
            ),
        ),
    ] = False,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Hash every artifact in a collection and record what produced it."""
    from causalmesh.provenance import ManifestError, build

    repo = _repo_or_exit(root_option)
    name = _resolve(repo, experiment_id, latest)
    destination = _manifest_path(repo, name)

    if destination.exists() and not force:
        fail(
            f"a manifest for {name} already exists",
            hint=f"{destination} — pass --force only if you mean to replace the record.",
        )
        raise typer.Exit(Exit.FAILED)

    try:
        manifest = build(
            repo.experiment_dir(name),
            repository_root=repo.root,
            config={"experiment_id": name},
            record_host=record_host,
        )
    except ManifestError as exc:
        fail(str(exc))
        raise typer.Exit(Exit.ERROR) from exc

    manifest.write(destination)
    if record_host:
        note(
            "--record-host: this manifest names the real hostname and username; "
            "do not commit it to a repository that publishes data/manifests/"
        )
    payload = {
        "artifacts": len(manifest.artifacts),
        "bytes": manifest.total_bytes,
        "config_freeze": manifest.config_freeze,
        "experiment_id": name,
        "host_recorded": record_host,
        "path": str(destination),
    }
    if not emit(payload, as_json=as_json):
        rendered = table(f"manifest: {name}", ["property", "value"])
        rendered.add_row("artifacts", str(len(manifest.artifacts)))
        rendered.add_row("total bytes", f"{manifest.total_bytes:,}")
        rendered.add_row("config freeze", manifest.config_freeze[:16] + "...")
        rendered.add_row("git commit", str(manifest.environment["git"]["commit"])[:12])
        rendered.add_row("written to", str(destination))
        out_console.print(rendered)
        if manifest.environment["git"]["dirty"]:
            note("the working tree was dirty; this collection is not attributable to a commit")
    raise typer.Exit(Exit.OK)


def audit_command(
    experiment_id: Annotated[str | None, typer.Option("--id")] = None,
    audit_all: Annotated[bool, typer.Option("--all", help="Audit every experiment.")] = False,
    latest: Annotated[bool, typer.Option("--latest")] = False,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check that recorded evidence is present, unchanged and still valid."""
    from causalmesh.cli.commands_verify import _verify_one
    from causalmesh.provenance import Manifest, ManifestError, check

    repo = _repo_or_exit(root_option)
    if audit_all:
        selected = repo.experiments()
        if not selected:
            fail("no experiments found")
            raise typer.Exit(Exit.FAILED)
    else:
        selected = [_resolve(repo, experiment_id, latest)]

    findings: dict[str, dict] = {}
    for name in selected:
        entry: dict = {"experiment_id": name}
        manifest_path = _manifest_path(repo, name)

        if not manifest_path.is_file():
            entry["manifest"] = None
            entry["findings"] = ["no manifest recorded"]
        else:
            try:
                manifest = Manifest.read(manifest_path)
                result = check(manifest, repo.experiment_dir(name))
            except ManifestError as exc:
                fail(f"{name}: {exc}")
                raise typer.Exit(Exit.ERROR) from exc

            entry["manifest"] = result.to_dict()
            entry["environment"] = manifest.environment
            problems = []
            if result.missing:
                problems.append(f"{len(result.missing)} artifact(s) missing")
            if result.changed:
                problems.append(f"{len(result.changed)} artifact(s) changed since recording")
            if manifest.environment.get("git", {}).get("dirty"):
                problems.append("recorded from a dirty working tree")
            entry["findings"] = problems

        results = [_verify_one(d) for d in repo.run_dirs(name)]
        verified = sum(1 for r in results if r["valid"])
        entry["chains"] = {"runs": len(results), "verified": verified}
        if verified != len(results):
            entry["findings"].append(f"{len(results) - verified} chain(s) failed verification")

        findings[name] = entry

    total_findings = sum(len(e["findings"]) for e in findings.values())
    payload = {"clean": total_findings == 0, "experiments": findings, "findings": total_findings}

    if not emit(payload, as_json=as_json):
        rendered = table("audit", ["experiment", "artifacts", "chains", "verdict"])
        for name, entry in findings.items():
            manifest = entry["manifest"]
            artifacts = "not recorded" if manifest is None else f"{manifest['checked']} recorded"
            chains = f"{entry['chains']['verified']}/{entry['chains']['runs']}"
            verdict = "[green]CLEAN[/green]" if not entry["findings"] else "[red]FINDINGS[/red]"
            rendered.add_row(name, artifacts, chains, verdict)
        out_console.print(rendered)
        for name, entry in findings.items():
            for finding in entry["findings"]:
                out_console.print(f"  [yellow]{name}[/yellow]: {finding}")
        if total_findings == 0:
            note("every recorded artifact is present, unchanged, and its chain verifies")

    raise typer.Exit(Exit.FAILED if total_findings else Exit.OK)
