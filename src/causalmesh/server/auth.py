from __future__ import annotations

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
    """

    async def check(
        credentials: HTTPAuthorizationCredentials | None = Security(bearer),  # noqa: B008
    ) -> None:
        if tokens is None:
            # Dev mode: no auth required.
            return
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Authentication required")
        if credentials.credentials not in tokens:
            raise HTTPException(status_code=401, detail="Invalid token")

    return check
