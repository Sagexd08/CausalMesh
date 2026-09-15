<!--
Say what changed and why it was wrong before. The commit log is where this
project keeps the reasoning for decisions that are not obvious from the
diff, and most of the interesting ones are not.
-->

## What this changes

## Why

<!--
The rules below are not style preferences. Each is load-bearing for a claim
the project makes, and each has been broken at least once. CONTRIBUTING.md
has the full reasoning.

Delete the lines that do not apply to your change.
-->

## Checks

- [ ] `ruff check src tests` passes
- [ ] `ruff format src tests` is clean
- [ ] `pytest -q` passes
- [ ] Nothing non-reproducible entered the signed chain (no hostname, wall
      clock, absolute path or random id inside a signed payload)
- [ ] Any new counter over run artifacts treats an absent field as
      `unknown` rather than `0`
- [ ] Any new refusal is returned as data rather than raised
- [ ] Money is `Decimal`, rejected at the call site if it arrives as a float
- [ ] `docs/backlog.md` records anything this falls short of
- [ ] Terminal output is ASCII, or asks the console what it can encode

## Evidence

<!--
If this changes a measurement, a rendered surface, or anything a reader
would check, show it rather than describing it. A run artifact, a terminal
capture, or a screenshot.
-->
