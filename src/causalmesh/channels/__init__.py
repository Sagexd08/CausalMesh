"""Coordination channels: the single point where information enters an agent.

Spec §14 to §18. Each arm installs a channel, so its information behaviour is
a property of the installed object rather than of a branch in the runtime.

    C0  NullChannel        rejects everything, reports a provable zero
    C1  TranscriptChannel  unbounded prose history
    C2  MetadataChannel    bounded typed events, at most w per turn
    C3  MetadataChannel    identical to C2; C3 differs by enforcement only
"""

from __future__ import annotations

from .base import (
    ChannelError,
    CoordinationChannel,
    Injection,
    InjectionAccounting,
)
from .metadata import DEFAULT_WINDOW, MetadataChannel, render_event
from .null import NullChannel
from .tokens import CHARS_PER_TOKEN, estimate_tokens
from .transcript import Message, Room, TranscriptChannel, describe_event

__all__ = [
    "CHARS_PER_TOKEN",
    "DEFAULT_WINDOW",
    "ChannelError",
    "CoordinationChannel",
    "Injection",
    "InjectionAccounting",
    "Message",
    "MetadataChannel",
    "NullChannel",
    "Room",
    "TranscriptChannel",
    "describe_event",
    "estimate_tokens",
    "render_event",
]
