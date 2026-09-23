"""The policy plane: resources, the contract, the gate and the ledger.

The claim being tested is the one the framework rests on: **a refused write
and a refused payment are the same event**. So the gate is exercised across
all four resource kinds through one interface, and the tests that matter most
are the ones where a near-miss must NOT be treated as a match — an allowlist
that covers a lookalike domain, or an ownership rule that claims a
neighbour's file, fails open, and a gate that fails open enforces nothing.

Money is tested for exactness rather than approximately. A budget compared as
float drifts by fractions of a cent until it silently does not hold, which is
the same defect class as the enforcement bug in `docs/backlog.md`: a
confident wrong answer rather than a loud failure.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from causalmesh.claims.registry import ClaimRegistry
from causalmesh.policy import (
    Checkpoint,
    Contract,
    ContractError,
    Gate,
    Ledger,
    Resource,
    ResourceError,
    ResourceKind,
    ScriptedHandler,
)

pytestmark = [pytest.mark.unit]

NOW = 1_000_000


@pytest.fixture
def contract() -> Contract:
    return Contract.from_dict(
        {
            "version": 1,
            "roles": [
                {
                    "agent_id": "agent_a",
                    "archetype": "writer",
                    "owns": ["src/schema.py", "src/models/"],
                },
                {"agent_id": "agent_b", "archetype": "writer", "owns": ["src/handlers/"]},
                {
                    "agent_id": "buyer",
                    "archetype": "spender",
                    "allow": ["api.example.com", "data.vendor.io"],
                    "budget": {"usd_total": "5.00", "usd_per_call": "0.10"},
                },
            ],
            "policy": {
                "arm": "C3",
                "contested": {"src/config.py": "exclusive"},
                "budgets": {"tokens": 200000},
            },
        }
    )


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    with Ledger(tmp_path / "ledger.db", run_id="run1") as opened:
        yield opened


@pytest.fixture
def registry(tmp_path: Path) -> ClaimRegistry:
    with ClaimRegistry(tmp_path / "claims.db") as opened:
        yield opened


def gate_for(contract: Contract, **kwargs) -> Gate:
    return Gate(contract, run_id="run1", **kwargs)


class TestResourceIdentity:
    def test_kinds_never_collide(self) -> None:
        """A file named like a host is not that host.

        Without the kind prefix a lease on one would refuse the other, which
        refuses the wrong action while reporting success.
        """
        name = "premium.unknown.io"
        assert Resource.path(name).identity != Resource.endpoint(name).identity

    def test_separators_are_one_resource(self) -> None:
        """`src\\a.py` and `src/a.py` are the same file.

        Two spellings producing two claims means exclusivity silently does
        not hold between them.
        """
        windows = "src" + chr(92) + "a.py"
        assert Resource.path(windows).identity == Resource.path("src/a.py").identity

    def test_hosts_fold_case(self) -> None:
        assert Resource.spend(to="API.Example.COM", amount="1").identity == (
            Resource.spend(to="api.example.com", amount="1").identity
        )

    def test_a_float_amount_is_refused(self) -> None:
        """Rejected at the call site that introduced the imprecision."""
        with pytest.raises(ResourceError, match="float"):
            Resource.spend(to="api.example.com", amount=0.1)  # type: ignore[arg-type]

    def test_identity_round_trips(self) -> None:
        original = Resource.path("src/config.py")
        assert Resource.parse(original.identity).identity == original.identity

    def test_an_unknown_kind_raises_rather_than_parsing(self) -> None:
        with pytest.raises(ResourceError, match="unknown resource kind"):
            Resource.parse("paymnt:api.example.com")

    def test_a_consumable_without_an_amount_raises(self) -> None:
        with pytest.raises(ResourceError, match="require an amount"):
            Resource(kind=ResourceKind.SPEND, name="api.example.com")


class TestContract:
    def test_a_typo_is_an_error_not_a_shrug(self) -> None:
        """A misspelled budget key is a budget that does not exist."""
        with pytest.raises(ContractError, match="unknown key"):
            Contract.from_dict(
                {"version": 1, "roles": [{"agent_id": "a", "budget": {"usd_totl": "5"}}]}
            )

    def test_a_float_budget_is_refused(self) -> None:
        with pytest.raises(ContractError, match="float"):
            Contract.from_dict(
                {"version": 1, "roles": [{"agent_id": "a", "budget": {"usd_total": 5.10}}]}
            )

    def test_an_unsupported_version_is_refused(self) -> None:
        with pytest.raises(ContractError, match="not supported"):
            Contract.from_dict({"version": 99})

    def test_duplicate_agents_are_refused(self) -> None:
        with pytest.raises(ContractError, match="duplicate agent_id"):
            Contract.from_dict({"version": 1, "roles": [{"agent_id": "a"}, {"agent_id": "a"}]})

    def test_the_longest_declaration_wins(self) -> None:
        """Carving one contested file out of a directory must be expressible."""
        contract = Contract.from_dict(
            {
                "version": 1,
                "roles": [
                    {"agent_id": "broad", "owns": ["src/"]},
                    {"agent_id": "specific", "owns": ["src/config.py"]},
                ],
            }
        )
        assert contract.owner_of("src/config.py") == "specific"
        assert contract.owner_of("src/other.py") == "broad"

    def test_an_undeclared_path_has_no_owner(self, contract: Contract) -> None:
        """The contract states exceptions, not a map of the repository."""
        assert contract.owner_of("README.md") is None

    def test_round_trips_through_a_file(self, tmp_path: Path, contract: Contract) -> None:
        import yaml

        path = tmp_path / "causalmesh.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "roles": [{"agent_id": "agent_a", "owns": ["src/schema.py"]}],
                    "policy": {"arm": "C2"},
                }
            ),
            encoding="utf-8",
        )
        loaded = Contract.load(path)
        assert loaded.arm == "C2"
        assert loaded.owner_of("src/schema.py") == "agent_a"

    def test_identity_keys_dir_is_parsed(self) -> None:
        """`identity.keys` (a directory of per-agent seed files) now has a

        real consumer: `load_identity_keys` (crypto/keys.py), wired in by
        `tasks/runner.py`. See `docs/backlog.md`, "Checkpoints and identity
        are parsed and ignored" -- this is the "identity" half becoming real.
        """
        contract = Contract.from_dict(
            {"version": 1, "identity": {"keys": ".causalmesh/keys/"}}
        )
        assert contract.identity_keys_dir == Path(".causalmesh/keys/")

    def test_identity_without_keys_has_no_dir(self) -> None:
        assert Contract.from_dict({"version": 1}).identity_keys_dir is None

    def test_identity_must_be_a_mapping(self) -> None:
        with pytest.raises(ContractError, match="identity.*mapping"):
            Contract.from_dict({"version": 1, "identity": "not-a-mapping"})

    def test_an_identity_typo_is_an_error_not_a_shrug(self) -> None:
        with pytest.raises(ContractError, match="unknown key"):
            Contract.from_dict({"version": 1, "identity": {"key": ".causalmesh/keys/"}})

    def test_checkpoints_are_parsed(self) -> None:
        """`policy.checkpoints` (human-in-the-loop rules) now has a real

        consumer: `Gate` consults them after every other rule allows (see
        `TestCheckpoints` below). See docs/backlog.md's "Checkpoints and
        identity are parsed and ignored" -- this is the "checkpoints" half
        becoming real.
        """
        contract = Contract.from_dict(
            {
                "version": 1,
                "policy": {
                    "checkpoints": [
                        {"on": "spend", "when": {"usd": ">0.50"}, "require": "human"},
                    ],
                },
            }
        )
        assert len(contract.checkpoints) == 1
        checkpoint = contract.checkpoints[0]
        assert checkpoint.on == "spend"
        assert checkpoint.when == {"usd": ">0.50"}
        assert checkpoint.require == "human"

    def test_checkpoints_default_empty(self) -> None:
        assert Contract.from_dict({"version": 1}).checkpoints == ()

    def test_a_checkpoint_without_on_is_refused(self) -> None:
        with pytest.raises(ContractError, match="`on`"):
            Contract.from_dict(
                {"version": 1, "policy": {"checkpoints": [{"require": "human"}]}}
            )

    def test_a_checkpoint_typo_is_an_error_not_a_shrug(self) -> None:
        with pytest.raises(ContractError, match="unknown key"):
            Contract.from_dict(
                {
                    "version": 1,
                    "policy": {"checkpoints": [{"on": "spend", "requires": "human"}]},
                }
            )

    def test_verify_on_exit_is_a_known_evidence_key(self) -> None:
        """Unlike `identity`/`checkpoints`, `verify_on_exit` is real and used

        today -- this repository's own causalmesh.yaml sets it. It must
        parse rather than raise.
        """
        contract = Contract.from_dict(
            {"version": 1, "evidence": {"sign": True, "verify_on_exit": True}}
        )
        assert contract.verify_on_exit is True

    def test_verify_on_exit_defaults_true(self) -> None:
        assert Contract.from_dict({"version": 1}).verify_on_exit is True

    def test_an_evidence_typo_is_an_error_not_a_shrug(self) -> None:
        """The same rule `policy.budgets` already gets: a typo silently

        parsing as nothing is worse than a typo that fails the load.
        """
        with pytest.raises(ContractError, match="unknown key"):
            Contract.from_dict({"version": 1, "evidence": {"verfy_on_exit": True}})


class TestOwnership:
    @pytest.mark.parametrize(
        ("path", "refused"),
        [
            ("src/schema.py", True),
            ("src/models/user.py", True),
            # A prefix test without segment boundaries claims a neighbour's
            # file. `src/models` must not cover `src/models_old.py`.
            ("src/models_old.py", False),
            ("README.md", False),
        ],
    )
    def test_ownership_matches_on_segment_boundaries(
        self, contract: Contract, path: str, refused: bool
    ) -> None:
        verdict = gate_for(contract).check(
            agent_id="agent_b", resource=Resource.path(path), now_us=NOW
        )
        assert verdict.refused is refused

    def test_an_owner_may_write_its_own_path(self, contract: Contract) -> None:
        verdict = gate_for(contract).check(
            agent_id="agent_a", resource=Resource.path("src/schema.py"), now_us=NOW
        )
        assert verdict.allowed


class TestAllowlist:
    @pytest.mark.parametrize(
        ("host", "allowed"),
        [
            ("api.example.com", True),
            ("data.vendor.io", True),
            # The ones that must fail. A naive `endswith` lets every one of
            # these through, which is how an allowlist silently fails open.
            ("notapi.example.com", False),
            ("api.example.com.evil.io", False),
            ("evil.io", False),
        ],
    )
    def test_subdomains_match_only_on_label_boundaries(
        self, contract: Contract, host: str, allowed: bool
    ) -> None:
        verdict = gate_for(contract).check(
            agent_id="buyer", resource=Resource.spend(to=host, amount="0.01"), now_us=NOW
        )
        assert verdict.allowed is allowed

    def test_a_port_or_path_does_not_defeat_the_allowlist(self, contract: Contract) -> None:
        verdict = gate_for(contract).check(
            agent_id="buyer",
            resource=Resource.spend(to="api.example.com:443/v1/data", amount="0.01"),
            now_us=NOW,
        )
        assert verdict.allowed

    def test_no_allowlist_means_unrestricted(self, contract: Contract) -> None:
        """Absent is permissive so adoption is incremental, not a rewrite."""
        verdict = gate_for(contract).check(
            agent_id="agent_a", resource=Resource.spend(to="anywhere.io", amount="0.01"), now_us=NOW
        )
        assert verdict.allowed

    def test_an_empty_allowlist_means_nothing(self) -> None:
        contract = Contract.from_dict(
            {"version": 1, "roles": [{"agent_id": "locked", "allow": []}]}
        )
        verdict = gate_for(contract).check(
            agent_id="locked",
            resource=Resource.spend(to="api.example.com", amount="0.01"),
            now_us=NOW,
        )
        assert verdict.refused


class TestBudgets:
    def test_a_single_call_over_the_ceiling_is_refused(self, contract: Contract) -> None:
        verdict = gate_for(contract).check(
            agent_id="buyer",
            resource=Resource.spend(to="api.example.com", amount="0.50"),
            now_us=NOW,
        )
        assert verdict.refused
        assert verdict.rule == "ceiling"

    def test_the_total_holds_exactly_at_the_limit(self, contract: Contract, ledger: Ledger) -> None:
        """100 x 0.05 is 5.00 exactly, and the limit is inclusive.

        Float arithmetic reaches 5.000000000000004 here and refuses a spend
        that is within budget.
        """
        gate = gate_for(contract)
        gate.attach_ledger(ledger)
        nickel = Resource.spend(to="api.example.com", amount="0.05")
        for _ in range(99):
            ledger.record(agent_id="buyer", resource=nickel, now_us=NOW)

        assert ledger.total(agent_id="buyer", resource=nickel) == Decimal("4.95")
        assert gate.check(agent_id="buyer", resource=nickel, now_us=NOW).allowed

        ledger.record(agent_id="buyer", resource=nickel, now_us=NOW)
        assert ledger.total(agent_id="buyer", resource=nickel) == Decimal("5.00")
        exceeded = gate.check(agent_id="buyer", resource=nickel, now_us=NOW)
        assert exceeded.refused
        assert exceeded.rule == "budget"

    def test_a_token_budget_refuses_the_runaway_loop(self, contract: Contract) -> None:
        """The open-ended agent loop, refused rather than invoiced."""
        verdict = gate_for(contract).check(
            agent_id="agent_a",
            resource=Resource.budget(name="tokens", amount=250_000, unit="tokens"),
            now_us=NOW,
        )
        assert verdict.refused
        assert verdict.rule == "budget"

    def test_a_role_budget_overrides_the_run_budget(self) -> None:
        contract = Contract.from_dict(
            {
                "version": 1,
                "roles": [{"agent_id": "a", "budget": {"tokens": 10}}],
                "policy": {"budgets": {"tokens": 1_000_000}},
            }
        )
        verdict = gate_for(contract).check(
            agent_id="a", resource=Resource.budget(name="tokens", amount=50), now_us=NOW
        )
        assert verdict.refused

    def test_a_ledger_is_shared_across_connections(self, tmp_path: Path) -> None:
        """Two processes must not each get the whole budget.

        A second Ledger over the same file stands in for a second process;
        an in-memory counter passes a single-process test and fails here.
        """
        spend = Resource.spend(to="api.example.com", amount="1.00")
        with Ledger(tmp_path / "shared.db", run_id="run1") as first:
            first.record(agent_id="buyer", resource=spend, now_us=NOW)
        with Ledger(tmp_path / "shared.db", run_id="run1") as second:
            assert second.total(agent_id="buyer", resource=spend) == Decimal("1.00")

    def test_a_gate_without_a_ledger_allows_rather_than_failing(self, contract: Contract) -> None:
        """Missing data must not silently refuse everything."""
        verdict = gate_for(contract).check(
            agent_id="buyer",
            resource=Resource.spend(to="api.example.com", amount="0.05"),
            now_us=NOW,
        )
        assert verdict.allowed


class TestClaims:
    def test_a_held_path_refuses_another_agent(
        self, contract: Contract, registry: ClaimRegistry
    ) -> None:
        resource = Resource.path("src/config.py")
        granted = registry.acquire(
            claim_id="c1",
            path=resource.identity,
            agent_id="agent_a",
            run_id="run1",
            now_us=NOW,
            duration_us=60_000_000,
        )
        assert granted.granted

        verdict = gate_for(contract, registry=registry).check(
            agent_id="agent_b", resource=resource, now_us=NOW
        )
        assert verdict.refused
        assert verdict.rule == "claim"
        assert verdict.holder == "agent_a"

    def test_the_holder_may_still_write(self, contract: Contract, registry: ClaimRegistry) -> None:
        resource = Resource.path("src/config.py")
        registry.acquire(
            claim_id="c1",
            path=resource.identity,
            agent_id="agent_a",
            run_id="run1",
            now_us=NOW,
            duration_us=60_000_000,
        )
        verdict = gate_for(contract, registry=registry).check(
            agent_id="agent_a", resource=resource, now_us=NOW
        )
        assert verdict.allowed

    def test_a_payment_can_be_leased_like_a_path(
        self, contract: Contract, registry: ClaimRegistry
    ) -> None:
        """The claim that the framework rests on, tested directly.

        The registry was written for file paths and never modified for this;
        it holds a lease on a payment destination because a resource identity
        is an opaque normalized string either way.
        """
        resource = Resource.spend(to="api.example.com", amount="0.05")
        granted = registry.acquire(
            claim_id="p1",
            path=resource.identity,
            agent_id="buyer",
            run_id="run1",
            now_us=NOW,
            duration_us=60_000_000,
        )
        assert granted.granted

        verdict = gate_for(contract, registry=registry).check(
            agent_id="other", resource=resource, now_us=NOW
        )
        assert verdict.refused
        assert verdict.rule == "claim"


class TestEnforcementIsolatesOneFactor:
    def test_an_unenforcing_gate_allows_but_records_the_counterfactual(
        self, contract: Contract
    ) -> None:
        """C2 and C3 run the same code path; only the verdict differs.

        That is what makes the C2 -> C3 contrast measure enforcement rather
        than a difference in how the two arms were implemented.
        """
        resource = Resource.path("src/schema.py")
        refused = gate_for(contract, enforcing=True).check(
            agent_id="agent_b", resource=resource, now_us=NOW
        )
        shadow = gate_for(contract, enforcing=False).check(
            agent_id="agent_b", resource=resource, now_us=NOW
        )

        assert refused.refused
        assert shadow.allowed
        assert shadow.detail["would_refuse"] is True
        # The reason survives, so an unenforced arm can still report what
        # enforcement would have cost it.
        assert shadow.rule == refused.rule

    def test_a_verdict_serializes_for_the_chain(self, contract: Contract) -> None:
        verdict = gate_for(contract).check(
            agent_id="agent_b", resource=Resource.path("src/schema.py"), now_us=NOW
        )
        payload = verdict.to_dict()
        assert payload["allowed"] is False
        assert payload["resource"]["identity"] == "path:src/schema.py"
        assert payload["rule"] == "ownership"


class TestCheckpointsInTheGate:
    def _checkpointed_contract(self) -> Contract:
        return Contract.from_dict(
            {
                "version": 1,
                "roles": [
                    {
                        "agent_id": "buyer",
                        "archetype": "spender",
                        "budget": {"usd_total": "100.00"},
                    }
                ],
                "policy": {
                    "arm": "C3",
                    "checkpoints": [
                        {"on": "spend", "when": {"usd": ">0.50"}, "require": "human"}
                    ],
                },
            }
        )

    def test_a_matched_checkpoint_with_no_handler_refuses_by_default(self) -> None:
        gate = gate_for(self._checkpointed_contract())
        verdict = gate.check(
            agent_id="buyer", resource=Resource.spend(to="api.example.com", amount="1.00"), now_us=NOW
        )
        assert verdict.refused
        assert verdict.rule == "checkpoint"

    def test_an_unmatched_checkpoint_does_not_refuse(self) -> None:
        gate = gate_for(self._checkpointed_contract())
        verdict = gate.check(
            agent_id="buyer", resource=Resource.spend(to="api.example.com", amount="0.10"), now_us=NOW
        )
        assert verdict.allowed

    def test_a_scripted_approval_allows_the_call(self) -> None:
        gate = gate_for(self._checkpointed_contract(), checkpoint_handler=ScriptedHandler([True]))
        verdict = gate.check(
            agent_id="buyer", resource=Resource.spend(to="api.example.com", amount="1.00"), now_us=NOW
        )
        assert verdict.allowed

    def test_a_prior_refusal_never_reaches_the_checkpoint(self) -> None:
        """A ceiling refusal already answers the question; the human is not

        asked about a call the contract already refuses on its own terms.
        """
        contract = Contract.from_dict(
            {
                "version": 1,
                "roles": [
                    {
                        "agent_id": "buyer",
                        "budget": {"usd_total": "100.00", "usd_per_call": "0.05"},
                    }
                ],
                "policy": {
                    "checkpoints": [{"on": "spend", "require": "human"}],
                },
            }
        )
        gate = gate_for(contract, checkpoint_handler=ScriptedHandler([True]))
        verdict = gate.check(
            agent_id="buyer", resource=Resource.spend(to="api.example.com", amount="1.00"), now_us=NOW
        )
        assert verdict.refused
        assert verdict.rule == "ceiling"

    def test_an_unenforced_gate_reports_the_checkpoint_as_a_shadow_refusal(self) -> None:
        gate = gate_for(self._checkpointed_contract(), enforcing=False)
        verdict = gate.check(
            agent_id="buyer", resource=Resource.spend(to="api.example.com", amount="1.00"), now_us=NOW
        )
        assert verdict.allowed
        assert verdict.detail["would_refuse"] is True
        assert verdict.rule == "checkpoint"

    def test_a_checkpoint_ignores_a_resource_kind_it_does_not_declare(
        self, contract: Contract
    ) -> None:
        gate = gate_for(contract, checkpoint_handler=ScriptedHandler([]))
        verdict = gate.check(agent_id="agent_b", resource=Resource.path("README.md"), now_us=NOW)
        assert verdict.allowed
