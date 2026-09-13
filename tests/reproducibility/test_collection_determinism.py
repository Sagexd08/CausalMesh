"""A whole collection reproduces from its seed (spec §40, §84).

`test_chain_determinism.py` covers a single run. This covers the layer
above it: the plan, the ordering, the per-run seed derivation and the
resulting chains, all from one master seed.

The distinction matters because the scheduler introduces new opportunities
for nondeterminism that a single run cannot expose — an order that depends
on dict iteration, a seed that depends on when a run happened to execute,
an id that embeds a timestamp. Each would leave individual runs perfectly
reproducible while making the collection irreproducible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.experiments import (
    derive_run_seed,
    plan_experiment,
    profile,
)
from causalmesh.scheduler import ExperimentRunner, RunEnvironment
from causalmesh.tasks import TaskDefinition

pytestmark = pytest.mark.reproducibility

REPO = Path(__file__).resolve().parents[2]
TASK_PATH = REPO / "tasks" / "schema_handler_widen.yaml"
FIXTURES = REPO / "fixtures"
SEED = b"causalmesh-collection-determinism"


class TestPlanDeterminism:
    """Cheap structural checks — no execution needed."""

    def test_the_plan_is_identical_across_constructions(self) -> None:
        def build():
            return plan_experiment(
                experiment_id="exp",
                profile=profile("medium"),
                task_ids=["t1", "t2", "t3"],
                master_seed=SEED,
            )

        first, second = build(), build()
        assert first.content_hash() == second.content_hash()
        assert [r.run_id for r in first.runs] == [r.run_id for r in second.runs]
        assert [r.order for r in first.runs] == [r.order for r in second.runs]

    def test_task_order_does_not_affect_the_plan(self) -> None:
        """A plan must not depend on how tasks were discovered.

        Task ids arrive from a directory listing, whose order is a
        filesystem detail. If it leaked into the plan, two machines would
        run the same experiment in different orders while both believing
        they had reproduced it.
        """
        forward = plan_experiment(
            experiment_id="exp",
            profile=profile("pilot"),
            task_ids=["alpha", "beta", "gamma"],
            master_seed=SEED,
        )
        backward = plan_experiment(
            experiment_id="exp",
            profile=profile("pilot"),
            task_ids=["gamma", "alpha", "beta"],
            master_seed=SEED,
        )
        assert forward.content_hash() == backward.content_hash()

    def test_run_seeds_are_a_pure_function_of_seed_and_run_id(self) -> None:
        # Not of execution order, wall-clock time, or anything else that
        # would differ between a first run and a resume.
        plan = plan_experiment(
            experiment_id="exp",
            profile=profile("pilot"),
            task_ids=["t1"],
            master_seed=SEED,
        )
        first = {r.run_id: derive_run_seed(SEED, r.run_id) for r in plan.runs}
        second = {r.run_id: derive_run_seed(SEED, r.run_id) for r in reversed(plan.runs)}
        assert first == second

    def test_the_experiment_id_changes_the_order(self) -> None:
        # Two collections of the same tasks must not share an order, or
        # any order effect would repeat identically across them.
        a = plan_experiment(
            experiment_id="exp_a",
            profile=profile("small"),
            task_ids=["t1", "t2"],
            master_seed=SEED,
        )
        b = plan_experiment(
            experiment_id="exp_b",
            profile=profile("small"),
            task_ids=["t1", "t2"],
            master_seed=SEED,
        )
        assert [r.arm for r in a.runs] != [r.arm for r in b.runs]


@pytest.mark.slow
@pytest.mark.integration
class TestExecutedCollectionDeterminism:
    """The expensive check: two real collections must agree."""

    async def test_two_collections_produce_identical_chains(
        self, tmp_path: Path
    ) -> None:
        """§84 at collection scale.

        Compared per run id rather than as a set: a collection that
        produced all the right hashes but attached them to the wrong runs
        would otherwise pass.
        """
        task = TaskDefinition.from_yaml(TASK_PATH)

        async def collect(where: Path) -> dict[str, tuple]:
            plan = plan_experiment(
                experiment_id="exp_repro",
                profile=profile("smoke"),
                task_ids=[task.task_id],
                master_seed=SEED,
                task_hashes={task.task_id: task.content_hash()},
            )
            environment = RunEnvironment(
                fixtures_root=FIXTURES,
                raw_root=where / "raw",
                workspace_root=where / "work",
                index_path=where / "raw" / "index.db",
            )
            with ExperimentRunner(
                plan=plan,
                tasks={task.task_id: task},
                environment=environment,
                master_seed=SEED,
            ) as runner:
                runner.prepare()
                await runner.run()
                return {
                    record.run_id: (record.arm, record.head_hash, record.succeeded)
                    for record in runner.index.runs("exp_repro")
                }

        first = await collect(tmp_path / "first")
        second = await collect(tmp_path / "second")
        assert first == second
        # Guard against a vacuous pass: two empty dicts are also equal.
        assert len(first) == 4
