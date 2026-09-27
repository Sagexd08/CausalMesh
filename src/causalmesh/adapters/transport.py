"""HTTP transport for chat-completion endpoints (spec §8).

Written against the **wire protocol** rather than a vendor SDK, for three
reasons that matter to this project specifically:

1. **Reproducibility (§84).** An SDK is a moving dependency whose retry
   policy, default timeout and request shaping can change between patch
   releases. A run that cannot be re-executed years later because a client
   library changed its defaults is not reproducible. The bytes on the wire
   are the contract.

2. **Recorded confounds (§43).** Everything that could influence a model's
   output — endpoint, model id, temperature, seed, max tokens — has to be
   captured in the run record. An SDK that supplies its own defaults hides
   some of them.

3. **One code path.** OpenAI, Anthropic and every local server (Ollama,
   vLLM, LM Studio, llama.cpp) speak either the OpenAI chat-completions
   shape or something one adapter class away from it. Three SDKs would mean
   three failure modes to test; one HTTP client means one.

`urllib` rather than `httpx` or `requests`: it is in the standard library,
so the runtime dependency list stays as short as §7 asks, and there is no
version of it that can drift underneath a stored run.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ChatMessage",
    "ChatResponse",
    "HttpTransport",
    "TransportError",
]


class TransportError(RuntimeError):
    """A request could not be completed.

    Carries the status code where there was one, so a caller can tell a
    rate limit from a bad request from an unreachable host. §52 wants a
    failure to be classifiable from its evidence rather than from a string.
    """

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One message in a conversation."""

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"content": self.content, "role": self.role}


@dataclass(frozen=True)
class ChatResponse:
    """What a provider returned, plus what it cost.

    `raw` is kept because a model's reply is evidence: §52 requires a
    failure to be traceable, and "the model produced something we could not
    parse" is only diagnosable if the something was retained.
    """

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = ""
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        """The subset worth recording. Excludes `raw` and `latency_ms`.

        Neither may enter the signed chain: raw replies are large and
        latency is wall-clock, and §84 forbids anything non-reproducible in
        the payload. Both stay available on the object for artifacts and
        debugging.
        """
        return {
            "completion_tokens": self.completion_tokens,
            "finish_reason": self.finish_reason,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
        }


_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _http_url(base_url: str, path: str) -> str:
    """Join a base and a path, refusing anything that is not HTTP.

    Raises rather than falling back, because the fallback for "this is not
    a URL I will open" is not to open something else.
    """
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise TransportError(
            f"refusing to open {scheme or 'a schemeless'} URL: "
            f"only {', '.join(sorted(_ALLOWED_SCHEMES))} are permitted"
        )
    return url


@dataclass
class HttpTransport:
    """A minimal JSON-over-HTTP client for chat-completion endpoints.

    Deliberately does not retry. A retry inside the transport would make
    the number of model calls in a run depend on transient network
    conditions, and the token accounting (§44) would silently include work
    the experiment did not intend. Retry policy, if any, belongs to the
    caller where it can be recorded.
    """

    base_url: str
    api_key: str | None = None
    timeout_s: float = 120.0
    headers: dict[str, str] = field(default_factory=dict)

    def post_json(self, path: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """POST a JSON body and return `(response, latency_ms)`.

        Raises `TransportError` for anything that is not a 2xx with a JSON
        body. Returning a sentinel instead would let an unnoticed failure
        become an empty model reply, which the agent layer would then treat
        as a decision the model made.
        """
        url = _http_url(self.base_url, path)
        payload = json.dumps(body).encode("utf-8")

        request = urllib.request.Request(url, data=payload, method="POST")
        request.add_header("Content-Type", "application/json")
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        for name, value in self.headers.items():
            request.add_header(name, value)

        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:  # nosec B310
                body_bytes = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:2000]
            raise TransportError(
                f"{url} returned {exc.code}: {detail}",
                status=exc.code,
                retryable=exc.code == 429 or 500 <= exc.code < 600,
            ) from exc
        except urllib.error.URLError as exc:
            raise TransportError(f"could not reach {url}: {exc.reason}", retryable=True) from exc
        except TimeoutError as exc:
            raise TransportError(
                f"{url} timed out after {self.timeout_s}s", retryable=True
            ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            decoded = json.loads(body_bytes)
        except json.JSONDecodeError as exc:
            raise TransportError(
                f"{url} returned {status} with a non-JSON body: {body_bytes[:500]!r}",
                status=status,
            ) from exc
        if not isinstance(decoded, dict):
            raise TransportError(
                f"{url} returned JSON that is not an object: {type(decoded).__name__}",
                status=status,
            )
        return decoded, latency_ms
