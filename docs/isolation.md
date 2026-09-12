# Isolation, tools and the lifecycle boundary

Spec §11, §12, §13. This document describes what agent isolation actually
guarantees, and is deliberately careful not to claim more (§87).

Status: describes the implementation as of Step 6 of `docs/PLAN.md`.

## The three layers

| Layer | Mechanism | What it guarantees |
|---|---|---|
| **L1 process** | Subprocess with the workspace as cwd and a scrubbed environment | No inherited environment, no ambient coordination state |
| **L2 path** | Every tool path resolved with `realpath` and checked for containment | Agents cannot reach peer workspaces **through the sanctioned tool API** |
| **L3 context** | Single typed injection point with per-call byte accounting | Evidence that C0 received zero coordination bytes |

L3 lands with the channel layer (Step 7); L1 and L2 are implemented.

### What L2 is not

**Windows has no `chroot` and no mount namespaces, so this is not a
filesystem jail.** A process that bypasses the tool API can still reach any
path its user token permits.

This was verified rather than assumed. A real Windows junction was created
inside an agent workspace pointing at a peer's, and:

- the junction exists and the OS honours it — a raw `open()` through it
  succeeds;
- every route through the tool API is refused.

That is precisely the boundary L2 draws. Docker (available here) is the
optional stronger jail for Linux and CI.

### Why containment is checked after resolution

A check on the path *string* would accept
`workspace/../../peer/secrets.py`, and a symlink planted inside the
workspace would defeat it entirely — the string looks innocent. Containment
is therefore evaluated on the `realpath`-resolved result, which collapses
`..`, follows symlinks and resolves junctions first.

Containment compares **path components**, not string prefixes. A sibling
directory named `agent_a_backup` starts with `agent_a` as text but is a
different directory; a `startswith` check would wrongly admit it.

### Attacks tested

All in `tests/unit/test_workspace_isolation.py`, and none of them skip on
this platform:

`..` traversal (five spellings) · absolute paths · symlink to a peer file ·
symlink to a peer directory · **Windows junction** (needs no privileges, so
it is the realistic attack) · sibling directory with a shared name prefix ·
empty paths

Refusals carry the requested path, the resolved path and the root, so a
denial is traceable evidence (§52) rather than an opaque error.

### One workspace per agent

Layout is `base/run_id/agent_id`, and workspaces are **siblings, never
nested** — nesting would make one agent's containment check automatically
admit the other's files.

Each agent gets its own copy of the task fixture. There is no shared
filesystem (§11), so any interference must travel through the coordination
channel where it can be measured.

## The tool API

Eleven operations, and no unrestricted host shell:

```
read_file    write_file   create_file  modify_file  delete_file
rename_file  list_files   run_command  run_tests    git_status   git_diff
```

`Toolbox` is constructed per agent, so a call cannot name another agent's
workspace — there is no parameter through which to express it.

`create_file` and `write_file` are separate so that "I am adding this" and "I
am replacing this" are different events (§16); the distinction matters when
attributing a conflicting edit. `modify_file` replaces an exact substring
rather than overwriting, because a conflicting write is only interesting if
we know it changed something specific.

### `run_command`

The dangerous one, treated accordingly:

- **Argument list, never a shell string.** `shell=True` would let an agent
  reach any path its token permits via `&&`, redirection or a subshell,
  voiding every isolation claim here.
- **Allowlist, not denylist** (`python`, `pytest`, `git`). A denylist is a
  promise to have imagined every dangerous command, which is not a promise
  this project can keep.
- **Scrubbed environment.** Only `PATH` and a few OS essentials pass through,
  plus `PYTHONHASHSEED=0`. Inheriting the operator's environment would carry
  API keys and proxy settings, and would make runs depend on whose shell
  launched them — breaking the §3 requirement that everything but the
  manipulated factors be held constant.
- **Bounded by a timeout**, recorded as data rather than raised (§22).

A non-zero exit code is returned, not raised: the harness decides what it
means for task success (§38), never the agent.

## The lifecycle boundary

```
agent -> pre-hook -> injection -> gate -> tool -> post-hook -> event -> relay
```

Two properties of that ordering carry the experiment.

**The gate runs before execution.** §20 requires that a denied write never
modifies the artifact. Checking afterwards — or after opening the file —
would already have truncated it. `test_a_denied_call_never_reaches_the_tool`
asserts the tool function is not called at all.

**Every call is recorded, including refused ones.** A denial that leaves no
event is invisible to the analysis, and C3's enforcement cost would be
understated. Denied and failed calls emit a `FAILURE` event carrying the
reason, the holder and the blocked path.

`DENIED` and `FAILED` are distinct outcomes. A denial is the coordination
mechanism working as designed; a failure is the tool breaking. Collapsing
them would make enforcement look like unreliability in the metrics (§44).

**Only mutating calls consult the gate.** Gating reads would make C3 differ
from C2 in more than write enforcement, which is the factor §20 defines.

### Gates per arm

```
C0, C1, C2   AllowAllGate
C3           ClaimGate
```

`gate_for_arm` raises for C3 without a registry: that combination would
produce an unenforced run indistinguishable from C2 while claiming to be
enforced, and the C2→C3 contrast would measure nothing with no error to
reveal it.

## The vertical slice, executed

The §71 slice runs end to end under all four arms. One scripted collision —
agent_a edits `schema.py` holding a claim; agent_b, having read the old
version, attempts the same file:

| Arm | Peer events observed | agent_b's write | agent_b's file afterwards |
|---|---|---|---|
| C0 | 0 | executed | clobbered |
| C1 | 2 | executed | clobbered |
| C2 | 2 | executed | clobbered |
| C3 | 2 | **denied** | **intact** |

Every arm produces a 4-event chain that verifies offline. Both factors are
independently observable: information in the C0→C2 row, enforcement in the
C2→C3 row.

Whether preventing the write *improves overall task success* is a separate
question the experiment measures rather than assumes (§74).
