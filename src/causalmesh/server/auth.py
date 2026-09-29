from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)


def make_auth_checker(tokens: set[str] | None) -> Callable[..., Any]:
    """Returns a FastAPI dependency that checks bearer tokens.

    tokens=None means authentication is disabled (dev mode).
    tokens=set() means ALL requests are refused (misconfiguration guard).
    tokens={...} means only those tokens are valid.

    A blank token is refused at construction: it would let an empty
    `Authorization: Bearer` header through, which is authentication off in
    everything but name. `serve` already treats a blank `--api-token` as no
    token; this closes the same hole for a caller of the factory.
    """
    if tokens is not None and any(not token.strip() for token in tokens):
        raise ValueError("bearer tokens must be non-blank")

    async def check(
        credentials: HTTPAuthorizationCredentials | None = Security(bearer),  # noqa: B008
    ) -> None:
        if tokens is None:
            # Dev mode: no auth required.
            return
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Every candidate is compared, in constant time, so the response time
        # does not reveal how much of a guessed token matched.
        presented = credentials.credentials.encode("utf-8")
        matched = False
        for token in tokens:
            matched |= hmac.compare_digest(presented, token.encode("utf-8"))
        if not matched:
            raise HTTPException(
                status_code=401,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return check
