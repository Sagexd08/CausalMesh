"""Model adapters: real language models driving the substrate (spec §8).

`ModelAgent` implements the same `CodingAgent` lifecycle the scripted agent
does, so nothing below it — scheduler, relay, gate, channels, chain —
changes when a model is driving. If swapping the agent required touching
any of that, the substrate would have been coupled to determinism rather
than merely tested with it.

Written against the chat-completions wire protocol rather than vendor SDKs.
See `transport.py` for why: reproducibility, recorded confounds, and one
code path instead of three.
"""

from __future__ import annotations

from .clients import (
    AnthropicClient,
    LocalClient,
    OpenAIClient,
    client_from_environment,
)
from .model_agent import ModelAgent, ModelSettings
from .protocol import (
    PARSE_FAILURE_KINDS,
    ParsedAction,
    ProtocolError,
    parse_action,
    system_prompt,
)
from .transport import ChatMessage, ChatResponse, HttpTransport, TransportError

__all__ = [
    "PARSE_FAILURE_KINDS",
    "AnthropicClient",
    "ChatMessage",
    "ChatResponse",
    "HttpTransport",
    "LocalClient",
    "ModelAgent",
    "ModelSettings",
    "OpenAIClient",
    "ParsedAction",
    "ProtocolError",
    "TransportError",
    "client_from_environment",
    "parse_action",
    "system_prompt",
]
