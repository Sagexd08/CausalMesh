"""Import the real CooperBench dataset and run the section-37 gate on every feature pair.

    python scripts/import_cooperbench.py --dataset-root <CooperBench clone> \\
        --cache-dir <dir for base-repo fetches> --output-dir <dir for results>

Nothing is written into git-tracked paths by default: the cache and the
output both default to gitignored directories under `data/`. See
`causalmesh.tasks.cooperbench_batch` for what the verdicts do and do not
mean (scripted mock agents, offline line-multiset oracle, winner-take-all
contested-path merge).

Exit status is 0 when the batch ran to completion, whatever the verdicts and
however many pairs failed (a failure is data in the results file); 2 for a
usage or setup error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from causalmesh.tasks.cooperbench_batch import (  # noqa: E402
    BatchOptions,
    GitBaseResolver,
    discover_pairs,
    run_batch,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dataset-root", type=Path, required=True, help="CooperBench clone (or its dataset/ dir)"
    )
    parser.add_argument("--cache-dir", type=Path, default=REPO / "data" / "cooperbench_cache")
    parser.add_argument("--output-dir", type=Path, default=REPO / "data" / "cooperbench_out")
    parser.add_argument(
        "--repo", action="append", default=[], help="only this dataset repo dir (repeatable)"
    )
    parser.add_argument(
        "--task", action="append", default=[], help="only this task dir, e.g. task1621 (repeatable)"
    )
    parser.add_argument("--max-pairs", type=int, default=None)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument(
        "--force", action="store_true", help="redo pairs that already have a terminal result"
    )
    parser.add_argument("--keep-workspaces", action="store_true")
    parser.add_argument(
        "--contested-merge",
        choices=("last_writer", "three_way"),
        default="last_writer",
        help="how a path both features edit is integrated (default keeps winner-take-all)",
    )
    parser.add_argument("--list", action="store_true", help="print the selected pairs and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = BatchOptions(
        dataset_dir=args.dataset_root,
        output_dir=args.output_dir,
        repetitions=args.repetitions,
        only_repos=frozenset(args.repo),
        only_tasks=frozenset(args.task),
        max_pairs=args.max_pairs,
        force=args.force,
        keep_workspaces=args.keep_workspaces,
        jobs=max(1, args.jobs),
        contested_merge=args.contested_merge,
    )
    try:
        pairs = discover_pairs(options)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.list:
        for key in pairs:
            print(key.pair_id)
        print(f"{len(pairs)} pair(s)")
        return 0
    if not pairs:
        print("error: no pairs selected", file=sys.stderr)
        return 2

    document = run_batch(options, resolver=GitBaseResolver(args.cache_dir), progress=print)
    summary = document["summary"]
    print("")
    print(
        f"pairs: {summary['pairs_total']}  gated: {summary['gated']}  "
        f"sensitive: {summary['sensitive']}  not sensitive: {summary['not_sensitive']}  "
        f"skipped: {summary['skipped']}  failed: {summary['failed']}"
    )
    for reason, count in summary["reasons"].items():
        print(f"  {count:4d}  {reason}")
    print(f"results: {options.output_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
