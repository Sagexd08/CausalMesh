"""Chain-building helpers shared by the adversarial battery (spec §27, §58).

Kept out of `conftest.py` so test modules can import them directly: conftest
is for fixtures, not for importable helpers.
"""

from __future__ import annotations

from causalmesh.events.schema import Event, EventIdentity, EventType

__all__ = ["ACTORS", "SCRIPT", "SEED", "build_event"]

SEED = b"causalmesh-adversarial-master-seed"
ACTORS = ("agent_a", "agent_b")

# A short scripted history with both actors touching a shared file — the
# minimal shape that makes attribution attacks meaningful.
SCRIPT: tuple[tuple[str, EventType, tuple[str, ...]], ...] = (
    ("agent_a", EventType.READ, ("src/schema.py",)),
    ("agent_a", EventType.WRITE, ("src/schema.py",)),
    ("agent_b", EventType.READ, ("src/schema.py",)),
    ("agent_b", EventType.WRITE, ("src/api.py",)),
    ("agent_a", EventType.TEST, ("tests/test_api.py",)),
)


def build_event(sequence: int, actor: str, event_type: EventType, paths: tuple[str, ...]) -> Event:
    """Construct the event at a given position in the scripted history."""
    return Event(
        event_id=f"evt_{sequence:04d}",
        identity=EventIdentity(
            experiment_id="exp_adversarial",
            task_id="task_schema_handler",
            run_id="run_001",
            agent_id=actor,
            arm="C3",
        ),
        event_type=event_type,
        sequence=sequence,
        timestamp_us=1_700_000_000_000_000 + sequence * 1_000,
        paths=paths,
        parent_id=f"evt_{sequence - 1:04d}" if sequence else None,
    )
