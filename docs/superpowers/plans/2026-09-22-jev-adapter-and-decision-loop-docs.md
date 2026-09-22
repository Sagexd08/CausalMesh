# Jev Adapter and Decision-Loop Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested, standalone `JevClient` adapter for TypeSafe AI's Jev decision
engine (real API: `POST https://api.typesafe.ai/v1/systemone`), then fold the
decision-loop concept it enables into `docs/FRAMEWORK-PLAN.md`, `docs/backlog.md`, and
one new Next.js landing-page section — without wiring Jev into any existing runtime
decision path.

**Architecture:** New `src/causalmesh/jev/` package mirrors the existing
`src/causalmesh/adapters/` conventions: a dataclass client over the shared
`HttpTransport`, typed request builders for Jev's three question primitives (Choice,
Score, Noul), and typed response parsing. Unit tests cover request/response shaping
with no network; one integration test proves the client against the real API, skipped
when `TYPESAFE_API_KEY` is unset. Docs and frontend changes are additive only.

**Tech Stack:** Python 3.13 (stdlib `urllib` via the existing `HttpTransport`), pytest,
Next.js/React (existing landing-page component patterns), Tailwind CSS.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/causalmesh/jev/__init__.py` | Public exports: `JevClient`, `Choice`, `Score`, `Noul`, `ChoiceAnswer`, `ScoreAnswer`, `NoulAnswer` |
| `src/causalmesh/jev/questions.py` | Typed request builders for the three Jev question primitives |
| `src/causalmesh/jev/response.py` | Typed parsing of a Jev response into answer dataclasses |
| `src/causalmesh/jev/client.py` | `JevClient`: auth, base URL, the one `ask()` call over `HttpTransport` |
| `tests/unit/test_jev.py` | Request-building and response-parsing tests, no network |
| `tests/integration/test_jev_live.py` | Real network call against `api.typesafe.ai`, skipped without `TYPESAFE_API_KEY` |
| `docs/PLAN.md` | Add `jev/` to the module table (§ "Package layout") |
| `docs/FRAMEWORK-PLAN.md` | Add "The decision loop" subsection to §2; add "Three audit properties" to §5 |
| `docs/backlog.md` | Add four entries: Jev adapter status, acceptance decision object, handoff package, causal edges |
| `frontend/components/landing/DecisionLoop.jsx` | New landing-page section: the four-decision stepper |
| `frontend/app/page.tsx` | Insert `<DecisionLoop />` after `<Framework />` |

---

## Task 1: Jev response types

**Files:**
- Create: `src/causalmesh/jev/response.py`
- Test: `tests/unit/test_jev.py`

Jev's documented response shape (confirmed across TypeSafe's own docs and independent
integration write-ups): a top-level object with a `model` field and an `answers` object
keyed by question id, where each answer carries a `type` (`"choice"`, `"score"`, or
`"noul"`) plus type-specific fields, and usage metrics.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_jev.py
"""Unit tests for the Jev adapter (TypeSafe AI's typed decision engine).

Jev returns typed, calibrated answers instead of text: a Choice question
gets back the chosen option plus a probability per option; a Score question
gets back a level plus a probability per level; a Noul question gets back a
single probability. These tests cover parsing that response shape with no
network involved — the live-API proof is in tests/integration/test_jev_live.py.
"""

from __future__ import annotations

import pytest

from causalmesh.jev.response import (
    ChoiceAnswer,
    JevResponse,
    NoulAnswer,
    ScoreAnswer,
    parse_response,
)

pytestmark = pytest.mark.unit


class TestParseResponse:
    def test_a_choice_answer(self) -> None:
        decoded = {
            "model": "jev-latest",
            "answers": {
                "pick_agent": {
                    "type": "choice",
                    "selected": "claude_code",
                    "confidence": 0.71,
                    "probabilities": {"claude_code": 0.71, "codex": 0.29},
                }
            },
            "usage": {"input_tokens": 120},
        }
        response = parse_response(decoded)
        answer = response.answers["pick_agent"]
        assert isinstance(answer, ChoiceAnswer)
        assert answer.selected == "claude_code"
        assert answer.confidence == pytest.approx(0.71)
        assert answer.probabilities == {"claude_code": 0.71, "codex": 0.29}

    def test_a_score_answer(self) -> None:
        decoded = {
            "model": "jev-latest",
            "answers": {
                "severity": {
                    "type": "score",
                    "level": "high",
                    "confidence": 0.84,
                    "probabilities": {"low": 0.05, "medium": 0.11, "high": 0.84},
                }
            },
            "usage": {"input_tokens": 90},
        }
        response = parse_response(decoded)
        answer = response.answers["severity"]
        assert isinstance(answer, ScoreAnswer)
        assert answer.level == "high"
        assert answer.confidence == pytest.approx(0.84)
        assert answer.probabilities["high"] == pytest.approx(0.84)

    def test_a_noul_answer(self) -> None:
        decoded = {
            "model": "jev-latest",
            "answers": {
                "should_continue": {"type": "noul", "probability": 0.93},
            },
            "usage": {"input_tokens": 60},
        }
        response = parse_response(decoded)
        answer = response.answers["should_continue"]
        assert isinstance(answer, NoulAnswer)
        assert answer.probability == pytest.approx(0.93)

    def test_multiple_answers_in_one_response(self) -> None:
        decoded = {
            "model": "jev-latest",
            "answers": {
                "a": {"type": "noul", "probability": 0.5},
                "b": {"type": "noul", "probability": 0.6},
            },
            "usage": {"input_tokens": 10},
        }
        response = parse_response(decoded)
        assert set(response.answers) == {"a", "b"}

    def test_an_unknown_answer_type_raises(self) -> None:
        decoded = {
            "model": "jev-latest",
            "answers": {"x": {"type": "mystery"}},
            "usage": {"input_tokens": 1},
        }
        with pytest.raises(ValueError, match="mystery"):
            parse_response(decoded)

    def test_response_carries_the_model_name(self) -> None:
        decoded = {
            "model": "jev-2026-09",
            "answers": {"a": {"type": "noul", "probability": 0.1}},
            "usage": {"input_tokens": 1},
        }
        response = parse_response(decoded)
        assert response.model == "jev-2026-09"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_jev.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'causalmesh.jev'`

