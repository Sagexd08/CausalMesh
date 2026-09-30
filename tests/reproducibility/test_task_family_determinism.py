"""The remaining §35 task families reproduce from their seed (spec §40, §84).

Same task, same arm, same seed: the same signed chain head and the same
workspace digests. The chain must contain nothing that differs between two
executions, so this also guards the two new fixtures and scenarios against
smuggling in a hostname, a wall-clock time or an absolute path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.tasks import RunConfig, TaskDefinition, execute_task

pytestmark = [pytest.mark.reproducibility, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures"
SEED = b"causalmesh-family-determinism-01"
OTHER_SEED = b"a-different-master-seed-of-32-b!"
TASK_IDS = ("interface_consumer", "shared_utility_refactor")


async def run(task_id: str, arm: str, seed: bytes, root: Path):
    task = TaskDefinition.from_yaml(REPO / "tasks" / f"{task_id}.yaml")
    return await execute_task(
        task,
        RunConfig(experiment_id="exp_determinism", run_id=f"run_{arm}", arm=arm, master_seed=seed),
        workspace_root=root,
        fixtures_root=FIXTURES,
    )


@pytest.mark.parametrize("task_id", TASK_IDS)
@pytest.mark.parametrize("arm", ["C0", "C2", "C3"])
async def test_the_same_seed_gives_the_same_head_hash(
    task_id: str, arm: str, tmp_path: Path
) -> None:
    first = await run(task_id, arm, SEED, tmp_path / "first")
    second = await run(task_id, arm, SEED, tmp_path / "second")
    assert first.head_hash == second.head_hash
    assert first.workspace_digests == second.workspace_digests
    assert first.succeeded == second.succeeded


@pytest.mark.parametrize("task_id", TASK_IDS)
async def test_a_different_seed_signs_the_same_events_differently(
    task_id: str, tmp_path: Path
) -> None:
    # The seed drives key derivation. The chain hash covers the events, not
    # the signatures, so what a different seed changes is who signed what:
    # signatures that ignored the seed would mean the chain was not being
    # signed with the run's own keys.
    first = await run(task_id, "C2", SEED, tmp_path / "first")
    second = await run(task_id, "C2", OTHER_SEED, tmp_path / "second")
    assert [r["signature"] for r in first.records] != [r["signature"] for r in second.records]
    # The outcome is a property of the task and the arm, not of the seed.
    assert first.succeeded == second.succeeded


@pytest.mark.parametrize("task_id", TASK_IDS)
async def test_the_arms_produce_different_chains(task_id: str, tmp_path: Path) -> None:
    c0 = await run(task_id, "C0", SEED, tmp_path / "c0")
    c2 = await run(task_id, "C2", SEED, tmp_path / "c2")
    assert c0.head_hash != c2.head_hash
