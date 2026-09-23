"""Parsing a Jev response into typed answers.

Jev (TypeSafe AI's "System One" model) returns one of three answer shapes
per question it was asked, keyed by the question's id in the request. This
module is the only place that reads `decoded["answers"][...]["type"]` —
every caller works with `ChoiceAnswer` / `ScoreAnswer` / `NoulAnswer`
instead, the same discipline `adapters/transport.py` uses for chat
responses: parse once, at the boundary, into a typed shape everything else
trusts.

Two things are verified here rather than assumed. First, that every number
Jev calls a probability actually is one (`[0.0, 1.0]`): a calibrated
decision engine that returns 1.7 or `nan` for "confidence" has stopped
being calibrated, and a caller doing arithmetic on that value — an
acceptance threshold, say — deserves a loud failure at the parse boundary
rather than a wrong answer two calls later. Second, that a Choice or Score
answer actually selects from the options it was offered: `questions.py`
promises "Jev cannot return an option that was not offered" as the whole
point of asking a selection question instead of a generation one, and that
promise is worth checking rather than trusting, because the failure mode —
a stale option set, a server bug, a version mismatch — would otherwise look
like a valid, silently-wrong answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .questions import Choice, Noul, Score

__all__ = [
    "ChoiceAnswer",
    "JevAnswer",
    "JevResponse",
    "JevResponseError",
    "NoulAnswer",
    "ScoreAnswer",
    "parse_response",
]


class JevResponseError(ValueError):
    """A Jev response could not be trusted as given.

    Covers a malformed answer shape, a probability outside `[0.0, 1.0]`, and
    a Choice or Score answer naming an option that was never offered. All
    three are the same kind of problem — the response cannot be used as a
    calibrated answer — so they share one exception type rather than being
    scattered across `ValueError`, `KeyError` and a silent pass-through.
    """


def _require_unit_interval(question_id: str, field_name: str, value: float) -> float:
    if value != value or not (0.0 <= value <= 1.0):
        raise JevResponseError(
            f"question {question_id!r}: {field_name} must be a probability in "
            f"[0.0, 1.0], got {value!r}"
        )
    return value


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


def _parse_probabilities(
    question_id: str, raw: Mapping[str, Any], *, allowed: frozenset[str] | None
) -> dict[str, float]:
    probabilities = {
        option: _require_unit_interval(question_id, f"probabilities[{option!r}]", float(value))
        for option, value in raw.items()
    }
    if allowed is not None:
        unknown = sorted(set(probabilities) - allowed)
        if unknown:
            raise JevResponseError(
                f"question {question_id!r}: probabilities named option(s) "
                f"{unknown} that were never offered; offered options were "
                f"{sorted(allowed)}"
            )
    return probabilities


def _parse_answer(
    question_id: str, raw: dict[str, Any], question: Choice | Score | Noul | None
) -> JevAnswer:
    kind = raw.get("type")

    if kind == "choice":
        if question is not None and not isinstance(question, Choice):
            raise JevResponseError(
                f"question {question_id!r}: answer type 'choice' does not match "
                f"the {type(question).__name__} question that was asked"
            )
        allowed = frozenset(question.options) if isinstance(question, Choice) else None
        selected = raw["selected"]
        if allowed is not None and selected not in allowed:
            raise JevResponseError(
                f"question {question_id!r}: selected {selected!r}, which was "
                f"never offered; offered options were {sorted(allowed)}. Jev "
                "is documented to select rather than generate an answer, so "
                "this indicates a response that cannot be trusted."
            )
        return ChoiceAnswer(
            selected=selected,
            confidence=_require_unit_interval(question_id, "confidence", float(raw["confidence"])),
            probabilities=_parse_probabilities(
                question_id, raw.get("probabilities", {}), allowed=allowed
            ),
        )

    if kind == "score":
        if question is not None and not isinstance(question, Score):
            raise JevResponseError(
                f"question {question_id!r}: answer type 'score' does not match "
                f"the {type(question).__name__} question that was asked"
            )
        allowed = frozenset(question.criteria) if isinstance(question, Score) else None
        level = raw["level"]
        if allowed is not None and level not in allowed:
            raise JevResponseError(
                f"question {question_id!r}: level {level!r}, which was never "
                f"offered; offered criteria were {sorted(allowed)}. Jev is "
                "documented to select rather than generate an answer, so this "
                "indicates a response that cannot be trusted."
            )
        return ScoreAnswer(
            level=level,
            confidence=_require_unit_interval(question_id, "confidence", float(raw["confidence"])),
            probabilities=_parse_probabilities(
                question_id, raw.get("probabilities", {}), allowed=allowed
            ),
        )

    if kind == "noul":
        if question is not None and not isinstance(question, Noul):
            raise JevResponseError(
                f"question {question_id!r}: answer type 'noul' does not match "
                f"the {type(question).__name__} question that was asked"
            )
        return NoulAnswer(
            probability=_require_unit_interval(
                question_id, "probability", float(raw["probability"])
            )
        )

    raise JevResponseError(
        f"question {question_id!r}: unknown Jev answer type {kind!r}; "
        "expected 'choice', 'score', or 'noul'"
    )


def parse_response(
    decoded: dict[str, Any],
    *,
    questions: Mapping[str, Choice | Score | Noul] | None = None,
) -> JevResponse:
    """Turn a decoded JSON response body into a typed `JevResponse`.

    Raises `JevResponseError` for an answer whose type is not one of the
    three Jev primitives, whose probability or confidence falls outside
    `[0.0, 1.0]`, or — when `questions` is given — that selects an option or
    level never offered, or answers a question with the wrong answer shape.
    Silently accepting any of these would let a caller ask for a decision
    and receive an unusable or fabricated one back with no indication why.

    `questions` is optional and keyed by question id, the same id the
    response is keyed by. It is omitted by tests that construct a response
    shape directly with no originating question to check against, and
    supplied by `JevClient.ask`, which has both in scope.
    """
    answers = {
        question_id: _parse_answer(
            question_id, raw, questions.get(question_id) if questions else None
        )
        for question_id, raw in decoded.get("answers", {}).items()
    }
    return JevResponse(
        model=decoded.get("model", ""),
        answers=answers,
        usage=decoded.get("usage", {}),
    )
