# Fragment: token expiry, revocation and rotation (track TOKEN-LIFECYCLE)

For the integrator to fold into `docs/backlog.md` (replacing the last
sentences of "Identity on the HTTP surface: bound tokens built, proof not" and
the "no rotation, expiry or revocation" clause), `docs/security.md` and
`CHANGELOG.md`. `docs/backlog.md` and `CHANGELOG.md` were not edited.

## Backlog text

### Token lifecycle: expiry, revocation, rotation built; proof still not

**Status: built (2026-09-30).** A token can expire, be revoked and be rotated
without restarting `serve`, and the chain says which credential acted.

- **Expiry.** `--agent-token AGENT=TOKEN@EXPIRY` (ISO 8601 such as
  `2026-12-31T00:00:00Z`, or unix seconds), `--api-token-expires`, or `expires:`
  in the tokens file. A credential is valid while `now < expires_at`: at the
  expiry instant it is already refused. Past it, the request gets 401 "Token
  expired". Expiry is judged on every request, so nothing outlives it, including
  a set kept after a failed reload. Times without a zone are UTC. The clock is
  injectable (`create_app(clock=...)`).
- **Tokens file.** `--tokens-file PATH` (also `CAUSALMESH_TOKENS_FILE`), YAML or
  JSON: `tokens:` is a list of `{id, token, agent?, expires?}`. It is re-read
  when its mtime, size or inode changes (one `stat` per request), and on
  SIGHUP on POSIX. Deleting an entry makes that token fail on the next request;
  adding one takes effect on the next. Flag tokens stay valid beside the file.
- **Rotation.** Several entries may name one agent. Add the new token, move
  the clients, delete the old entry: both are valid in between. More than two
  live tokens for one agent logs a warning.
- **A bad reload keeps the last good set.** Malformed YAML, a missing or
  unreadable file, a bad entry, a duplicate label or token, an agent with no
  key in this session, or a permissive mode all leave the credentials as they
  were, and log one warning per distinct failure that carries no file content
  and no token. Failing closed would lock every client out over a typo; failing
  open is never acceptable, and keeping the old set is neither. Its cost: a
  token the operator meant to revoke in that same broken edit stays valid until
  the file is fixed or the token expires. To revoke everything on purpose write
  `tokens: []`. A bad file at start-up is an error: there is no good set to keep.
- **Permissions.** On POSIX a tokens file with any group or other bit set is
  refused, at start-up and on reload, with the `chmod 600` to run. On Windows
  mode bits mean nothing, so nothing is checked; restrict the file with an ACL.
- **Record.** Chat and `/execute` events carry `credential_id` beside
  `identity_source`: the operator's label for the credential (`id:` in the
  file; `agent-token:AGENT` and `api-token` for plain flags). It is signed and
  reproducible, because it comes from configuration and not from the secret,
  a clock or a random id, and it is never the token or a digest of it (a digest
  of a guessable token could be tested offline). Labels are limited to
  `[A-Za-z0-9._:-]`, 64 characters, and a label that contains its own token
  is refused. With authentication off the field is absent, not `none`.
- **Logs.** No token is logged. Reload and refusal messages name labels,
  counts and line numbers. The log redactor (`RedactingFormatter`) now accepts
  a callable, and `serve` hands it the credential store, so a token added by a
  reload is scrubbed from the next line and a revoked one stays scrubbed.

**What remains.**

- Tokens are still shared secrets over whatever transport the operator
  provides, and the server still holds every agent's signing key. Expiry and
  revocation shrink the window in which a leaked token is useful; they do not
  make a token prove anything to someone who did not see the request. Per-agent
  signing keys held by the agents, or mutual TLS, are still undecided protocol
  questions.
- Revocation is per process and needs the file to be reachable. There is no
  admin endpoint and no shared revocation list, so several processes must all
  read the same file.
- A detected edit within the timestamp granularity relies on a byte compare for
  two seconds after each read. A file changed in place, to the same size, with
  the old mtime restored, more than two seconds after it was read, is not seen
  until SIGHUP (POSIX) or the next change. There is no SIGHUP equivalent on
  Windows.
- SIGHUP reloads only when `--tokens-file` is set; otherwise the default action
  (terminate) is untouched. With a file set, a terminal hang-up reloads instead
  of stopping the process.
- A keep-last-good set is silent to clients. There is no metric or health
  signal that the file is currently unreadable, only the log warning.
  `/health` and `/readyz` are unauthenticated and deliberately say nothing about it.
- A token containing `@` followed by something that looks like a date cannot be
  given as `--agent-token` (it would be read as an expiry). Put it in the file.
- The rate-limit table is keyed on a digest of each token that authenticated and
  is never pruned, so a long-lived process that rotates many tokens grows it a
  little per rotation.
- The redactor works by value, so a token shorter than four characters is not
  scrubbed (as before); `serve` warns under 16.

## Files

- `src/causalmesh/server/credentials.py` (new): `Credential`, `CredentialStore`,
  `parse_expiry`, `split_token_expiry`, the file parser and its rules.
- `src/causalmesh/server/auth.py`: the checker compares against the store;
  `Principal.label`; 401 "Token expired".
- `src/causalmesh/server/app.py`: `credentials=`, `tokens_file=`, `clock=`;
  `app.state.credentials`; `credential_id` in both event paths.
- `src/causalmesh/server/observability.py`: `RedactingFormatter` and
  `configure_logging` accept a callable secret source.
- `src/causalmesh/cli/commands_serve.py`: `--tokens-file`,
  `--api-token-expires`, `@EXPIRY`, SIGHUP.
- `tests/server/test_token_lifecycle.py`, `tests/integration/test_serve_tokens.py`.

## Tests

Expiry boundary (valid at `expires_at - 1ms`, refused at `expires_at`), expiry of
a file credential with no reload, revocation, addition and rotation overlap after
reload, an edit inside timestamp granularity, SIGHUP / `request_reload`, a bad
reload keeping the last good set (parametrised over thirteen malformed and invalid
files, each asserting nothing leaked to the log), a deleted file, recovery, a
kept set still honouring expiry, permissive modes at start-up and on reload, no
mode check where mode bits do not apply, the constant-time spy (every credential
compared, expired ones too, no early exit, still true after a reload), no secret
in logs, errors or the chain (including digests of the token), the redactor
learning reloaded tokens, `credential_id` on chat, `/execute` and denied calls,
absent with auth off, identical for a rotated token under one label, the chain
still verifying, and the CLI wiring including SIGHUP and its unwiring.
Mutation-checked: an early `break` in the compare loop, `>` for `>=` at the
expiry, and a reload that swallows a parse error each fail the suite.
