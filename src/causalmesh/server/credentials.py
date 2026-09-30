"""The credentials the server accepts, how long they last, and how they change.

`auth.py` decides what a *request* proves. This module holds the set of
secrets a request is checked against, and is what makes that set something an
operator can change while the server runs.

**Credential.** A token, the agent it is bound to (or none: the operator's
unbound token), an optional expiry and a *label*. The label is chosen by the
operator, is recorded in the signed chain as `credential_id`, and is how
evidence says which credential acted. It is never derived from the token: a
hash of a token in evidence could be tested against guesses offline, and the
evidence is meant to be handed to people who do not hold the secrets. Labels
are restricted to `[A-Za-z0-9._:-]`, at most 64 characters, and may not be the
token itself, so a pasted secret is refused rather than signed into the chain.

**Expiry.** `expires_at` is seconds since the Unix epoch. A credential is valid
while `now < expires_at`: at the expiry instant it is already expired. The
clock is injected (`time.time` by default) so tests do not sleep. Expiry is
judged at request time, so a credential never outlives it, including one that
belongs to the last good set after a failed reload.

**The tokens file.** `--tokens-file PATH` names a YAML or JSON file::

    version: 1
    tokens:
      - id: coder-2026-09          # label: required, unique, goes in evidence
        token: "<long random>"     # required
        agent: coder               # optional; absent means unbound (asserts)
        expires: 2026-12-31T00:00:00Z   # optional: ISO 8601, or unix seconds

Naive times (no zone) are read as UTC. Several entries may name one agent:
that is the rotation overlap, so add the new token, move the clients, then
delete the old entry. Two live tokens per agent is the intended shape; more
logs a warning.

**Reload.** The file is checked on every request with one `stat` (mtime, size,
inode) and re-read when that changed, or when `request_reload()` was called
(`serve` does so on SIGHUP, POSIX only). Removing an entry therefore makes that
token fail on the very next request. A timestamp as recent as the last load
could hide an edit on a coarse-mtime filesystem, so a file modified within two
seconds of being read is compared byte for byte.

**A bad reload keeps the last good set.** Malformed YAML, a missing file, a
bad entry, a duplicate label or token, an agent the session has no key for, or
a permissive mode all leave the credentials as they were and log a warning
that names the problem but carries no file content and no token. Failing
closed on a parse error would lock every client out over a typo, and failing
open (accepting anything, or dropping all checks) is never acceptable. The
cost is stated plainly: until the file is fixed, a token the operator meant to
revoke in that edit is still accepted (until its own expiry). To revoke
everything on purpose, write `tokens: []`: that parses, and means nothing is
valid. A bad file at start-up is an error, since there is no good set to keep.

**File permissions.** On POSIX a tokens file readable or writable by group or
other (`mode & 0o077`) is refused, at start-up and on reload, with the `chmod
600` to run. Windows mode bits are not access control, so nothing is checked
there and the operator must restrict the file with an ACL.

Nothing here is logged with a token in it. Messages name labels, counts, line
numbers and the kind of error, never a value taken from a file.
"""

from __future__ import annotations

import hmac
import logging
import math
import os
import re
import stat
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

__all__ = [
    "MAX_TOKENS_FILE_BYTES",
    "Credential",
    "CredentialStore",
    "agent_token_label",
    "parse_expiry",
    "split_token_expiry",
]

LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
MAX_TOKENS_FILE_BYTES = 1_048_576

# Unix seconds must be 9-11 digits (1973 to 5138). Shorter digit runs are far
# more likely to be part of a token than a date, and `split_token_expiry`
# relies on that to keep an `@` inside a token a token.
_UNIX = re.compile(r"^\d{9,11}$")
_ISO_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}.*)?$")
_RACY_NS = 2_000_000_000
# Windows mode bits are not access control, so they are not consulted there.
_ENFORCE_FILE_MODE = os.name == "posix"
_ENTRY_KEYS = frozenset({"id", "token", "agent", "expires"})


@dataclass(frozen=True, slots=True)
class Credential:
    """One secret the server accepts. `repr` never shows the token."""

    label: str
    token: str = field(repr=False)
    agent_id: str | None = None
    expires_at: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not LABEL_PATTERN.fullmatch(self.label):
            raise ValueError(
                "a credential label must be 1-64 characters of letters, digits and . _ : -, "
                "starting with a letter or digit"
            )
        if not isinstance(self.token, str) or not self.token.strip():
            raise ValueError(f"the token for credential {self.label!r} must be non-blank")
        # A pasted secret as a label is the mistake worth catching. Tokens shorter
        # than 12 characters are weak anyway (`serve` says so) and would match
        # ordinary labels by accident (`tok` in `api-token`), so they are not checked.
        if len(self.token) >= 12 and self.token in self.label:
            raise ValueError(
                f"the label of credential {self.label!r} contains its token; "
                "a label goes into the evidence chain, so it must not be a secret"
            )
        if self.agent_id is not None and not self.agent_id.strip():
            raise ValueError(f"credential {self.label!r} needs a non-blank agent id")
        if self.expires_at is not None and not math.isfinite(self.expires_at):
            raise ValueError(f"credential {self.label!r} has a non-finite expiry")

    def expired(self, now: float) -> bool:
        """True from the expiry instant onwards."""
        return self.expires_at is not None and now >= self.expires_at


