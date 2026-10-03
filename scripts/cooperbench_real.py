"""Run the CooperBench loader over a real checkout and print a summary (backlog §54).

    python scripts/cooperbench_real.py import --dataset <CooperBench>/dataset \\
        --cache <scratch dir for upstream fetches> [--out summary.json]
    python scripts/cooperbench_real.py gate --dataset ... --cache ... --work <scratch dir> \\
        --task pallets_click_task/task2800 [--task ...] [--merge three_way] [--out gate.json]
    python scripts/cooperbench_real.py merge-check --dataset ... --cache ... [--out merge.json]

`import` imports every feature pair of every task, fetching each task's base
files from its pinned upstream commit (network on first use, cached after),
and writes per-task counts plus every failure with its stage and reason. It
vendors nothing: the output is counts and statuses, no repository contents.

`gate` builds a full base checkout for each named task, imports the first
pair (feature1, feature2) with the generated pytest harness, checks that the
harness discriminates (every feature's tests fail on the base, pass with
`combined.patch`), then runs the real §37 gate and reports the verdict as
produced. Nothing is tuned; the pair is fixed in advance, not chosen by
outcome. Python-only: it needs pytest and each repository's own test
dependencies importable by the `python` on PATH.

`merge-check` validates `tasks/merge3.py` on every pair: for each contested
file it merges the two features' patched contents against the base with the
platform's merge and with `git merge-file`, and compares the pair-level verdict
(any conflict) with CooperBench's own `gold_conflict_report.json`. It writes
counts and pair ids only, no repository contents.

The output holds no wall-clock times, hostnames or absolute paths, so it is
reproducible from the same CooperBench commit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from causalmesh.tasks import (  # noqa: E402
    RunConfig,
    check_sensitivity,
    execute_task,
    validate_structure,
)
from causalmesh.tasks.cooperbench import (  # noqa: E402
    ImportOptions,
    feature_numbers,
    git_base_files_provider,
    import_dataset_report,
    import_task,
)
from causalmesh.tasks.cooperbench_base import (  # noqa: E402
    checkout_base_repo,
    parse_base_spec,
)

SEED = b"cooperbench-real-gate-seed"


def _upstream_commit(dataset: Path) -> str | None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=dataset,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.strip()


def _gold_conflicts(dataset: Path) -> dict[tuple[str, str], int]:
    report = dataset / "gold_conflict_report.json"
    if not report.is_file():
        return {}
    counts: dict[tuple[str, str], int] = {}
    for item in json.loads(report.read_text(encoding="utf-8")).get("conflict_pairs", []):
        key = (item["repo"], f"task{item['task_id']}")
        counts[key] = counts.get(key, 0) + 1
    return counts


def run_import(dataset: Path, cache: Path) -> dict[str, Any]:
    report = import_dataset_report(
        dataset, pairs="all", base_files_provider=git_base_files_provider(cache)
    )
    gold = _gold_conflicts(dataset)
    per_task: dict[str, dict[str, Any]] = {}
    for outcome in report.outcomes:
        key = f"{outcome.repo}/{outcome.task}"
        row = per_task.setdefault(
            key,
            {
                "features": len(feature_numbers(dataset / outcome.repo / outcome.task)),
                "pairs": 0,
                "imported": 0,
                "failed": 0,
                "pairs_with_a_contested_path": 0,
                "gold_patches_conflict_under_git_merge": gold.get((outcome.repo, outcome.task)),
            },
        )
        row["pairs"] += 1
        if outcome.status == "imported":
            row["imported"] += 1
            if outcome.contested_paths:
                row["pairs_with_a_contested_path"] += 1
        else:
            row["failed"] += 1
    summary = report.to_dict()
    failures = [o.to_dict() for o in report.outcomes if o.status != "imported"]
    return {
        "cooperbench_commit": _upstream_commit(dataset),
        "tasks_attempted": summary["tasks_attempted"],
        "tasks_with_at_least_one_imported_pair": summary["tasks_with_at_least_one_imported_pair"],
        "features_total": sum(row["features"] for row in per_task.values()),
        "pairs_attempted": summary["attempted_pairs"],
        "pairs_imported": summary["imported_pairs"],
        "pairs_failed": summary["failed_pairs"],
        "pairs_with_a_contested_path": sum(
            r["pairs_with_a_contested_path"] for r in per_task.values()
        ),
        "failures_by_reason": summary["failures_by_reason"],
        "failures": failures,
        "per_task": per_task,
    }


def _gold_pair_conflicts(dataset: Path) -> set[tuple[str, int, int, int]]:
    report = dataset / "gold_conflict_report.json"
    items = json.loads(report.read_text(encoding="utf-8")).get("conflict_pairs", [])
    return {(i["repo"], int(i["task_id"]), int(i["f1"]), int(i["f2"])) for i in items}


def _git_merge_file(base: bytes, ours: bytes, theirs: bytes, scratch: Path) -> tuple[int, bytes]:
    for name, content in (("ours", ours), ("base", base), ("theirs", theirs)):
        (scratch / name).write_bytes(content)
    done = subprocess.run(
        ["git", "merge-file", "-p", "ours", "base", "theirs"],
        cwd=scratch,
        capture_output=True,
        check=False,
    )
    return done.returncode, done.stdout


def run_merge_check(dataset: Path, cache: Path) -> dict[str, Any]:
    """Validate the platform's three-way merge against git and against the dataset."""
    import tempfile

    from causalmesh.tasks.cooperbench import feature_pairs
    from causalmesh.tasks.merge3 import merge_three_way

    gold = _gold_pair_conflicts(dataset)
    provider = git_base_files_provider(cache)
    pairs = paths = 0
    path_verdict_agrees = clean_bytes_identical = clean_paths = 0
    pair_vs_git = {"agree": 0, "disagree": 0}
    pair_vs_dataset = {"agree": 0, "disagree": 0}
    confusion = {
        "both_conflict": 0,
        "both_clean": 0,
        "we_conflict_dataset_clean": 0,
        "we_clean_dataset_conflict": 0,
    }
    disagreements: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as raw:
        scratch = Path(raw)
        for repo_dir in sorted(
            p for p in dataset.iterdir() if p.is_dir() and p.name.endswith("_task")
        ):
            for task_dir in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
                task_number = int(task_dir.name.removeprefix("task"))
                for first, second in feature_pairs(task_dir):
                    imported = import_task(
                        task_dir,
                        features=(first, second),
                        base_files=provider(task_dir, (first, second)),
                        options=ImportOptions(contested_merge="three_way"),
                    )
                    pairs += 1
                    ours_conflict = git_conflict = False
                    for path in sorted(imported.definition.contested_paths):
                        base = imported.base_files[path].encode("utf-8")
                        sides = []
                        for agent in ("agent_a", "agent_b"):
                            writes = [
                                a["write"]["content"]
                                for a in imported.definition.scenario[agent]["actions"]
                                if "write" in a and a["write"]["path"] == path
                            ]
                            sides.append(writes[-1].encode("utf-8") if writes else base)
                        mine = merge_three_way(base, sides[0], sides[1])
                        git_rc, git_out = _git_merge_file(base, sides[0], sides[1], scratch)
                        paths += 1
                        path_verdict_agrees += int(mine.clean == (git_rc == 0))
                        if mine.clean and git_rc == 0:
                            clean_paths += 1
                            clean_bytes_identical += int(mine.content == git_out)
                        ours_conflict |= not mine.clean
                        git_conflict |= git_rc != 0
                    dataset_conflict = (repo_dir.name, task_number, first, second) in gold
                    pair_vs_git["agree" if ours_conflict == git_conflict else "disagree"] += 1
                    agrees = ours_conflict == dataset_conflict
                    pair_vs_dataset["agree" if agrees else "disagree"] += 1
                    confusion[
                        {
                            (True, True): "both_conflict",
                            (False, False): "both_clean",
                            (True, False): "we_conflict_dataset_clean",
                            (False, True): "we_clean_dataset_conflict",
                        }[(ours_conflict, dataset_conflict)]
                    ] += 1
                    if not agrees or ours_conflict != git_conflict:
                        disagreements.append(
                            {
                                "pair": f"{repo_dir.name}/{task_dir.name}/f{first}-f{second}",
                                "platform_merge_conflicts": ours_conflict,
                                "git_merge_file_conflicts": git_conflict,
                                "cooperbench_gold_conflicts": dataset_conflict,
                            }
                        )
    return {
        "cooperbench_commit": _upstream_commit(dataset),
        "pairs": pairs,
        "contested_files_merged": paths,
        "file_level_verdict_agrees_with_git_merge_file": path_verdict_agrees,
        "files_both_clean": clean_paths,
        "files_both_clean_with_identical_bytes": clean_bytes_identical,
        "pair_level_vs_git_merge_file": pair_vs_git,
        "pair_level_vs_cooperbench_gold_report": pair_vs_dataset,
        "pair_level_confusion_vs_cooperbench_gold_report": confusion,
        "disagreements": disagreements,
    }


