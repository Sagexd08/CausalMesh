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
