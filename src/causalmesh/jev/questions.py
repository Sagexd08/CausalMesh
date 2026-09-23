"""The three typed questions Jev answers: Choice, Score, Noul.

Each is a request to evaluate the *current* program state against a fixed
set of possible answers. Jev cannot return an answer outside what was
given here — it selects, it does not generate — so the set of options or
criteria is itself part of the contract with the caller, not a hint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Choice", "Noul", "Score"]


@dataclass(frozen=True, slots=True)
class Choice:
    """Pick one of a fixed set of named options."""

    id: str
    prompt: str
    options: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.options) < 2:
            raise ValueError(
                f"question {self.id!r}: a Choice needs at least two options, got {self.options!r}"
            )
        if len(set(self.options)) != len(self.options):
            raise ValueError(f"question {self.id!r}: options must be unique, got {self.options!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"type": "choice", "prompt": self.prompt, "options": list(self.options)}


@dataclass(frozen=True, slots=True)
class Score:
    """Rate the state against a fixed, ordered set of levels."""

    id: str
    prompt: str
    criteria: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.criteria) < 2:
            raise ValueError(
                f"question {self.id!r}: a Score needs at least two criteria, got {self.criteria!r}"
            )
        if len(set(self.criteria)) != len(self.criteria):
            raise ValueError(
                f"question {self.id!r}: criteria must be unique, got {self.criteria!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"type": "score", "prompt": self.prompt, "criteria": list(self.criteria)}


@dataclass(frozen=True, slots=True)
class Noul:
    """The probability that a yes/no proposition about the state is true."""

    id: str
    prompt: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": "noul", "prompt": self.prompt}
