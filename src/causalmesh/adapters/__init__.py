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
from .x402 import (
    PaymentDecision,
    PaymentRequired,
    PaymentRequirement,
    X402Error,
    decide_payment,
    parse_payment_required,
    resource_for,
)

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
    "PaymentDecision",
    "PaymentRequired",
    "PaymentRequirement",
    "ProtocolError",
    "TransportError",
    "X402Error",
    "client_from_environment",
    "decide_payment",
    "parse_action",
    "parse_payment_required",
    "resource_for",
    "system_prompt",
]
