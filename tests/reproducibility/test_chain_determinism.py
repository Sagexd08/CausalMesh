"""Chain reproducibility across identical runs (spec §84, §42).

§84 requires that the same seed, task, configuration and mock agent produce
an equivalent chain. That is only true if **nothing non-reproducible reaches
the signed payload**, and two such leaks were found by an earlier version of
these tests:

- `duration_us`, a wall-clock measurement, was written into every event;
- command `stdout`/`stderr` were, and `pytest -q` prints "1 passed in 0.73s"
  with the elapsed time differing every run.

Both are still *measured* — the lifecycle boundary records timing for §85,
and full command output is kept as a run artifact — but neither enters the
integrity record. These tests pin that separation, because the failure mode
is silent: chains simply stop matching, with nothing to say why.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.crypto.keys import KeyPair
from causalmesh.events.schema import EventIdentity
from causalmesh.hooks import LifecycleBoundary
from causalmesh.isolation import build_run_workspaces
from causalmesh.relay import Relay, policy_for_arm
from causalmesh.tools import Toolbox, ToolExecutor
from causalmesh.tools.api import CommandResult

pytestmark = pytest.mark.reproducibility

SEED = b"causalmesh-determinism-seed-0001"
RUN = "run_001"
BASE_TIME = 1_700_000_000_000_000


def build_runtime(tmp_path: Path, label: str) -> tuple[Relay, ToolExecutor]:
    fixture = tmp_path / "fixture"
    (fixture / "src").mkdir(parents=True, exist_ok=True)
    (fixture / "src" / "schema.py").write_text("FIELDS = ['id']\n", encoding="utf-8")
    (fixture / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )

    workspaces = build_run_workspaces(
        base=tmp_path / label / "ws", run_id=RUN, agent_ids=["agent_a"], fixture=fixture
    )
    relay = Relay(
        run_id=RUN,
        keypairs={"agent_a": KeyPair.derive(SEED, "agent_a")},
        delivery=policy_for_arm("C2"),
        participants=["agent_a"],
    )
    executor = ToolExecutor(
        agent_id="agent_a",
        identity=EventIdentity(
            experiment_id="exp_det",
            task_id="task_det",
            run_id=RUN,
            agent_id="agent_a",
            arm="C2",
        ),
        toolbox=Toolbox(workspaces["agent_a"]),
        boundary=LifecycleBoundary(),
        relay=relay,
    )
    return relay, executor


class TestPayloadDeterminism:
    def test_two_identical_file_runs_produce_the_same_chain(
        self, tmp_path: Path
    ) -> None:
        heads = []
        for index in range(2):
            relay, executor = build_runtime(tmp_path, f"run_{index}")
            executor.call(
                "read_file", now_us=BASE_TIME, paths=("src/schema.py",), path="src/schema.py"
            )
            executor.call(
                "write_file",
                now_us=BASE_TIME + 1,
                paths=("src/schema.py",),
                path="src/schema.py",
                content="FIELDS = ['id', 'email']\n",
            )
            heads.append(relay.head_hash)
        assert heads[0] == heads[1]

    def test_wall_clock_duration_never_reaches_the_payload(
        self, tmp_path: Path
    ) -> None:
        """The first leak, pinned.

        Duration is measured — the boundary records it — but it varies
        between runs, so it must not be inside the hashed payload.
        """
        relay, executor = build_runtime(tmp_path, "durations")
        result = executor.call(
            "read_file", now_us=BASE_TIME, paths=("src/schema.py",), path="src/schema.py"
        )

        payload = relay.records()[0]["event"]["payload"]
        assert "duration_us" not in payload
        # Still measured, just not in the chain.
        assert result.duration_us >= 0
        assert executor.boundary.results[0].duration_us >= 0

    def test_running_tests_twice_produces_the_same_chain(
        self, tmp_path: Path
    ) -> None:
        """The second leak, pinned.

        `pytest -q` reports its own elapsed time, so including command
        output would break reproducibility for every scenario that runs
        tests — which is most of them.
        """
        heads = []
        for index in range(2):
            relay, executor = build_runtime(tmp_path, f"tests_{index}")
            executor.call("run_tests", now_us=BASE_TIME, paths=())
            heads.append(relay.head_hash)
        assert heads[0] == heads[1]

    def test_command_output_is_absent_from_the_payload(self, tmp_path: Path) -> None:
        relay, executor = build_runtime(tmp_path, "output")
        executor.call("run_tests", now_us=BASE_TIME, paths=())

        payload = relay.records()[0]["event"]["payload"]
        assert "stdout" not in payload
        assert "stderr" not in payload
        # What the analysis actually needs is still there.
        assert "exit_code" in payload
        assert "command" in payload
        assert "timed_out" in payload

    def test_the_payload_carries_no_digest_of_the_output(self, tmp_path: Path) -> None:
        """A digest of non-reproducible bytes is still non-reproducible.

        An earlier version included `output_sha256` and reintroduced the
        very failure it was meant to fix, hidden behind a hash rather than
        visible as text. The full output lives in the run artifact instead.
        """
        relay, executor = build_runtime(tmp_path, "digest")
        executor.call("run_tests", now_us=BASE_TIME, paths=())
        assert "output_sha256" not in relay.records()[0]["event"]["payload"]

    def test_a_failing_command_still_records_its_exit_code(
        self, tmp_path: Path
    ) -> None:
        # §38: success is decided from the exit code, so it must survive.
        relay, executor = build_runtime(tmp_path, "failing")
        executor.call(
            "run_command", now_us=BASE_TIME, paths=(), command=["python", "-c", "raise SystemExit(3)"]
        )
        assert relay.records()[0]["event"]["payload"]["exit_code"] == 3


class TestCommandResultSeparation:
    def test_the_event_payload_excludes_output(self) -> None:
        result = CommandResult(
            command=("pytest", "-q"), exit_code=0, stdout="1 passed in 0.73s", stderr=""
        )
        assert "stdout" not in result.to_event_payload()
        assert "stderr" not in result.to_event_payload()

    def test_the_full_dict_retains_output_for_artifacts(self) -> None:
        # Debugging a failed run needs the output; it just lives elsewhere.
        result = CommandResult(
            command=("pytest", "-q"), exit_code=1, stdout="F", stderr="boom"
        )
        assert result.to_dict()["stdout"] == "F"
        assert result.to_dict()["stderr"] == "boom"

    def test_differing_output_yields_an_identical_event_payload(self) -> None:
        """The property the chain depends on, stated directly.

        Two runs of the same command differing only in reported timing must
        produce byte-identical payloads. Anything derived from the output —
        including a digest — would break this.
        """
        first = CommandResult(("pytest", "-q"), 0, "1 passed in 0.73s", "")
        second = CommandResult(("pytest", "-q"), 0, "1 passed in 0.76s", "")
        assert first.to_event_payload() == second.to_event_payload()


class TestEventOrdering:
    def test_sequence_numbers_are_reproducible(self, tmp_path: Path) -> None:
        sequences = []
        for index in range(2):
            relay, executor = build_runtime(tmp_path, f"seq_{index}")
            for step in range(3):
                executor.call(
                    "write_file",
                    now_us=BASE_TIME + step,
                    paths=(f"src/f{step}.py",),
                    path=f"src/f{step}.py",
                    content=f"# {step}\n",
                )
            sequences.append([r["event"]["sequence"] for r in relay.records()])
        assert sequences[0] == sequences[1] == [0, 1, 2]

    def test_event_ids_are_reproducible(self, tmp_path: Path) -> None:
        # §42: stable identifiers, so a duplicate operation is detectable.
        ids = []
        for index in range(2):
            relay, executor = build_runtime(tmp_path, f"ids_{index}")
            executor.call(
                "read_file", now_us=BASE_TIME, paths=("src/schema.py",), path="src/schema.py"
            )
            ids.append([r["event"]["event_id"] for r in relay.records()])
        assert ids[0] == ids[1]

    def test_signatures_are_byte_identical_across_runs(self, tmp_path: Path) -> None:
        # Ed25519 is deterministic and keys are derived, so a reproduced run
        # yields identical signatures rather than merely valid ones.
        signatures = []
        for index in range(2):
            relay, executor = build_runtime(tmp_path, f"sig_{index}")
            executor.call(
                "read_file", now_us=BASE_TIME, paths=("src/schema.py",), path="src/schema.py"
            )
            signatures.append([r["signature"] for r in relay.records()])
        assert signatures[0] == signatures[1]
