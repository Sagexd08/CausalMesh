# src/causalmesh/jev/response.py
"""Parsing a Jev response into typed answers.

Jev (TypeSafe AI's "System One" model) returns one of three answer shapes
per question it was asked, keyed by the question's id in the request. This
module is the only place that reads `decoded["answers"][...]["type"]` —
every caller works with `ChoiceAnswer` / `ScoreAnswer` / `NoulAnswer`
instead, the same discipline `adapters/transport.py` uses for chat
responses: parse once, at the boundary, into a typed shape everything else
trusts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ChoiceAnswer",
    "JevAnswer",
    "JevResponse",
    "NoulAnswer",
    "ScoreAnswer",
    "parse_response",
]


@dataclass(frozen=True, slots=True)
class ChoiceAnswer:
    """The chosen option among a fixed set, with a probability per option."""

    selected: str
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoreAnswer:
    """A level on a fixed scale, with a probability per level."""

    level: str
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NoulAnswer:
    """The probability that a yes/no proposition is true.

    No separate confidence field: the probability itself describes the
    yes/no uncertainty, so a second number would just restate it.
    """

    probability: float


JevAnswer = ChoiceAnswer | ScoreAnswer | NoulAnswer


@dataclass(frozen=True, slots=True)
class JevResponse:
    """A full Jev reply: one answer per question that was asked."""

    model: str
    answers: dict[str, JevAnswer]
    usage: dict[str, Any] = field(default_factory=dict)


def _parse_answer(question_id: str, raw: dict[str, Any]) -> JevAnswer:
    kind = raw.get("type")
    if kind == "choice":
        return ChoiceAnswer(
            selected=raw["selected"],
            confidence=float(raw["confidence"]),
            probabilities={k: float(v) for k, v in raw.get("probabilities", {}).items()},
        )
    if kind == "score":
        return ScoreAnswer(
            level=raw["level"],
            confidence=float(raw["confidence"]),
            probabilities={k: float(v) for k, v in raw.get("probabilities", {}).items()},
        )
    if kind == "noul":
        return NoulAnswer(probability=float(raw["probability"]))
    raise ValueError(
        f"question {question_id!r}: unknown Jev answer type {kind!r}; "
        "expected 'choice', 'score', or 'noul'"
    )


def parse_response(decoded: dict[str, Any]) -> JevResponse:
    """Turn a decoded JSON response body into a typed `JevResponse`.

    Raises `ValueError` for an answer whose type is not one of the three
    Jev primitives — silently skipping it would let a caller ask for a
    decision and receive nothing back with no indication why.
    """
    answers = {
        question_id: _parse_answer(question_id, raw)
        for question_id, raw in decoded.get("answers", {}).items()
    }
    return JevResponse(
        model=decoded.get("model", ""),
        answers=answers,
        usage=decoded.get("usage", {}),
    )
