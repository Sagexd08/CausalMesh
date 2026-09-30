"""Bearer-token authentication, and what it does and does not prove.

**What is authenticated.** That the caller holds a secret the operator
configured. Nothing more.

**Which agent is calling is a separate question**, and the answer depends on
the kind of token:

- A *bound* token (`agent_tokens={"agent": "secret"}`) belongs to one agent.
  The server takes the agent from the token, and a request that names a
  different one is refused. Here the agent is established by the credential,
  not by the caller's say-so.
- An *unbound* token (`api_tokens={"secret"}`) belongs to the operator, or to
  a gateway acting for several agents. It can name any agent that has a key.
  The agent is asserted, and the token vouches for the caller, not for the
  claim.

Which credentials exist, when they expire and how they change while the
server runs (`--tokens-file`) is `credentials.py`. A request is refused 401
when its token is unknown or past its expiry; the chain records the operator's
label for the credential (`credential_id`), never the token or a digest of it.

Both are bearer secrets over whatever transport the operator provides; TLS is
theirs. Neither proves anything to a third party who did not see the request:
the server holds every agent's signing key, so a signature in the chain
attests that *the server* recorded the event, and the token is the only thing
tying that record to an agent.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .credentials import CredentialStore

log = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)

__all__ = ["Principal", "SlidingWindowLimiter", "make_auth_checker", "validate_tokens"]


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a request authenticated as.

    `agent_id` is set only for a token bound to an agent. `None` means the
    token is not bound, so any agent named in the request is merely asserted.
    `label` says which configured credential it was, without revealing it.
    """

    agent_id: str | None = None
    key: str = ""
    # The operator's label for the credential, recorded in the chain as
    # `credential_id`. Empty when authentication is off (unknown, not "none").
    label: str = ""


class SlidingWindowLimiter:
    """At most `limit` hits per `window_s` seconds, per key. In memory.

    Deliberately small: no dependency, no shared store. It bounds what one
    credential can ask of a single server process, which is what protects the
    upstream bill and the event loop. It is not distributed (each worker keeps
    its own count) and it is not a defence against a flood from callers who
    hold no valid token, which belongs to the proxy in front of the server.
    Keys are digests of tokens that already authenticated, so the table is
    bounded by the number of configured tokens.
    """

    def __init__(self, limit: int, *, window_s: float = 60.0) -> None:
        if limit < 1:
            raise ValueError("rate limit must be at least 1 request per window")
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str, *, now: float | None = None) -> float | None:
        """Record a hit; return seconds to wait if it is over the limit, else `None`."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and moment - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(0.0, self.window_s - (moment - hits[0]))
            hits.append(moment)
            return None


def validate_tokens(
    tokens: set[str] | None, agent_tokens: Mapping[str, str] | None
) -> dict[str, str]:
    """Check the configured secrets and return them as `{token: agent_id}`.

    Refuses what would make authentication mean less than it appears to: a
    blank token (an empty `Authorization: Bearer` would match it), one token
    given to two agents, or a token that is both bound and unbound.
    """
    if tokens is not None and any(not token.strip() for token in tokens):
        raise ValueError("bearer tokens must be non-blank")
    bound: dict[str, str] = {}
    for agent, token in (agent_tokens or {}).items():
        if not agent.strip():
            raise ValueError("an agent token needs a non-blank agent id")
        if not token.strip():
            raise ValueError(f"the token for agent {agent!r} must be non-blank")
        if token in bound:
            raise ValueError("one token cannot be bound to two agents")
        if tokens is not None and token in tokens:
            raise ValueError(f"the token for agent {agent!r} is also configured as unbound")
        bound[token] = agent
    return bound


def make_auth_checker(
    tokens: set[str] | None,
    agent_tokens: Mapping[str, str] | None = None,
    *,
    rate_limit_per_minute: int | None = None,
    store: CredentialStore | None = None,
) -> Callable[..., Any]:
    """Returns a FastAPI dependency that checks bearer tokens and yields a `Principal`.

    tokens=None with no agent_tokens means authentication is disabled (dev mode).
    tokens=set() with no agent_tokens means ALL requests are refused
    (misconfiguration guard).
    Otherwise only the given tokens are valid.

    `store` replaces the two token arguments with a `CredentialStore`, which is
    how labels, expiry and a reloadable tokens file reach the checker.

    A blank token is refused at construction: it would let an empty
    `Authorization: Bearer` header through, which is authentication off in
    everything but name. `serve` already treats a blank `--api-token` as no
    token; this closes the same hole for a caller of the factory.
    """
    if store is None:
        store = CredentialStore.from_config(tokens, agent_tokens)
    credentials = store
    limiter = SlidingWindowLimiter(rate_limit_per_minute) if rate_limit_per_minute else None

    async def check(
        request: Request,
        credentials_header: HTTPAuthorizationCredentials | None = Security(bearer),  # noqa: B008
    ) -> Principal:
        if not credentials.enabled:
            # Dev mode: no auth required.
            return Principal()
        if credentials_header is None or credentials_header.scheme.lower() != "bearer":
            _refuse(request, "Authentication required")
        presented = credentials_header.credentials.encode("utf-8")

        # Every candidate is compared, in constant time, so the response time
        # does not reveal how much of a guessed token matched.
        matched, expired = credentials.lookup(presented)
        if matched is None:
            _refuse(request, "Invalid token")
        if expired:
            _refuse(request, "Token expired", credential=matched.label)

        key = hashlib.sha256(presented).hexdigest()[:16]
        if limiter is not None:
            wait = limiter.retry_after(key)
            if wait is not None:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(int(wait) + 1)},
                )
        return Principal(agent_id=matched.agent_id, key=key, label=matched.label)

    return check


def _refuse(request: Request, detail: str, *, credential: str | None = None) -> NoReturn:
    """Refuse a request as 401, logging that it happened and never the credential.

    `credential` is the operator's label for a token that was recognised but is
    no longer valid; it names which one, and is not a secret.
    """
    client = request.client.host if request.client else "unknown"
    log.warning(
        "authentication refused: %s %s from %s (%s%s)",
        request.method,
        request.url.path,
        client,
        detail,
        f", credential {credential!r}" if credential else "",
    )
    raise HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})