def parse_expiry(value: object) -> float:
    """Seconds since the epoch from an ISO 8601 string, unix seconds or a YAML date.

    Naive times are UTC. Raises `ValueError` without echoing the value.
    """
    if isinstance(value, bool):
        raise ValueError("an expiry must be an ISO 8601 time or unix seconds")
    if isinstance(value, int | float):
        seconds = float(value)
    elif isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        seconds = moment.timestamp()
    elif isinstance(value, date):
        seconds = datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp()
    elif isinstance(value, str):
        text = value.strip()
        if _UNIX.fullmatch(text):
            seconds = float(text)
        else:
            try:
                moment = datetime.fromisoformat(text)
            except ValueError:
                raise ValueError("an expiry must be an ISO 8601 time or unix seconds") from None
            seconds = (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()
    else:
        raise ValueError("an expiry must be an ISO 8601 time or unix seconds")
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("an expiry must be a positive, finite time")
    return seconds


def split_token_expiry(text: str) -> tuple[str, float | None]:
    """Split `TOKEN[@EXPIRY]`, for `--agent-token AGENT=TOKEN@EXPIRY`.

    Only the text after the *last* `@` is considered, and only when it is
    shaped like an expiry (9-11 digits, or `YYYY-MM-DD` optionally followed by
    a time). Anything else leaves the `@` inside the token, so tokens that
    contain one keep working. A suffix that has the shape but is not a real
    time (`2026-13-45`) is refused rather than guessed at. A token that really
    ends in `@` plus a date-like string belongs in `--tokens-file`.
    """
    head, separator, tail = text.rpartition("@")
    if not separator or not head:
        return text, None
    candidate = tail.strip()
    if not (_UNIX.fullmatch(candidate) or _ISO_SHAPE.fullmatch(candidate)):
        return text, None
    try:
        return head, parse_expiry(candidate)
    except ValueError:
        raise ValueError(
            "the text after the last '@' looks like an expiry but is not a valid one "
            "(ISO 8601 like 2026-12-31T00:00:00Z, or unix seconds)"
        ) from None


def agent_token_label(agent: str) -> str:
    """The default label for an agent's token: `agent-token:AGENT`, made label-safe.

    Agent ids were never restricted to the label alphabet, so a legacy
    `--agent-token "my agent=..."` must keep working; characters outside it
    become `_`. Two ids that collapse to one label are told apart by
    `CredentialStore.from_config`.
    """
    return "agent-token:" + re.sub(r"[^A-Za-z0-9._:-]", "_", agent)[:48]


def _check_set(
    credentials: Sequence[Credential], known_agents: Collection[str] | None
) -> dict[str, Credential]:
    """Validate a whole set; return it by label. Raises `ValueError`, never echoing a token."""
    labels: dict[str, Credential] = {}
    tokens: set[str] = set()
    for cred in credentials:
        if cred.label in labels:
            raise ValueError(f"two credentials share the label {cred.label!r}")
        if cred.token in tokens:
            raise ValueError(f"credential {cred.label!r} has the same token as another credential")
        labels[cred.label] = cred
        tokens.add(cred.token)
    if known_agents is not None:
        unknown = sorted({c.agent_id for c in credentials if c.agent_id} - set(known_agents))
        if unknown:
            raise ValueError(
                f"credentials name agents this session has no key for: {unknown}; "
                "declare them under `roles` in causalmesh.yaml"
            )
    return labels


def _parse_tokens_file(data: bytes) -> list[Credential]:
    """Credentials from the bytes of a tokens file. Messages never carry file content."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("the file is not UTF-8 text") from None
    try:
        document: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        # `str(exc)` quotes the offending line, which may be a token.
        mark = getattr(exc, "problem_mark", None)
        where = f" near line {mark.line + 1}" if mark is not None else ""
        raise ValueError(f"the file is not valid YAML or JSON{where}") from None
    if not isinstance(document, dict):
        raise ValueError("the file must be a mapping with a `tokens` list")
    extra = set(document) - {"version", "tokens"}
    if extra:
        raise ValueError(f"unknown top-level key(s): {sorted(str(k) for k in extra)}")
    if document.get("version", 1) != 1:
        raise ValueError("unsupported `version` (this server reads version 1)")
    entries = document.get("tokens")
    if not isinstance(entries, list):
        raise ValueError("`tokens` must be a list (write `tokens: []` to revoke everything)")
    parsed: list[Credential] = []
    for index, entry in enumerate(entries):
        where = f"tokens[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a mapping")
        stray = set(entry) - _ENTRY_KEYS
        if stray:
            raise ValueError(f"{where} has unknown key(s): {sorted(str(k) for k in stray)}")
        label, token, agent = entry.get("id"), entry.get("token"), entry.get("agent")
        if not isinstance(label, str):
            raise ValueError(f"{where}.id must be a text label")
        if not isinstance(token, str):
            raise ValueError(f"{where}.token must be text (quote it in YAML)")
        if agent is not None and not isinstance(agent, str):
            raise ValueError(f"{where}.agent must be text")
        expires = None
        if entry.get("expires") is not None:
            try:
                expires = parse_expiry(entry["expires"])
            except ValueError as exc:
                raise ValueError(f"{where}.expires: {exc}") from None
        try:
            parsed.append(Credential(label, token, agent, expires))
        except ValueError as exc:
            # Credential's messages name the label at most; `where` says which entry.
            raise ValueError(f"{where}: {exc}") from None
    return parsed


class CredentialStore:
    """The live set of credentials, optionally backed by a tokens file.

    `static` credentials (from flags, or `create_app` arguments) are always
    part of the set; the file adds to them. Readers take a reference to an
    immutable tuple, so a reload swaps the whole set at once and a request
    never sees half of one.
    """

    def __init__(
        self,
        static: Sequence[Credential] = (),
        *,
        tokens_file: str | os.PathLike[str] | None = None,
        clock: Callable[[], float] = time.time,
        known_agents: Collection[str] | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._static = tuple(static)
        self._path = Path(tokens_file) if tokens_file is not None else None
        self._clock = clock
        self._known_agents = None if known_agents is None else frozenset(known_agents)
        # Authentication is on whenever anything was configured; `enabled=True`
        # with no credentials is the "refuse everything" guard.
        self.enabled = bool(self._static or self._path is not None) if enabled is None else enabled
        _check_set(self._static, self._known_agents)
        self._lock = threading.Lock()
        self._reload_requested = False
        self._signature: tuple[int, int, int] | None = None
        self._loaded_bytes: bytes | None = None
        self._loaded_at_ns = 0
        self._last_error: str | None = None
        self._retired: set[str] = set()
        self._current: tuple[Credential, ...] = self._static
        if self._path is not None:
            try:
                self._load(initial=True)
            except ValueError as exc:
                raise ValueError(f"tokens file {self._path}: {exc}") from None

    # -- reading ---------------------------------------------------------

    def lookup(self, presented: bytes) -> tuple[Credential | None, bool]:
        """The credential `presented` matches, and whether it has expired.

        Every credential is compared, expired or not, and the loop never
        stops early, so the time taken does not say which one matched or how
        much of a guess was right.
        """
        self.refresh()
        now = self._clock()
        matched: Credential | None = None
        for cred in self._current:
            if hmac.compare_digest(presented, cred.token.encode("utf-8")):
                matched = cred
        if matched is None:
            return None, False
        return matched, matched.expired(now)

    def credentials(self) -> tuple[Credential, ...]:
        """The credentials in force now (labels and agents are not secret; tokens are)."""
        return self._current

    def secrets(self) -> tuple[str, ...]:
        """Every token this process has held, revoked ones included, for log redaction.

        A revoked token is still a secret the operator meant to keep out of
        logs, and a client that keeps presenting it can put it in an error.
        """
        return tuple({c.token for c in self._current} | self._retired)

    # -- changing --------------------------------------------------------

    def request_reload(self) -> None:
        """Ask for a re-read on the next request. Safe from a signal handler."""
        self._reload_requested = True

    def refresh(self) -> None:
        """Re-read the tokens file if it changed. Never raises."""
        if self._path is None:
            return
        try:
            try:
                st = os.stat(self._path)
                signature: tuple[int, int, int] | None = (st.st_mtime_ns, st.st_size, st.st_ino)
            except OSError:
                signature = None
            forced = self._reload_requested
            if not forced and signature == self._signature:
                racy = (
                    signature is not None
                    and self._loaded_at_ns - _RACY_NS
                    < signature[0]
                    <= self._loaded_at_ns + _RACY_NS
                )
                if not racy:
                    return
            with self._lock:
                self._reload_requested = False
                try:
                    self._load(initial=False)
                except ValueError as exc:
                    message = str(exc)
                    if message != self._last_error:
                        log.warning(
                            "tokens file %s was not reloaded, keeping the last good set "
                            "(%d credential(s)): %s",
                            self._path,
                            len(self._current),
                            message,
                        )
                    self._last_error = message
        except Exception as exc:  # noqa: BLE001 - a reload must never break a request
            log.warning("tokens file reload failed unexpectedly (%s)", type(exc).__name__)

    # -- internals -------------------------------------------------------

    def _read(self) -> tuple[bytes, tuple[int, int, int]]:
        assert self._path is not None
        try:
            handle = open(self._path, "rb")  # noqa: SIM115 - closed below, fstat needs the fd
        except OSError as exc:
            raise ValueError(f"cannot be opened ({type(exc).__name__})") from None
        with handle:
            st = os.fstat(handle.fileno())
            if not stat.S_ISREG(st.st_mode):
                raise ValueError("is not a regular file")
            if _ENFORCE_FILE_MODE and st.st_mode & 0o077:
                raise ValueError(
                    f"has mode {stat.S_IMODE(st.st_mode):04o}; it holds secrets, so it must "
                    f"not be accessible to group or other (run: chmod 600 {self._path})"
                )
            data = handle.read(MAX_TOKENS_FILE_BYTES + 1)
        if len(data) > MAX_TOKENS_FILE_BYTES:
            raise ValueError(f"is larger than {MAX_TOKENS_FILE_BYTES} bytes")
        return data, (st.st_mtime_ns, st.st_size, st.st_ino)

    def _load(self, *, initial: bool) -> None:
        """Read, validate and swap in the file. Raises `ValueError`, changing nothing."""
        assert self._path is not None
        started_ns = time.time_ns()
        try:
            data, signature = self._read()
        except ValueError:
            # Remember that this state was tried so it is not re-read and
            # re-logged on every request; a change of file makes a new signature.
            try:
                st = os.stat(self._path)
                self._signature = (st.st_mtime_ns, st.st_size, st.st_ino)
            except OSError:
                self._signature = None
            self._loaded_at_ns = started_ns
            raise
        self._signature = signature
        self._loaded_at_ns = started_ns
        if data == self._loaded_bytes:
            self._last_error = None
            return
        from_file = _parse_tokens_file(data)
        combined = (*self._static, *from_file)
        _check_set(combined, self._known_agents)
        previous = {c.label for c in self._current}
        self._retired |= {c.token for c in self._current}
        self._current = combined
        self._retired -= {c.token for c in combined}
        self._loaded_bytes = data
        self._last_error = None
        self._warn_on_many_live(combined)
        if not initial:
            now = {c.label for c in combined}
            log.info(
                "tokens file reloaded: %d credential(s); added %s; removed %s",
                len(combined),
                sorted(now - previous) or "none",
                sorted(previous - now) or "none",
            )

    def _warn_on_many_live(self, credentials: Sequence[Credential]) -> None:
        now = self._clock()
        live: dict[str, int] = {}
        for cred in credentials:
            if cred.agent_id and not cred.expired(now):
                live[cred.agent_id] = live.get(cred.agent_id, 0) + 1
        for agent, count in sorted(live.items()):
            if count > 2:
                log.warning(
                    "agent %r has %d live tokens; two (old and new) is the rotation overlap, "
                    "and each extra one is another secret to protect",
                    agent,
                    count,
                )

    # -- building --------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        api_tokens: set[str] | None = None,
        agent_tokens: Mapping[str, str] | None = None,
        *,
        credentials: Sequence[Credential] = (),
        tokens_file: str | os.PathLike[str] | None = None,
        clock: Callable[[], float] = time.time,
        known_agents: Collection[str] | None = None,
    ) -> CredentialStore:
        """A store from the plain-token arguments `create_app` has always taken.

        Default labels are stable and come from configuration, not from the
        secret: `api-token` (`api-token-N` for several unbound tokens, in
        sorted-token order) and `agent-token:AGENT`.
        """
        from .auth import validate_tokens

        bound = validate_tokens(api_tokens, agent_tokens)
        static: list[Credential] = list(credentials)
        unbound = sorted(api_tokens or ())
        for index, token in enumerate(unbound, start=1):
            label = "api-token" if len(unbound) == 1 else f"api-token-{index}"
            static.append(Credential(label, token))
        used = {c.label for c in static}
        for token, agent in bound.items():
            label = base = agent_token_label(agent)
            suffix = 1
            while label in used:
                suffix += 1
                label = f"{base}-{suffix}"
            used.add(label)
            static.append(Credential(label, token, agent))
        enabled = (
            api_tokens is not None
            or bool(agent_tokens)
            or bool(credentials)
            or tokens_file is not None
        )
        return cls(
            static,
            tokens_file=tokens_file,
            clock=clock,
            known_agents=known_agents,
            enabled=enabled,
        )
