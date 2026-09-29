"""`causalmesh agreement` — kappa over an operator-supplied judgement file (§53).

This command has no notion of "the latest experiment": kappa is computed
from *human* judgements, and this project has none of its own to point at
(`docs/backlog.md`, "Multi-rater kappa coding (§53)"). An operator supplies
a JSON or YAML file of `RaterJudgement` records — coded by real raters, off
this machine, on their own schedule — and this command is the arithmetic
over whatever they hand it. It never reads `data/raw/` itself.

Two raters routes to Cohen's kappa; three or more routes to Fleiss'. Which
one ran, and why, is always stated rather than left for the operator to
infer from the number alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from causalmesh.cli._output import Exit, emit, fail, note, out_console, table

app = typer.Typer(help="Compute inter-rater kappa over a judgement file.", no_args_is_help=True)


def _load_records(path: Path) -> list[dict[str, Any]]:
    """Parse a judgement file as JSON or YAML, by its own content.

    Extension-sniffing would guess wrong the moment someone names a YAML
    file `.json` by habit; this tries JSON first (the stricter format, so a
    YAML document that happens to parse as JSON is rare) and falls back to
    YAML, matching the tolerant-input spirit of `policy check --stdin`.
    """
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        import yaml

        payload = yaml.safe_load(text)

    if isinstance(payload, dict) and "judgements" in payload:
        payload = payload["judgements"]
    if not isinstance(payload, list):
        raise ValueError(
            "expected a JSON/YAML list of judgement records, or an object with a "
            f"'judgements' list; got {type(payload).__name__}"
        )
    return payload


def agreement_command(
    judgements_file: Annotated[
        Path,
        typer.Argument(help="JSON or YAML file of rater judgements (item_id, rater_id, category)."),
    ],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Compute Cohen's (2 raters) or Fleiss' (3+ raters) kappa from a judgement file.

    Exits `USAGE` on a malformed file, `ERROR` on a file that cannot be
    read, and `FAILED` on well-formed judgements that fail a precondition
    (an unknown category, an unequal rater count per item) — the same
    three-way split `causalmesh policy check` already uses for "the input
    was wrong" versus "the input was fine and the answer is no".
    """
    from causalmesh.analysis.agreement import (
        AgreementError,
        FailureModeCategory,
        RaterJudgement,
        cohens_kappa,
        fleiss_kappa,
    )

    if not judgements_file.is_file():
        fail(f"no such file: {judgements_file}")
        raise typer.Exit(Exit.USAGE)

    try:
        records = _load_records(judgements_file)
    except (ValueError, OSError) as exc:
        fail(f"could not read {judgements_file}: {exc}")
        raise typer.Exit(Exit.USAGE) from exc

    try:
        judgements = tuple(RaterJudgement.from_dict(record) for record in records)
    except AgreementError as exc:
        fail(str(exc), hint=f"Known categories: {', '.join(str(c) for c in FailureModeCategory)}")
        raise typer.Exit(Exit.USAGE) from exc

    if not judgements:
        fail("no judgements in file", hint="Nothing to compute kappa over.")
        raise typer.Exit(Exit.USAGE)

    rater_count = len({j.rater_id for j in judgements})
    try:
        if rater_count == 2:
            result = cohens_kappa(judgements)
        elif rater_count >= 3:
            result = fleiss_kappa(judgements)
        else:
            fail(
                f"only one rater ({next(iter({j.rater_id for j in judgements}))!r}) in "
                f"{judgements_file}",
                hint="Kappa needs at least two raters coding the same items.",
            )
            raise typer.Exit(Exit.USAGE)
    except AgreementError as exc:
        fail(str(exc))
        raise typer.Exit(Exit.FAILED) from exc

    payload = {
        "label": "PILOT",
        "result": result.to_dict(),
        "source_file": str(judgements_file),
    }

    if not emit(payload, as_json=as_json):
        rendered = table(
            f"{judgements_file.name} - inter-rater agreement  [PILOT]",
            ["method", "raters", "items", "observed", "expected", "kappa"],
        )
        rendered.add_row(
            result.method,
            str(result.n_raters),
            str(result.n_items),
            f"{result.observed_agreement:.3f}",
            f"{result.expected_agreement:.3f}",
            f"{result.kappa:.3f}",
        )
        out_console.print(rendered)
        note(
            "computed from the judgements in this file only; no run in this repository "
            "has been coded by real raters (docs/backlog.md, section 'Multi-rater kappa "
            "coding (S53)')"
        )

    raise typer.Exit(Exit.OK)
