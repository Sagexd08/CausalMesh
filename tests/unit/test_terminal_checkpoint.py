"""`TerminalCheckpointHandler`: a person at a terminal decides a checkpoint.

The facts pinned here are the ones a safeguard depends on, not how the
prompt looks today (AGENTS.md, Testing): approval needs an explicit yes from
a person who was shown the question, and everything short of that refuses.
Streams are injected, so nothing here touches a real terminal.
"""

from __future__ import annotations

import io
import threading
import time

import pytest

from causalmesh.policy import Checkpoint, Resource, TerminalCheckpointHandler
from causalmesh.policy.checkpoints import evaluate_checkpoints

pytestmark = pytest.mark.unit

NOW = 1_000_000
CHECKPOINT = Checkpoint(on="path", require="human")
RESOURCE = Resource.path("src/a.py")


class Tty(io.StringIO):
    """A StringIO that claims to be an interactive terminal."""

    def isatty(self) -> bool:
        return True


class BlockedStream:
    """An input that never produces a line until released, like a silent terminal."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.lines: list[str] = []

    def readline(self) -> str:
        self.release.wait(timeout=30)
        return self.lines.pop(0) if self.lines else ""

    def isatty(self) -> bool:
        return True


class Broken:
    def readline(self) -> str:
        raise ValueError("I/O operation on closed file")


class DeadOutput:
    def write(self, text: str) -> int:
        raise OSError("broken pipe")

    def flush(self) -> None:
        raise OSError("broken pipe")


def handler(answers: str = "", **kwargs: object) -> tuple[TerminalCheckpointHandler, io.StringIO]:
    out = io.StringIO()
    source = kwargs.pop("input_stream", None) or io.StringIO(answers)
    return (
        TerminalCheckpointHandler(input_stream=source, output_stream=out, **kwargs),  # type: ignore[arg-type]
        out,
    )


def ask(h: TerminalCheckpointHandler, agent: str = "agent_a", resource: Resource = RESOURCE):
    return h.decide(agent_id=agent, resource=resource, checkpoint=CHECKPOINT, now_us=NOW)


class TestAnswers:
    @pytest.mark.parametrize("text", ["y", "Y", "yes", "YES", "  yes  "])
    def test_an_explicit_yes_approves(self, text: str) -> None:
        h, _ = handler(f"{text}\n")
        approved, reason = ask(h)
        assert approved is True
        assert "approved" in reason

    @pytest.mark.parametrize("text", ["n", "N", "no", "No"])
    def test_an_explicit_no_denies(self, text: str) -> None:
        h, _ = handler(f"{text}\n")
        approved, reason = ask(h)
        assert approved is False
        assert "denied" in reason

    @pytest.mark.parametrize("text", ["", "ok", "yep", "y es", "1", "true", "approve"])
    def test_nothing_but_yes_or_no_is_an_approval(self, text: str) -> None:
        h, _ = handler(f"{text}\n" * 3)
        approved, reason = ask(h)
        assert approved is False
        assert "no valid answer" in reason

    def test_an_unintelligible_answer_is_asked_again_then_a_yes_counts(self) -> None:
        h, _ = handler("maybe\nyes\n")
        approved, _ = ask(h)
        assert approved is True

    def test_re_prompts_are_bounded(self) -> None:
        h, _ = handler("what\nwhat\nwhat\nyes\n", max_attempts=3)
        approved, _ = ask(h)
        assert approved is False
        # The yes that came after the limit is left for the next question.
        assert ask(h)[0] is True

    def test_the_handler_satisfies_the_gate_protocol(self) -> None:
        h, _ = handler("y\n")
        decision = evaluate_checkpoints(
            (CHECKPOINT,), agent_id="a", resource=RESOURCE, handler=h, now_us=NOW
        )
        assert decision is not None and decision.approved


class TestEverythingShortOfYesRefuses:
    def test_end_of_input_denies(self) -> None:
        h, _ = handler("")
        approved, reason = ask(h)
        assert approved is False
        assert "input closed" in reason

    def test_after_end_of_input_it_keeps_denying_without_asking(self) -> None:
        h, out = handler("")
        ask(h)
        shown = out.getvalue()
        assert ask(h)[0] is False
        assert out.getvalue() == shown

    def test_a_closed_input_stream_denies(self) -> None:
        stream = io.StringIO("yes\n")
        stream.close()
        h, _ = handler(input_stream=stream)
        assert ask(h)[0] is False

    def test_an_input_that_raises_denies(self) -> None:
        h, _ = handler(input_stream=Broken())
        assert ask(h)[0] is False

    def test_an_input_that_raises_something_unexpected_denies_promptly(self) -> None:
        class Weird:
            def readline(self) -> str:
                raise RuntimeError("unexpected")

        h, _ = handler(input_stream=Weird(), timeout_s=30)
        started = time.monotonic()
        assert ask(h)[0] is False
        assert time.monotonic() - started < 5

    def test_a_missing_terminal_denies_without_prompting_when_one_is_required(self) -> None:
        h, out = handler("yes\n", require_tty=True)
        approved, reason = ask(h)
        assert approved is False
        assert "no interactive terminal" in reason
        assert out.getvalue() == ""

    def test_a_terminal_satisfies_require_tty(self) -> None:
        out = io.StringIO()
        h = TerminalCheckpointHandler(
            input_stream=Tty("yes\n"), output_stream=out, require_tty=True
        )
        assert ask(h)[0] is True

    def test_a_stream_without_isatty_is_not_a_terminal(self) -> None:
        h, _ = handler(input_stream=Broken(), require_tty=True)
        approved, reason = ask(h)
        assert approved is False
        assert "no interactive terminal" in reason

    def test_an_output_that_cannot_show_the_question_denies(self) -> None:
        h = TerminalCheckpointHandler(
            input_stream=io.StringIO("yes\n"),
            output_stream=DeadOutput(),  # type: ignore[arg-type]
        )
        approved, reason = ask(h)
        assert approved is False
        assert "could not show the prompt" in reason


class TestTimeout:
    def test_silence_denies_after_the_deadline_and_never_blocks_forever(self) -> None:
        silent = BlockedStream()
        h, _ = handler(input_stream=silent, timeout_s=0.2)
        started = time.monotonic()
        approved, reason = ask(h)
        elapsed = time.monotonic() - started
        silent.release.set()
        assert approved is False
        assert "no answer within" in reason
        assert elapsed < 5

    def test_a_late_answer_is_not_the_answer_to_the_next_question(self) -> None:
        silent = BlockedStream()
        h, _ = handler(input_stream=silent, timeout_s=0.2)
        assert ask(h)[0] is False

        # The person finally types "yes", to the question already refused.
        silent.lines = ["yes\n", "no\n"]
        silent.release.set()
        approved, _ = ask(h)

        assert approved is False, "a stale yes must not approve a later question"

    def test_the_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="timeout_s"):
            TerminalCheckpointHandler(timeout_s=0)
        with pytest.raises(ValueError, match="max_attempts"):
            TerminalCheckpointHandler(max_attempts=0)


class TestConcurrentAgents:
    def test_prompts_do_not_interleave_and_each_answer_belongs_to_its_question(self) -> None:
        out = io.StringIO()
        gate = threading.Event()

        class Slow(io.StringIO):
            def readline(self, *args: object) -> str:
                gate.wait(timeout=5)
                return super().readline(*args)

        h = TerminalCheckpointHandler(input_stream=Slow("yes\nno\nyes\n"), output_stream=out)
        results: dict[str, bool] = {}

        def worker(name: str) -> None:
            results[name] = ask(h, agent=name)[0]

        threads = [threading.Thread(target=worker, args=(f"agent_{i}",)) for i in range(3)]
        for thread in threads:
            thread.start()
        time.sleep(0.2)
        gate.set()
        for thread in threads:
            thread.join(timeout=10)

        text = out.getvalue()
        # Three complete questions, each followed by its own prompt before the next header.
        headers = [i for i in range(len(text)) if text.startswith("=== checkpoint #", i)]
        assert len(headers) == 3
        for start, end in zip(headers, [*headers[1:], len(text)], strict=True):
            assert text[start:end].count("Approve?") == 1
        assert sorted(results.values()) == [False, True, True]


class TestDecisionsLog:
    def test_every_decision_is_logged_with_the_fact_that_decided_it(self) -> None:
        h, _ = handler("yes\nno\n", input_stream=None)
        ask(h, agent="a1")
        ask(h, agent="a2", resource=Resource.path("src/b.py"))
        log = h.decisions()
        assert [entry["agent_id"] for entry in log] == ["a1", "a2"]
        assert [entry["approved"] for entry in log] == [True, False]
        assert [entry["outcome"] for entry in log] == ["answered", "answered"]
        assert log[1]["resource"]["identity"] == "path:src/b.py"
        assert log[0]["now_us"] == NOW
        assert [entry["sequence"] for entry in log] == [1, 2]

    def test_refusals_from_failures_are_logged_too(self) -> None:
        h, _ = handler("")
        ask(h)
        (entry,) = h.decisions()
        assert entry["approved"] is False
        assert entry["outcome"] == "eof"

    def test_the_log_is_a_copy(self) -> None:
        h, _ = handler("yes\n")
        ask(h)
        h.decisions()[0]["approved"] = False
        assert h.decisions()[0]["approved"] is True

    def test_it_declares_itself_not_reproducible(self) -> None:
        assert TerminalCheckpointHandler.deterministic is False
