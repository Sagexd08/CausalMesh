# Security policy

## Reporting a vulnerability

Report privately through GitHub's
[security advisory form](https://github.com/Sagexd08/CausalMesh/security/advisories/new),
not as a public issue.

Include what you ran, what you observed, and what the impact is. A working
proof of concept is welcome and not required.

You should get an acknowledgement within a week. This is a small project
without a funded security team, and saying that plainly is better than
implying a response time nobody is staffed to meet.

## What is in scope

This project's claims are cryptographic and enforcement-related, so the
findings that matter most are the ones that break those claims:

- **Forging or altering a chain without detection.** The chain is Ed25519
  over hash-linked events. Any way to change, reorder or remove an event
  while `causalmesh verify` still reports VERIFIED is the highest-severity
  finding this project can receive.
- **Bypassing the claim registry.** Two agents holding a valid exclusive
  lease on the same resource at the same instant, across processes.
- **Bypassing the gate.** Performing an action the contract refuses, in a
  way the gate does not see. There is a recorded instance of this class in
  `docs/backlog.md`: a channel that reached around the coordination boundary
  and passed every test.
- **Escaping workspace isolation.** Reading or writing a peer agent's
  workspace during a C0 run, by relative path, absolute path, symlink,
  junction or traversal.
- **Signing key exposure.** Any path by which a private key reaches an
  artifact, a log, or the chain.

## What is out of scope

- **Running untrusted agent code.** The tool executes coding agents against
  a repository. That is the function, not a vulnerability. Isolation limits
  the blast radius and is documented rather than claimed absolute.
- **Windows C0 isolation being weaker than POSIX.** There is no chroot on
  Windows, so isolation there is layered rather than absolute. This is
  stated in `docs/isolation.md` and in the whitepaper's limitations section.
  A report that it is weaker is a duplicate of a known limitation; a report
  that it fails in a way the documentation does not describe is in scope.
- **Denial of service by resource exhaustion** on a machine the reporter
  controls.
- **Findings in the marketing site** that do not affect the substrate.

## Known limitations, stated rather than found

These are documented and deliberate. They are listed here so a reviewer can
tell a known trade-off from a new finding.

| Limitation | Where it is recorded |
|---|---|
| C0 isolation is layered, not absolute, on Windows | `docs/isolation.md` |
| A run driven by a hosted model is not bit-reproducible | `docs/adapters.md`, §84 |
| Provenance is outside the signed payload by design | `docs/security.md` |
| The policy plane is built but not yet wired into the run loop | `docs/backlog.md` |
| No hosted model has been executed through any adapter | `docs/backlog.md` |

## Supported versions

Pre-1.0. Only `main` receives fixes. There are no maintained release
branches yet, and pretending otherwise would be a promise nobody is keeping.
