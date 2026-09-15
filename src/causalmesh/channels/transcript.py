"""The C1 channel: an unbounded conversational transcript (spec §15).

C1 models the common practice of letting agents share a chat history. Its
defining property is that it is **unbounded**: every message ever posted is
replayed to every agent on every turn, so the injected context grows
quadratically with the number of turns.

That growth is not an accident to be optimised away — it is the phenomenon
C1 exists to measure. §46 predicts transcript cost as

    C_tr(T) = μT(T - 1) / 2

and the C1→C2 contrast is precisely the difference between that and a
bounded channel. Truncating C1 would flatten the very curve the experiment
is trying to observe, so §15 forbids silent truncation: any limit must
appear in configuration and in the manifest, and this implementation offers
none.

The `Room` is the shared history (§15). Membership is explicit so that an
agent's own messages can be excluded from what is replayed to it — an agent
re-reading its own words is not coordination and would inflate the cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..events.schema import Event, EventType
from .base import Injection, InjectionAccounting
from .tokens import estimate_tokens

__all__ = ["Message", "Room", "TranscriptChannel"]


@dataclass(frozen=True, slots=True)
class Message:
    """One transcript entry (§15)."""

    actor: str
    timestamp_us: int
    run_id: str
    task_id: str
    content: str
    event_id: str | None = None

    def render(self) -> str:
        return f"[{self.actor}] {self.content}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "content": self.content,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "timestamp_us": self.timestamp_us,
        }


class Room:
    """The shared, append-only transcript (§15)."""

    def __init__(self, run_id: str, task_id: str) -> None:
        self.run_id = run_id
        self.task_id = task_id
        self._messages: list[Message] = []
        self._participants: set[str] = set()

    def append(self, message: Message) -> None:
        self._messages.append(message)
        self._participants.add(message.actor)

    def history(self, *, exclude_actor: str | None = None) -> tuple[Message, ...]:
        """The full history, optionally without one actor's own messages."""
        if exclude_actor is None:
            return tuple(self._messages)
        return tuple(m for m in self._messages if m.actor != exclude_actor)

    def participants(self) -> tuple[str, ...]:
        return tuple(sorted(self._participants))

    def export(self) -> list[dict[str, Any]]:
        return [message.to_dict() for message in self._messages]

    def __len__(self) -> int:
        return len(self._messages)


def describe_event(event: Event) -> str:
    """Render an event as the prose a chatty agent would post.

    Deliberately verbose. C1's cost comes from natural-language framing
    around the same underlying facts C2 carries as typed fields, and
    compressing this would understate the difference the C1→C2 contrast
    measures.
    """
    paths = ", ".join(event.paths) if event.paths else "no specific file"
    verb = {
        EventType.READ: "I read",
        EventType.WRITE: "I wrote to",
        EventType.CREATE: "I created",
        EventType.MODIFY: "I modified",
        EventType.DELETE: "I deleted",
        EventType.RENAME: "I renamed",
        EventType.TEST: "I ran tests touching",
        EventType.INTENT: "I am planning to work on",
        EventType.CLAIM: "I claimed",
        EventType.RELEASE: "I released",
        EventType.COMMIT: "I committed",
        EventType.FAILURE: "I hit a problem with",
    }.get(event.event_type, "I acted on")

    sentence = f"{verb} {paths}."
    reason = event.payload.get("reason")
    if reason:
        sentence += f" Note: {reason}"
    return sentence


class TranscriptChannel:
    """Replays the entire shared transcript on every turn.

    No truncation, no summarisation, no deduplication. Each is a plausible
    engineering improvement and each would destroy the measurement.
    """

    def __init__(self, agent_id: str, room: Room) -> None:
        self.agent_id = agent_id
        self.room = room
        self._accounting = InjectionAccounting(agent_id=agent_id)

    @property
    def arm(self) -> str:
        return "C1"

    @property
    def accounting(self) -> InjectionAccounting:
        return self._accounting

    def offer(self, events: tuple[Event, ...], *, turn: int) -> Injection:
        """Post the newly delivered events, then replay the whole history."""
        for event in events:
            self.room.append(
                Message(
                    actor=event.identity.agent_id,
                    timestamp_us=event.timestamp_us,
                    run_id=event.identity.run_id,
                    task_id=event.identity.task_id,
                    content=describe_event(event),
                    event_id=event.event_id,
                )
            )

        # An agent re-reading its own words is not coordination.
        history = self.room.history(exclude_actor=self.agent_id)
        text = "\n".join(message.render() for message in history)

        injection = Injection(
            text=text,
            events_available=len(events),
            events_selected=len(events),
            # The whole history is injected every turn — that is the point.
            events_injected=len(history),
            events_dropped=0,
            selection_reasons=({"policy": "unbounded transcript", "messages": len(history)},),
            tokens=estimate_tokens(text),
        )
        self._accounting.record(injection)
        return injection
