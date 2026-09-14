# Launch post — X / Twitter

Written for: developers on X who build with AI coding agents. Assumes no
knowledge of the project. Every number below resolves to a real artifact in
`data/raw/pilot_landing/`.

---

## Option A — the single post (recommended)

Fits the 280-character limit as the opener; the rest is the thread.

> **Post 1 (263 chars)**
>
> Building CausalMesh.
> Coordination you can prove.
>
> A verification substrate for AI agent fleets — every action signed, every
> refusal has a reason, every change has evidence.
>
> Last week my enforcement counter reported 0 blocks.
>
> Enforcement was working perfectly. 🧵

---

## The thread

**2/**
The bug: denials were recorded by one code path. The gate that actually
refuses writes was a different one.

So every block the system performed was invisible to the method whose own
docstring called it "the core enforcement measurement."

**3/**
A real run reported: 2 claims held, 0 denials.

Both numbers were wrong in the worst way — not crashed, not empty. Confident.

If I'd shipped it, "enforcement never blocked anything" goes in the results
table as a finding. It was a defect.

**4/**
The lesson I keep re-learning:

A metric that cannot observe its own subject doesn't fail loudly. It reports
zero, and zero looks like data.

Test that your instruments can see the thing they measure. Not just that they
return a number.

**5/**
Second one from the same week. I fed peer events straight into a model's
context, bypassing the coordination channel.

All 21 adapter tests passed.

That defect would have silently broken the entire experiment — agents knowing
things that no accounting recorded.

**6/**
Why that one is worse: every test I'd written checked that something happened
correctly.

Nothing checked that nothing *else* happened.

The guarantees most worth testing are properties of what your code does **not**
do. Those are exactly the ones no test naturally covers.

**7/**
What CausalMesh is actually for.

Put 4 coding agents on one repo and they interfere. Stale reads, duplicated
work, silent overwrites. Every one is a coordination failure, not a capability
failure — each agent did competent work.

**8/**
Systems that fix this do two things at once: they *tell* agents what peers are
doing, and they *prevent* agents from conflicting.

Because those always ship together, nobody knows which one is doing the work.

They cost very different things.

**9/**
So the experiment runs four arms with one variable changed at a time:

C0 — no peer info, no enforcement
C1 — full transcripts
C2 — bounded metadata
C3 — same info as C2 + enforced write claims

C2→C3 is enforcement alone. Same channel object, same bytes.

**10/**
24 runs so far. Real numbers, including the ones I don't like:

C0: 0/6 passed, 0 B
C1: 6/6, 361 B/run
C2: 6/6, 196 B/run
C3: 3/6, 196 B/run

**11/**
C2 matched full transcripts at 46% less coordination cost.

And C3 — the enforcement arm — did *worse*. 0/3 on the contested-file task.

That's not the result I was hoping for. It's the one the runs produced, so it's
the one that's published.

**12/**
Every run writes a hash chain, signed Ed25519. 24/24 verify offline with the
relay stopped, from exported artifacts, in a separate directory.

A refused write records actor, path, and holder. You can check the denied file
is byte-identical.

**13/**
Status, plainly: ~40% built.

865 tests pass. Protocol, crypto, claims, relay, channels, tasks, scheduler and
adapters are done.

Metrics, analysis, reporting and the CLI are not. No hosted model has driven it
yet. `docs/backlog.md` lists every gap with a reason.

**14/**
Next week: the CLI, so this is something you can actually run rather than read
about.

Then a real model in the loop.

If you run fleets of coding agents and have opinions about what breaks, I want
to hear them.

[repo link]

---

## Notes on claims

Every figure is checkable:

- `865 tests` — `pytest` output, 2026-09-14
- `24 runs`, arm figures — `docs-site/lib/landing/results.json`, generated from
  `data/raw/pilot_landing/`
- `46%` — 196 B / 361 B = 0.543. C2 costs 54% of C1, i.e. **46% less**. Say
  "46% less" or "46% cheaper" — never "46% of", which is a different number.
  This matches the landing page's "46% under transcript".
- `21 adapter tests` — `tests/integration/test_model_adapters.py`
- `~40%` — 16 of 22 subsystems have code; 6 are empty (cli, metrics, analysis,
  reporting, provenance, adversarial)

Do not post a number that is not in this list.
