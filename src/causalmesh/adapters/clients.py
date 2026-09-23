"""Provider clients: OpenAI, Anthropic, and any OpenAI-compatible endpoint.

Each exposes one method — `complete(messages, settings) -> ChatResponse` —
so `ModelAgent` never learns which provider it is talking to. The
differences between them are small and entirely contained here:

| | request shape | system prompt | token fields |
|---|---|---|---|
| OpenAI | `messages` | a message with `role: system` | `usage.prompt_tokens` |
| Anthropic | `messages` + `system` | a top-level field | `usage.input_tokens` |
| Local | OpenAI shape | as OpenAI | often absent |

Anthropic is not "OpenAI with a different URL": it hoists the system prompt
out of the message list and names its token counts differently. Pretending
otherwise would silently drop the system prompt, and an agent with no
instructions would look like a badly behaved model rather than a broken
adapter.

Local servers are the OpenAI shape by convention (Ollama, vLLM, LM Studio
and llama.cpp all implement `/v1/chat/completions`), which is why one class
covers all of them.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .transport import ChatMessage, ChatResponse, HttpTransport, TransportError

__all__ = [
    "AnthropicClient",
    "LocalClient",
    "OpenAIClient",
    "client_from_environment",
]

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com/v1"
DEFAULT_LOCAL_BASE = "http://localhost:11434/v1"

ANTHROPIC_VERSION = "2023-06-01"


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(
            f"{name} is required but not set. Adapters never fall back to an "
            "unauthenticated request: a run that silently used a different "
            "endpoint than intended would be attributed to the wrong model."
        )
    return value


@dataclass
class OpenAIClient:
    """OpenAI chat completions."""

    settings_model: str = ""
    api_key: str | None = None
    base_url: str = DEFAULT_OPENAI_BASE
    timeout_s: float = 120.0

    def __post_init__(self) -> None:
        self._transport = HttpTransport(
            base_url=self.base_url,
            api_key=_require(self.api_key or os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY"),
            timeout_s=self.timeout_s,
        )

    @property
    def provider(self) -> str:
        return "openai"

    def complete(self, messages: Sequence[ChatMessage], settings: Any) -> ChatResponse:
        body: dict[str, Any] = {
            "max_tokens": settings.max_tokens,
            "messages": [m.to_dict() for m in messages],
            "model": settings.model,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
        }
        if settings.seed is not None:
            body["seed"] = settings.seed

        decoded, latency_ms = self._transport.post_json("chat/completions", body)
        return _parse_openai_response(decoded, latency_ms, settings.model)


@dataclass
class LocalClient:
    """Any OpenAI-compatible local endpoint: Ollama, vLLM, LM Studio, llama.cpp.

    Separate from `OpenAIClient` despite sharing a wire format, because the
    two differ in what they require: a local server needs no key, and
    `OpenAIClient` deliberately refuses to run without one. Merging them
    would mean weakening that check.
    """

    base_url: str = DEFAULT_LOCAL_BASE
    api_key: str | None = None
    timeout_s: float = 300.0

    def __post_init__(self) -> None:
        self._transport = HttpTransport(
            base_url=self.base_url,
            api_key=self.api_key or os.environ.get("CAUSALMESH_LOCAL_API_KEY"),
            timeout_s=self.timeout_s,
        )

    @property
    def provider(self) -> str:
        return "local"

    def complete(self, messages: Sequence[ChatMessage], settings: Any) -> ChatResponse:
        body: dict[str, Any] = {
            "max_tokens": settings.max_tokens,
            "messages": [m.to_dict() for m in messages],
            "model": settings.model,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
        }
        if settings.seed is not None:
            body["seed"] = settings.seed
        decoded, latency_ms = self._transport.post_json("chat/completions", body)
        return _parse_openai_response(decoded, latency_ms, settings.model)


@dataclass
class AnthropicClient:
    """Anthropic messages API."""

    api_key: str | None = None
    base_url: str = DEFAULT_ANTHROPIC_BASE
    timeout_s: float = 120.0

    def __post_init__(self) -> None:
        self._transport = HttpTransport(
            base_url=self.base_url,
            timeout_s=self.timeout_s,
            headers={
                "anthropic-version": ANTHROPIC_VERSION,
                "x-api-key": _require(
                    self.api_key or os.environ.get("ANTHROPIC_API_KEY"),
                    "ANTHROPIC_API_KEY",
                ),
            },
        )

    @property
    def provider(self) -> str:
        return "anthropic"

    def complete(self, messages: Sequence[ChatMessage], settings: Any) -> ChatResponse:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        conversation = [m.to_dict() for m in messages if m.role != "system"]

        body: dict[str, Any] = {
            "max_tokens": settings.max_tokens,
            "messages": conversation,
            "model": settings.model,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
        }
        if system:
            body["system"] = system

        decoded, latency_ms = self._transport.post_json("messages", body)
        return _parse_anthropic_response(decoded, latency_ms, settings.model)


def _parse_openai_response(
    decoded: dict[str, Any], latency_ms: int, requested_model: str
) -> ChatResponse:
    choices = decoded.get("choices")
    if not isinstance(choices, list) or not choices:
        raise TransportError(f"response has no choices: {str(decoded)[:400]}")
    message = choices[0].get("message") or {}
    text = message.get("content")
    if not isinstance(text, str):
        raise TransportError(f"response choice has no text content: {str(choices[0])[:400]}")
    usage = decoded.get("usage") or {}
    return ChatResponse(
        text=text,
        model=decoded.get("model") or requested_model,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        finish_reason=str(choices[0].get("finish_reason") or ""),
        latency_ms=latency_ms,
        raw=decoded,
    )


def _parse_anthropic_response(
    decoded: dict[str, Any], latency_ms: int, requested_model: str
) -> ChatResponse:
    content = decoded.get("content")
    if not isinstance(content, list) or not content:
        raise TransportError(f"response has no content blocks: {str(decoded)[:400]}")
    text = "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
    if not text:
        raise TransportError(f"response has no text block: {str(content)[:400]}")
    usage = decoded.get("usage") or {}
    return ChatResponse(
        text=text,
        model=decoded.get("model") or requested_model,
        prompt_tokens=int(usage.get("input_tokens") or 0),
        completion_tokens=int(usage.get("output_tokens") or 0),
        finish_reason=str(decoded.get("stop_reason") or ""),
        latency_ms=latency_ms,
        raw=decoded,
    )


def client_from_environment(provider: str, **overrides: Any) -> Any:
    """Build a client by name, refusing an unknown provider.

    Raising rather than defaulting: a typo resolving to some default
    provider would attribute a run's results to the wrong model, which is
    the confound §43 exists to prevent.
    """
    normalized = provider.strip().lower()
    if normalized == "openai":
        return OpenAIClient(**overrides)
    if normalized == "anthropic":
        return AnthropicClient(**overrides)
    if normalized in {"local", "ollama", "vllm", "lmstudio", "llamacpp"}:
        return LocalClient(**overrides)
    raise ValueError(f"unknown provider {provider!r}; expected openai, anthropic or local")