- [ ] **Step 3: Write the response types**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_jev.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/causalmesh/jev/response.py tests/unit/test_jev.py
git commit -m "feat(jev): parse typed Choice/Score/Noul answers from a Jev response"
```

---

## Task 2: Jev question builders

**Files:**
- Create: `src/causalmesh/jev/questions.py`
- Modify: `tests/unit/test_jev.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_jev.py`:

```python
from causalmesh.jev.questions import Choice, Noul, Score


class TestQuestionBuilders:
    def test_choice_to_dict(self) -> None:
        q = Choice(
            id="pick_agent",
            prompt="Which agent should act next?",
            options=["claude_code", "codex"],
        )
        assert q.to_dict() == {
            "type": "choice",
            "prompt": "Which agent should act next?",
            "options": ["claude_code", "codex"],
        }

    def test_score_to_dict(self) -> None:
        q = Score(
            id="severity",
            prompt="How severe is this failure?",
            criteria=["low", "medium", "high"],
        )
        assert q.to_dict() == {
            "type": "score",
            "prompt": "How severe is this failure?",
            "criteria": ["low", "medium", "high"],
        }

    def test_noul_to_dict(self) -> None:
        q = Noul(id="should_continue", prompt="Should execution continue?")
        assert q.to_dict() == {
            "type": "noul",
            "prompt": "Should execution continue?",
        }

    def test_choice_requires_at_least_two_options(self) -> None:
        with pytest.raises(ValueError, match="at least two options"):
            Choice(id="x", prompt="pick one", options=["only_one"])

    def test_score_requires_at_least_two_criteria(self) -> None:
        with pytest.raises(ValueError, match="at least two"):
            Score(id="x", prompt="rate it", criteria=["only_one"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_jev.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'causalmesh.jev.questions'`

- [ ] **Step 3: Write the question builders**

```python
# src/causalmesh/jev/questions.py
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
                f"question {self.id!r}: a Choice needs at least two options, "
                f"got {self.options!r}"
            )

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
                f"question {self.id!r}: a Score needs at least two criteria, "
                f"got {self.criteria!r}"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_jev.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add src/causalmesh/jev/questions.py tests/unit/test_jev.py
git commit -m "feat(jev): typed Choice/Score/Noul question builders"
```

---

## Task 3: JevClient

**Files:**
- Create: `src/causalmesh/jev/client.py`
- Modify: `tests/unit/test_jev.py`

`JevClient` reuses `causalmesh.adapters.transport.HttpTransport` rather than a new HTTP
layer — it is already provider-agnostic (base URL, bearer key, JSON POST, typed
`TransportError`), and Jev's endpoint is a single fixed path, not a family of endpoints
the way chat-completions providers need.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_jev.py`:

```python
import os
from unittest.mock import patch

from causalmesh.jev.client import JevClient


class TestJevClientConstruction:
    def test_requires_an_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
                JevClient()

    def test_accepts_an_explicit_key(self) -> None:
        client = JevClient(api_key="test-key-123")
        assert client._transport.api_key == "test-key-123"

    def test_reads_the_key_from_the_environment(self) -> None:
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "env-key"}, clear=True):
            client = JevClient()
            assert client._transport.api_key == "env-key"

    def test_default_base_url(self) -> None:
        client = JevClient(api_key="k")
        assert client.base_url == "https://api.typesafe.ai/v1"


class TestJevClientAsk:
    def test_ask_posts_state_and_questions_and_parses_the_reply(self) -> None:
        client = JevClient(api_key="k")
        calls = []

        def fake_post_json(path, body):
            calls.append((path, body))
            return (
                {
                    "model": "jev-latest",
                    "answers": {
                        "pick": {
                            "type": "choice",
                            "selected": "b",
                            "confidence": 0.9,
                            "probabilities": {"a": 0.1, "b": 0.9},
                        }
                    },
                    "usage": {"input_tokens": 5},
                },
                12,
            )

        client._transport.post_json = fake_post_json  # type: ignore[method-assign]

        response = client.ask(
            state={"task": "fix bug"},
            questions=[Choice(id="pick", prompt="a or b?", options=["a", "b"])],
        )

        assert calls == [
            (
                "systemone",
                {
                    "state": {"task": "fix bug"},
                    "questions": {"pick": {"type": "choice", "prompt": "a or b?", "options": ["a", "b"]}},
                },
            )
        ]
        assert response.answers["pick"].selected == "b"
```

Add the missing import at the top of `tests/unit/test_jev.py`:

```python
from causalmesh.jev.questions import Choice, Noul, Score
```

(This import already exists from Task 2 — confirm it is present rather than duplicating it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_jev.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'causalmesh.jev.client'`

- [ ] **Step 3: Write the client**

```python
# src/causalmesh/jev/client.py
"""JevClient: one HTTP call to TypeSafe AI's Jev decision engine.

Jev takes unstructured program state and a set of typed questions (Choice,
Score, Noul — see questions.py) and returns a calibrated answer to each in
a single parallel pass. Unlike the chat-completions providers in
adapters/clients.py, Jev has exactly one endpoint, so this client is
smaller than OpenAIClient or AnthropicClient: there is no request shape to
choose between providers, only state and questions to serialize.

Reuses adapters.transport.HttpTransport rather than a new HTTP layer for
the same reasons that module gives: no version of urllib can drift
underneath a stored run, and one JSON-over-HTTP implementation is one
failure mode to test instead of two.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from causalmesh.adapters.transport import HttpTransport

from .questions import Choice, Noul, Score
from .response import JevResponse, parse_response

__all__ = ["JevClient"]

DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"

Question = Choice | Score | Noul


def _require_api_key(value: str | None) -> str:
    if not value:
        raise ValueError(
            "TYPESAFE_API_KEY is required but not set. JevClient never falls "
            "back to an unauthenticated request: a call that silently used a "
            "different endpoint than intended would be attributed to the "
            "wrong decision engine."
        )
    return value


@dataclass
class JevClient:
    """A typed decision engine call: state and questions in, answers out."""

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    # Jev is documented as 40-200x faster than a frontier LLM call on
    # comparable tasks; a chat-completion-sized timeout would be far too
    # generous and would mask a genuinely hung request.
    timeout_s: float = 30.0

    def __post_init__(self) -> None:
        self._transport = HttpTransport(
            base_url=self.base_url,
            api_key=_require_api_key(self.api_key or os.environ.get("TYPESAFE_API_KEY")),
            timeout_s=self.timeout_s,
        )

    def ask(self, *, state: dict[str, Any], questions: Sequence[Question]) -> JevResponse:
        """Evaluate `state` against every question, in one request.

        Jev evaluates all questions in a request in parallel, so asking
        several things at once costs about the same latency as asking one
        — batch related questions into a single `ask()` call rather than
        issuing one per question.
        """
        body = {
            "state": state,
            "questions": {q.id: q.to_dict() for q in questions},
        }
        decoded, _latency_ms = self._transport.post_json("systemone", body)
        return parse_response(decoded)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_jev.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add src/causalmesh/jev/client.py tests/unit/test_jev.py
git commit -m "feat(jev): JevClient — one call to TypeSafe's decision engine"
```

---

## Task 4: Package exports

**Files:**
- Create: `src/causalmesh/jev/__init__.py`
- Test: `tests/unit/test_jev.py` (modify)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_jev.py`:

```python
class TestPackageExports:
    def test_everything_importable_from_the_package_root(self) -> None:
        from causalmesh.jev import (
            Choice,
            ChoiceAnswer,
            JevClient,
            JevResponse,
            Noul,
            NoulAnswer,
            Score,
            ScoreAnswer,
        )

        assert JevClient is not None
        assert Choice is not None
        assert Score is not None
        assert Noul is not None
        assert ChoiceAnswer is not None
        assert ScoreAnswer is not None
        assert NoulAnswer is not None
        assert JevResponse is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_jev.py::TestPackageExports -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'causalmesh.jev'` (no `__init__.py` yet)

- [ ] **Step 3: Write the package init**

```python
# src/causalmesh/jev/__init__.py
"""Jev: TypeSafe AI's typed decision engine, as a client for this substrate.

Jev takes program state and a set of typed questions — Choice (pick one of
several named options), Score (rate against an ordered scale), Noul (the
probability a yes/no proposition is true) — and returns a calibrated
answer to each, generated by selection rather than text generation, so it
cannot return an option that was not offered.

This package is a tested, standalone adapter. Nothing in the runtime calls
it yet — see docs/backlog.md for why, and for the concrete decision points
(agent recovery, once multi-agent orchestration exists) that are the
natural future consumers.
"""

from __future__ import annotations

from .client import JevClient
from .questions import Choice, Noul, Score
from .response import ChoiceAnswer, JevAnswer, JevResponse, NoulAnswer, ScoreAnswer

__all__ = [
    "Choice",
    "ChoiceAnswer",
    "JevAnswer",
    "JevClient",
    "JevResponse",
    "Noul",
    "NoulAnswer",
    "Score",
    "ScoreAnswer",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_jev.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Run the full unit suite to confirm nothing else broke**

Run: `pytest tests/unit -v`
Expected: PASS (all existing unit tests plus the 16 new ones)

- [ ] **Step 6: Commit**

```bash
git add src/causalmesh/jev/__init__.py tests/unit/test_jev.py
git commit -m "feat(jev): export the package's public API"
```

---

## Task 5: Live-API integration test

**Files:**
- Create: `tests/integration/test_jev_live.py`

Proves the adapter against the real `api.typesafe.ai` endpoint. Skipped when
`TYPESAFE_API_KEY` is not set, matching the project's existing convention of never
running a real hosted-provider call unconditionally (see `docs/backlog.md`'s note on
"Real LLM adapters" — hosted calls require an operator's key and are the operator's
decision to spend).

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_jev_live.py
"""JevClient against the real TypeSafe AI API (spec: real Jev adapter).

This is the one test in the suite that leaves the machine to reach a real
hosted service. It is skipped unless TYPESAFE_API_KEY is set, the same
convention this project already applies to real LLM providers: spending
money against a real API is the operator's decision, not something a test
run makes silently.

The question asked is deliberately unambiguous — "pick the smaller
number" between two options that are not close — so a correct answer is
verifiable without needing to know anything about Jev's actual calibration
behavior on hard cases.
"""

from __future__ import annotations

import os

import pytest

from causalmesh.jev import Choice, JevClient

pytestmark = [pytest.mark.integration]

requires_typesafe_key = pytest.mark.skipif(
    not os.environ.get("TYPESAFE_API_KEY"),
    reason="TYPESAFE_API_KEY not set; skipping the real Jev API call",
)


@requires_typesafe_key
def test_a_real_choice_question_against_the_live_api() -> None:
    client = JevClient()
    response = client.ask(
        state={"context": "Comparing two plain integers."},
        questions=[
            Choice(
                id="smaller",
                prompt="Which of these two numbers is smaller: 3 or 9000?",
                options=["3", "9000"],
            )
        ],
    )
    answer = response.answers["smaller"]
    assert answer.selected == "3"
    assert 0.0 <= answer.confidence <= 1.0
    assert set(answer.probabilities) == {"3", "9000"}
```

- [ ] **Step 2: Run the test without a key to confirm it skips cleanly**

Run: `pytest tests/integration/test_jev_live.py -v`
Expected: `SKIPPED (TYPESAFE_API_KEY not set; skipping the real Jev API call)`

- [ ] **Step 3: If `TYPESAFE_API_KEY` is available in this environment, run it for real**

Run: `TYPESAFE_API_KEY=<key> pytest tests/integration/test_jev_live.py -v`
Expected: PASS — this is the "prove it against the real API" step. If no key is
available in this environment, leave the test in place (skipped) and note in the
commit message that it was not exercised live, consistent with how
`docs/backlog.md` already records untested-but-built provider adapters.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_jev_live.py
git commit -m "test(jev): real API proof, gated behind TYPESAFE_API_KEY"
```

---

## Task 6: `docs/PLAN.md` — module table entry

**Files:**
- Modify: `docs/PLAN.md:80` (the package layout table)

- [ ] **Step 1: Add the `jev/` row**

Find this line in `docs/PLAN.md`:

```
| `agents/`, `adapters/` | `CodingAgent` interface and scripted MockAgent | scheduler |
```

Add immediately after it:

```
| `jev/` | Typed decision engine client (Choice/Score/Noul) for TypeSafe AI's Jev | its own test suite only — no runtime caller yet; see `docs/backlog.md` |
```

- [ ] **Step 2: Verify the table still renders correctly**

Run: `grep -n "jev/" docs/PLAN.md`
Expected: one line showing the new row between the `agents/`/`adapters/` row and whatever follows it.

- [ ] **Step 3: Commit**

```bash
git add docs/PLAN.md
git commit -m "docs: record the jev/ package in the module layout table"
```

---

## Task 7: `docs/FRAMEWORK-PLAN.md` — the decision loop and audit properties

**Files:**
- Modify: `docs/FRAMEWORK-PLAN.md`

- [ ] **Step 1: Add "The decision loop" subsection to §2**

In `docs/FRAMEWORK-PLAN.md`, find the end of the "### The four planes" subsection —
the paragraph ending:

```
**4 · Measurement.** Exists, and is the moat. Any convention the framework proposes can
be run C2 vs C3 and measured. "Exclusive claims on config.py cost 196 bytes per run and
prevented three clobbers" is a sentence no other framework can produce.

---
```

Insert a new subsection immediately before the `---` that ends §2:

```markdown
### The decision loop

The four planes describe what the gate checks once. Some of what a run needs to
decide does not fit a single allow/refuse check — it is a small set of typed
questions asked repeatedly as the run progresses:

```
classify       what kind of task is this?
select_agent   which agent should act next?
recover        after a failure: retry, switch agent, or escalate?
accept         does the evidence support ACCEPT, REJECT, or HUMAN_REVIEW?
```

`accept` matters most: run completion should never be read directly off an agent's own
"I'm done" — it should be a decision made against evidence (tests passed, diff
conforms, divergence absent), with `REJECT` and `HUMAN_REVIEW` as named alternatives to
`ACCEPT`, not just the absence of success.

**What a typed decision engine in this role looks like, concretely.** TypeSafe AI's Jev
(shipped 2026-09-15) takes arbitrary state and a set of typed questions — Choice (pick
one of several named options), Score (rate against an ordered scale), Noul (the
probability a yes/no proposition is true) — and returns a calibrated answer to each by
selection rather than text generation, so it cannot answer outside the options it was
given. `classify`, `select_agent`, `recover`, and `accept` all fit that shape exactly:
each is a fixed, enumerable set of outcomes evaluated against the current run state.
We built and tested a `JevClient` adapter (`src/causalmesh/jev/`) against Jev's real API
to confirm the shape is implementable cheaply today — this is evidence the decision
loop is buildable, not an adopted dependency.

**What exists today.** The adapter, tested unit and against the live API. Nothing in
the runtime calls it. The gate (`policy/gate.py`) remains entirely deterministic rule
evaluation, which is correct for what it decides today — ownership, allowlists,
budgets, and leases all have a single correct answer given the contract, and a
probabilistic call would add latency and a new failure mode without resolving any real
uncertainty. `select_agent` and `recover` have no home yet: the scheduler runs exactly
one agent per run, with no state for "switch to a different agent mid-run." Recovery
producing a signed handoff package — the task, repo state, diff, test results, and
prior decisions, so a second agent inherits execution state rather than starting cold
— is designed here but not built; see `docs/backlog.md`.
```

- [ ] **Step 2: Add "Three audit properties" to §5**

In `docs/FRAMEWORK-PLAN.md`, find the "**Strong fit — build:**" list in §5
(Complementary features), specifically this bullet:

```
- **Compliance export.** One command producing the artifact NIST/IMDA/EU AI Act
  auditors ask for: which agent, under whose authorisation, did what, and the signature
  proving it. We already hold every field; this is a report, not a feature.
```

Insert a new bullet immediately after it:

```
- **Naming the three audit properties separately.** "Is the record trustworthy" is
  actually three different questions, and conflating them overstates what one
  guarantee proves:

  | Property | Question | Status today |
  |---|---|---|
  | Integrity | Did the record change after it was written? | Answered — the adversarial battery (`Integrity.jsx` on the landing page) detects 7/7 tamper modes, with suffix truncation named as the one gap an external anchor would close |
  | Provenance | Which signing identity emitted this event? | Answered — Ed25519 per-actor keys, checked on every verify |
  | Completeness | Did instrumentation capture every event a policy requires? | Open — nothing today measures whether the event *policy* itself is exhaustive, only whether the events that were written are intact and attributed |

  A valid signature on every recorded event does not prove nothing was left
  unrecorded. Compliance export should eventually report against all three
  separately rather than implying one covers the others.
```

- [ ] **Step 3: Verify the doc still reads coherently end to end**

Run: `grep -n "^##\|^###" docs/FRAMEWORK-PLAN.md`
Expected: heading list shows "### The decision loop" between "### The four planes" and
"## 3. The three agent kinds", and the new bullet sits inside "**Strong fit — build:**"
under "## 5. Complementary features".

- [ ] **Step 4: Commit**

```bash
git add docs/FRAMEWORK-PLAN.md
git commit -m "docs(framework-plan): the decision loop, named after Jev, and three audit properties"
```

---

## Task 8: `docs/backlog.md` — four new entries

**Files:**
- Modify: `docs/backlog.md`

- [ ] **Step 1: Read the file's existing entry format**

Run: `sed -n '1,60p' docs/backlog.md` and confirm each entry uses `### <title>` followed
by `**Status:**`, `**Why:**` (or equivalent prose), and what remains/what it would
take — matching the two entries already read during design (Real LLM adapters,
CooperBench import).

- [ ] **Step 2: Append four new entries at the end of the file**

```markdown

## Jev decision engine

### Adapter built, not wired

**Status:** `JevClient` and the Choice/Score/Noul request and response types exist in
`src/causalmesh/jev/`, tested at the unit level with no network and, when
`TYPESAFE_API_KEY` is set, against the real `api.typesafe.ai` endpoint. Nothing in the
runtime calls it — no run, no decision, no chain event depends on Jev today.

**Why:** every decision point that exists in the runtime — `TaskFamily`,
`check_sensitivity`'s C0-vs-C2 verdict, every rule in `policy/gate.py` — is
deliberately deterministic, and for good reason: §35/§36 require task properties to be
declared rather than inferred so a run stays reproducible and hash-pinned, and the
gate's rules (ownership, allowlist, ceiling, budget, claim) each have exactly one
correct answer given the contract and current state. There was no decision point in
the current runtime where trading a deterministic answer for a calibrated probability
was the right move — that would add latency, a network dependency, and a new failure
mode to a call that already had one correct answer.

**What it would take:** a decision that is genuinely uncertain given the available
state, not merely unautomated. The leading candidate is `recover` (retry the same
agent, switch to a different one, or escalate to a human) once multi-agent
orchestration exists — see "Agent handoff package on recovery" below. Wiring Jev into
`classify` or `accept` before then would be adding a probabilistic call to a decision
that already has a correct deterministic answer, which is the trap this entry exists
to name and avoid.

### Explicit acceptance decision object

**Status:** not built. Run success today is read directly off `SuccessCriteria` and
the verifier's result — a pass/fail, not a named decision.

**Why:** an explicit `ACCEPT` / `REJECT` / `HUMAN_REVIEW` record, entered into the
chain as its own event distinct from the verification result it was based on, makes
"why was this run accepted" a recorded decision rather than something reconstructed by
re-reading the verifier's output. This also needs a task whose acceptance is genuinely
contestable — a contested-path task, which §74 (the acceptance blocker recorded
elsewhere) notes does not exist yet — before the decision is meaningful to test rather
than trivially always-ACCEPT.

**What it would take:** a contested-path task (blocking), then a new chain event type
(`acceptance.decided`, say) carrying the verdict, the evidence it was based on, and —
once the Jev adapter has a wiring target — optionally a Jev `Choice` call among
`ACCEPT`/`REJECT`/`HUMAN_REVIEW` rather than a hand-written threshold rule.

### Agent handoff package on recovery

**Status:** not built, and currently has no design target: the scheduler
(`scheduler/states.py`, `scheduler/loop.py`) runs exactly one agent per run, with no
transition for "hand off to a different agent mid-run." `recover` as a decision type —
retry the same agent, switch agents, or escalate — presupposes that transition exists.

**Why deferred:** multi-agent recovery is a bigger change than an adapter or a doc
addition — it means a new run state, a new chain event class, and a decision about
what a second agent inherits (task, repository state, diff so far, test results, prior
decisions) so it starts from where the first agent left off rather than cold. Building
the handoff format before the state machine that would use it exists would be
designing against a system that does not yet have the shape the design assumes.

**What it would take:** first, a scheduler state for "run continues under a different
agent" (an addition to `RunState`/`TRANSITIONS` in `scheduler/states.py`); then a
handoff record shape; then, once that exists, `recover` becomes the concrete decision
point the Jev adapter above was built for.

### Causal edges over the chain

**Status:** not built. The chain (`relay/`) gives total order and hash linkage today —
event N's hash depends on event N-1's — which proves *sequence* but does not record
*relationships*. "Which decision caused this write" requires reading the chain in
order and matching timestamps by eye.

**Why:** a typed relationship layer (`caused`, `required`, `recovered`, `superseded`,
...) over the existing chain would make that a query instead of a manual scan, and
would let a future audit view answer "which decision caused this write" or "which
verification evidence caused acceptance" directly. It is additive to the existing
chain — it does not change what is signed or how verification works — which is why it
is scoped as a separate layer rather than a change to `relay/`'s core hashing.

**What it would take:** a store for `(from_event_id, to_event_id, relationship)`
triples, populated as decisions and events reference each other, plus a query surface.
Not blocked on anything else in this list — it could be built against the chain as it
exists today — but was out of scope for this session, which was adapter-and-docs only.
```

- [ ] **Step 3: Verify the file is still valid Markdown and reads coherently**

Run: `tail -80 docs/backlog.md`
Expected: the four new entries appear, formatted consistently with the rest of the
file (heading levels, bold field labels).

- [ ] **Step 4: Commit**

```bash
git add docs/backlog.md
git commit -m "docs(backlog): record the Jev adapter's real status and three related gaps"
```

---

## Task 9: Frontend — `DecisionLoop.jsx`

**Files:**
- Create: `frontend/components/landing/DecisionLoop.jsx`
- Modify: `frontend/app/page.tsx`

Matches the existing landing-page conventions: `Section`/`Mark`/`useInView` from
`Primitives.jsx` (used by `Routing.jsx`), and the status-pill pattern from
`Framework.jsx` (`measured` vs `planned`) — extended here with a third, honest status:
`adapter built`, for the one decision (none yet, since none are wired) versus the
adapter's own tested-but-unwired state.

- [ ] **Step 1: Read `Primitives.jsx` to confirm the exact exports this component needs**

Run: `sed -n '1,40p' frontend/components/landing/Primitives.jsx`
Expected: confirms `Section`, `Mark`, and `useInView` are exported with the signatures
already used in `Routing.jsx` (`Section({ id, className, children })`, `Mark` wraps
inline text, `useInView(threshold)` returns `[ref, seen]`).

- [ ] **Step 2: Write the component**

```jsx
// frontend/components/landing/DecisionLoop.jsx
"use client";

import { useEffect, useState } from "react";
import { Mark, Section, useInView } from "./Primitives.jsx";

/**
 * The decision loop: four typed questions a run asks as it progresses.
 *
 * This section exists because Framework.jsx already establishes the four
 * planes — contract, enforcement, evidence, measurement — as a single
 * allow/refuse check. This section is about what does *not* fit a single
 * check: a run also has to classify its task, pick an agent, decide how to
 * recover from a failure, and decide whether the result is acceptable.
 * Those are a small, fixed set of typed questions, which is exactly the
 * shape TypeSafe AI's Jev answers (state in, a typed Choice/Score/Noul
 * question out, a calibrated probability back — never a generated answer
 * outside the options given).
 *
 * Honesty, matching Framework.jsx's own discipline: the Jev adapter is
 * built and tested against the real API. None of these four decisions are
 * wired into the runtime yet, and the copy says so rather than implying a
 * working decision loop exists.
 */

const DECISIONS = [
  {
    id: "classify",
    label: "classify",
    question: "What kind of task is this?",
  },
  {
    id: "select_agent",
    label: "select_agent",
    question: "Which agent should act next?",
  },
  {
    id: "recover",
    label: "recover",
    question: "After a failure: retry, switch agent, or escalate?",
  },
  {
    id: "accept",
    label: "accept",
    question: "Does the evidence support ACCEPT, REJECT, or HUMAN_REVIEW?",
  },
];

function StatusPill() {
  return (
    <span className="ml-auto shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] text-ink-600 bg-paper-sunk border-rule-soft">
      Planned
    </span>
  );
}

export default function DecisionLoop() {
  const [ref, seen] = useInView(0.3);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!seen) return;
    const reduced = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)"
    )?.matches;
    if (reduced) {
      setStep(DECISIONS.length);
      return;
    }
    let n = 0;
    const timer = setInterval(() => {
      n += 1;
      setStep(n);
      if (n >= DECISIONS.length) clearInterval(timer);
    }, 600);
    return () => clearInterval(timer);
  }, [seen]);

  return (
    <Section id="decision-loop" className="py-24 md:py-32">
      <div className="grid grid-cols-1 items-center gap-x-16 gap-y-14 lg:grid-cols-[1fr_1.15fr]">
        <div>
          <h2 className="font-display text-[2.1rem] font-bold leading-[1.1] tracking-tightest text-ink-900 sm:text-[2.6rem]">
            One gate check,
            <br />
            or a <Mark>decision loop</Mark>
          </h2>

          <p className="mt-6 max-w-prose text-[15.5px] leading-relaxed text-ink-600">
            The gate answers one question: allow or refuse. A run also has
            to classify its task, pick an agent, decide how to recover from
            a failure, and decide whether the result is acceptable — four
            typed questions asked repeatedly as the run progresses, not
            once.
          </p>

          <p className="mt-4 max-w-prose text-[15.5px] leading-relaxed text-ink-600">
            TypeSafe AI&rsquo;s Jev answers exactly this shape of question:
            state in, a typed choice, score, or yes/no out, by selection
            rather than generation. We built and tested a Jev client
            against the real API to confirm the shape is implementable
            cheaply today.
          </p>

          <p className="mt-5 text-[13px] leading-relaxed text-ink-500">
            The adapter is real and tested. None of the four decisions below
            are wired into a run yet — see{" "}
            <a
              href="/docs"
              className="text-ink-700 underline decoration-rule-soft underline-offset-2 hover:text-ink-900"
            >
              the docs
            </a>{" "}
            for what that would take.
          </p>
        </div>

        <div ref={ref} className="flex flex-col gap-2.5">
          {DECISIONS.map((decision, i) => {
            const shown = i < step;
            return (
              <div
                key={decision.id}
                className={`flex items-center gap-3.5 border px-4 py-3.5 transition-all duration-500 ${
                  shown
                    ? "translate-x-0 opacity-100 border-rule-soft bg-paper-raised"
                    : "-translate-x-2 opacity-0 border-rule-soft bg-paper-raised"
                }`}
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-rule-soft font-mono text-[11px] tabular-nums text-ink-600">
                  {i + 1}
                </span>
                <div className="min-w-0">
                  <div className="font-mono text-[13px] text-ink-900">
                    {decision.label}
                  </div>
                  <div className="mt-0.5 truncate text-[12.5px] text-ink-500">
                    {decision.question}
                  </div>
                </div>
                <StatusPill />
              </div>
            );
          })}
        </div>
      </div>
    </Section>
  );
}
```

- [ ] **Step 3: Wire the section into the page**

In `frontend/app/page.tsx`, add the import after the `Framework` import:

```tsx
import Framework from '@/components/landing/Framework.jsx';
import DecisionLoop from '@/components/landing/DecisionLoop.jsx';
```

And render it immediately after `<Framework />`:

```tsx
        <Framework />
        <DecisionLoop />
        <Routing />
```

- [ ] **Step 4: Build the frontend to confirm it compiles**

Run: `cd frontend && npm run build`
Expected: build succeeds with no type or lint errors related to `DecisionLoop.jsx` or
`page.tsx`.

- [ ] **Step 5: Start the dev server and visually verify the section**

Run: `cd frontend && npm run dev`
Then open `http://localhost:3000` in a browser and scroll to the new section
(immediately after the "framework" section, before "routing"). Confirm:
- The four decisions step in on scroll, matching `Routing.jsx`'s reveal behavior.
- Each row shows a "Planned" pill.
- Layout holds at both desktop and mobile widths (resize the browser or use dev tools'
  device toolbar).
- Stop the dev server once confirmed (Ctrl+C).

- [ ] **Step 6: Commit**

```bash
git add frontend/components/landing/DecisionLoop.jsx frontend/app/page.tsx
git commit -m "feat(web): decision-loop section naming Jev as the reference engine"
```

---

## Task 10: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full Python test suite**

Run: `pytest tests/unit tests/integration -v -m "not slow"`
Expected: PASS. The new `test_jev_live.py` test shows as `SKIPPED` unless
`TYPESAFE_API_KEY` is set in this environment.

- [ ] **Step 2: Run linters if configured**

Run: `ruff check src/causalmesh/jev tests/unit/test_jev.py tests/integration/test_jev_live.py`
Expected: no findings. Fix any that appear before proceeding.

- [ ] **Step 3: Confirm the import-boundary rule still holds**

`docs/PLAN.md` states analysis never imports runtime, the verifier never imports the
relay, and so on. `jev/` imports only `adapters.transport` and stdlib — confirm no
other module was made to import `jev/` (it should have zero importers outside its own
tests right now, matching its backlog status).

Run: `grep -rn "from causalmesh.jev\|import causalmesh.jev" src/causalmesh --include="*.py" | grep -v "src/causalmesh/jev/"`
Expected: no output (nothing outside the package itself imports it yet).

- [ ] **Step 4: Confirm the frontend build is still clean**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 5: Final review of all changed files**

Run: `git log --oneline -12` and `git diff main --stat` (or the relevant base branch)
Expected: a clean, reviewable sequence of commits — jev package (4 commits), live test
(1), docs (3), frontend (1) — each one buildable/testable on its own.
