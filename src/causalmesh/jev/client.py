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
from .response import JevResponse, JevResponseError, parse_response

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

    @property
    def provider(self) -> str:
        # Matches OpenAIClient/AnthropicClient/LocalClient's `provider`
        # property (adapters/clients.py), so anything that logs or records
        # "which adapter answered this" — a run artifact's envelope, say —
        # has one consistent attribute to read across every client rather
        # than a special case for Jev.
        return "jev"

    def ask(self, *, state: dict[str, Any], questions: Sequence[Question]) -> JevResponse:
        """Evaluate `state` against every question, in one request.

        Jev evaluates all questions in a request in parallel, so asking
        several things at once costs about the same latency as asking one
        — batch related questions into a single `ask()` call rather than
        issuing one per question.

        Raises `ValueError` before any request is sent for an empty
        `questions` sequence or a duplicate question id: a `dict`
        comprehension keyed by id would otherwise silently drop the earlier
        of two questions sharing an id, sending fewer questions than the
        caller asked for with nothing to indicate why. After the response
        comes back, raises `JevResponseError` (via `parse_response`) if an
        answer names an option that was never offered, or if any question
        asked has no corresponding answer in the reply.
        """
        if not questions:
            raise ValueError("ask() requires at least one question")

        by_id: dict[str, Question] = {}
        for q in questions:
            if q.id in by_id:
                raise ValueError(f"duplicate question id {q.id!r} in a single ask() call")
            by_id[q.id] = q

        body = {
            "state": state,
            "questions": {q.id: q.to_dict() for q in by_id.values()},
        }
        decoded, _latency_ms = self._transport.post_json("systemone", body)
        response = parse_response(decoded, questions=by_id)

        missing = sorted(by_id.keys() - response.answers.keys())
        if missing:
            raise JevResponseError(
                f"Jev did not answer question(s) {missing}; asked "
                f"{sorted(by_id)}, answered {sorted(response.answers)}"
            )
        return response