def _labels(text: str) -> list[str]:
    return re.findall(r"feature\d+: (?:PASS|FAIL)", text)


def _harness(root: Path) -> list[str]:
    done = subprocess.run(
        ["bash", "run_tests.sh"], cwd=root, capture_output=True, text=True, timeout=900
    )
    return _labels(done.stdout)


async def run_gate(
    dataset: Path, cache: Path, work: Path, tasks: list[str], merge: str = "last_writer"
) -> dict[str, Any]:
    shutil.rmtree(work, ignore_errors=True)
    fixtures = work / "fixtures"
    results: dict[str, Any] = {}
    for name in tasks:
        repo, task = name.split("/")
        task_dir = dataset / repo / task
        spec = parse_base_spec((task_dir / "setup.sh").read_text(encoding="utf-8"))
        task_id = f"cb_{repo}_{task}_real"
        fixture = fixtures / task_id
        checkout_base_repo(spec, fixture, cache_dir=cache)
        imported = import_task(
            task_dir,
            features=(1, 2),
            base_files=git_base_files_provider(cache)(task_dir, (1, 2)),
            options=ImportOptions(task_id=task_id, hidden_tests="pytest", contested_merge=merge),
        )
        imported.write_fixture(fixture)

        on_base = work / "on_base" / task
        shutil.copytree(fixture, on_base)
        on_combined = work / "on_combined" / task
        shutil.copytree(fixture, on_combined)
        applied = subprocess.run(
            ["git", "apply", "--ignore-whitespace", str(task_dir / "combined.patch")],
            cwd=on_combined,
            capture_output=True,
            check=False,
        )
        structure = validate_structure(imported.definition, fixtures_root=fixtures)
        sensitivity = await check_sensitivity(
            imported.definition,
            workspace_root=work / "ws" / task,
            fixtures_root=fixtures,
            master_seed=SEED,
            repetitions=1,
        )
        # Diagnostic only, not the verdict: which feature's tests each arm's
        # integrated workspace passes, to show *why* the arms agree.
        integrated_tests: dict[str, list[str]] = {}
        merge_conflicts: dict[str, list[str] | None] = {}
        for arm in ("C0", "C2"):
            run_id = f"diag_{arm}"
            diag = await execute_task(
                imported.definition,
                RunConfig(experiment_id="diag", run_id=run_id, arm=arm, master_seed=SEED),
                workspace_root=work / "diag" / task / arm,
                fixtures_root=fixtures,
            )
            merge_conflicts[arm] = diag.merge_conflicts
            integrated_tests[arm] = _harness(work / "diag" / task / arm / f"{run_id}_integrated")
        results[name] = {
            "integrated_workspace_tests_by_arm": integrated_tests,
            "merge_conflicts_by_arm": merge_conflicts,
            "contested_merge": merge,
            "base_commit": spec.base_commit,
            "features": [1, 2],
            "contested_paths": sorted(imported.definition.contested_paths),
            "harness_on_base": _harness(on_base),
            "combined_patch_applied": applied.returncode == 0,
            "harness_with_combined_patch": _harness(on_combined),
            "structure_valid": structure.valid,
            "structure_issues": [issue.to_dict() for issue in structure.issues],
            "gate": sensitivity.to_dict(),
            "gate_summary": sensitivity.summary(),
        }
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("import", "gate", "merge-check"):
        command = sub.add_parser(name)
        command.add_argument("--dataset", type=Path, required=True)
        command.add_argument("--cache", type=Path, required=True)
        command.add_argument("--out", type=Path)
        if name == "gate":
            command.add_argument("--work", type=Path, required=True)
            command.add_argument("--task", action="append", required=True)
            command.add_argument(
                "--merge", choices=("last_writer", "three_way"), default="last_writer"
            )
    args = parser.parse_args()

    if args.command == "import":
        payload = run_import(args.dataset, args.cache)
    elif args.command == "merge-check":
        payload = run_merge_check(args.dataset, args.cache)
    else:
        payload = asyncio.run(run_gate(args.dataset, args.cache, args.work, args.task, args.merge))
    text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
