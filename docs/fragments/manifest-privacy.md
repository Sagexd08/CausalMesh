### Manifests no longer record a hostname or username by default

**Status: built.** Follows up "The pilot manifest named a person's host and
username" in `docs/backlog.md`, whose last paragraph ("The default that caused
it") described this change as not built.

**Behaviour change.** `Environment.capture(root)` no longer records
`platform.node()` or the OS username. By default `machine_id` and `operator_id`
are each one of:

- `keyed:` plus 16 hex digits, the first 64 bits of an HMAC-SHA-256 over the
  value, keyed with a random 256-bit secret. The hostname and the username are
  derived under separate labels, so neither can be matched to the other.
- `unknown`, when no key can be kept (not a git checkout, the git directory is
  unwritable, the key file is malformed) or the value itself is absent. It is
  never a bare unsalted hash: a hostname or username comes from a small space
  and could be enumerated against one.

The secret is generated on first use at
`<git-common-dir>/causalmesh/identity.key` (mode 0600, created with `O_EXCL`).
It is inside `.git`, so it is never tracked or pushed, and every worktree of one
clone shares it. No dependency was added.

`Environment.capture(root, record_host=True)`, `causalmesh manifest write
--record-host` and `causalmesh experiment run --record-host` record the real
values. `manifest write` prints a note when it is used, and its `--json` output
carries `host_recorded`. `experiment run` was in scope too: it calls the same
capture and copies both fields into each run's envelope.

Consumers checked: `provenance/manifest.py` (passes the flag through),
`cli/commands_audit.py` (prints only the git commit, and echoes
`manifest.environment` into the audit report, so it shows the digest or
`unknown` and never a value it did not read), `cli/commands_experiment.py`,
`tasks/runner.py` and `agents/base.py` (carry the two strings through untouched),
`verify` and `doctor` (read neither field). The frontend docs do not describe
these fields. Existing manifests are unchanged: `manifest.check` hashes the
listed artifacts, not the manifest, and the tracked manifest already reads
`unknown`. `causalmesh audit` could not be run against the pilot collection in
the worktree this was built in, because `data/raw/` is untracked and absent
there.

Tests: `tests/unit/test_provenance.py::TestIdentityPrivacy` (sentinel
host and user absent by default, present with the opt-in; the real hostname and
username of the machine running the suite absent from a default manifest; the key
stays in `.git` with mode 0600; no key or a corrupt key gives `unknown`) and
`tests/integration/test_cli.py::TestManifestPrivacy` (the same through the CLI).

**What remains.**

- **History is untouched.** The original hostname and username are still in
  `54cd3f4`, `743a69e` and `9d258f6`. This change stops new publication and does
  nothing about those; rewriting them is still the repository owner's decision.
- **A digest compares only within one clone.** The same machine cloned twice
  has two keys and so two digests, and a fresh clone cannot reproduce an earlier
  digest. "Different digest" means "different machine or different clone", never
  "different person", and a digest is not evidence that two manifests came from
  one machine unless they came from one clone. Where that is not enough, there is
  no answer short of recording the real value.
- **Old manifests written with the real values stay as they are.** Nothing
  rewrites or scans for them. Anyone who used `--record-host` and committed the
  result has published the values again; the flag is a choice, not a safeguard.
- **`platform` and `python_version` are still recorded in the clear** ("Windows
  11 (AMD64)", "3.13.5"). They describe a class of machine, not a person, and
  are what makes a run's conditions checkable, but a rare configuration narrows
  who could have written a manifest.
- **The fallback is uneven.** A checkout without a usable `.git` gets `unknown`
  for both, so two such manifests cannot be told apart at all.
- **The key is not rotated and not backed up.** Deleting it changes every later
  digest; nothing warns that earlier manifests no longer match.
- **No test scans the tracked tree.** The suite checks what is written, not what
  is committed; a manifest produced with `--record-host` and committed is not
  caught.
