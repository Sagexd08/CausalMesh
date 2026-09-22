# tests/unit/test_jev.py
"""Unit tests for the Jev adapter (TypeSafe AI's typed decision engine).

Jev returns typed, calibrated answers instead of text: a Choice question
gets back the chosen option plus a probability per option; a Score question
gets back a level plus a probability per level; a Noul question gets back a
single probability. These tests cover parsing that response shape with no
network involved — the live-API proof is in tests/integration/test_jev_live.py.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from causalmesh.jev.client import JevClient
from causalmesh.jev.questions import Choice, Noul, Score
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
        assert isinstance(response, JevResponse)
        assert response.model == "jev-2026-09"


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


class TestJevClientConstruction:
    def test_requires_an_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True), pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
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
