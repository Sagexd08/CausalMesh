"""Every resource kind the policy layer supports, decided through the SDK.

The gate could always refuse a spend, an endpoint or a budget, but the SDK
only ever handed it paths, so a tool that reached a network or spent money
ran with no policy decision at all. `Tool(resource_kind=..., amount_arg=...)`
declares what a call touches, and these tests pin, for each kind, that the
decision is made, that a refusal stops the handler, and that a value the gate
could not trust is refused rather than passed.

Also covered here, because they are the same property from the other side:

- the spellings of one path that used to walk around an ownership rule
  (`..`, `./`, case, a trailing dot, an absolute spelling);
- resource arguments that are not text, which the handler would receive as
  themselves while the gate checked `str(value)`;
- the two things the SDK deliberately does *not* decide (a tool with no
  declared resource, and a `mutating=False` tool), stated as tests so the
  boundary is executable rather than only written down.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.policy.contract import Contract
from causalmesh.policy.ledger import Ledger
from causalmesh.sdk.errors import InvalidResourceError, MissingResourceError

pytestmark = pytest.mark.unit

CONTRACT = """
version: 1
roles:
  - agent_id: alice
    archetype: writer
    owns: [allowed/]
  - agent_id: bob
    archetype: writer
    owns: [forbidden/]
  - agent_id: buyer
    archetype: spender
    allow: [api.example.com]
    budget:
      usd_total: "5.00"
      usd_per_call: "0.10"
  - agent_id: capped
    archetype: spender
    allow: [api.example.com]
    budget:
      usd_per_call: "0.10"
policy:
  arm: {arm}
  budgets:
    tokens: "1000"
"""


class Recorder:
    """Handlers that record every call, so a test can say what did not run."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def sync(self, name: str) -> Any:
        def handler(**kwargs: Any) -> str:
            self.calls.append((name, kwargs))
            return f"{name}:ok"

        return handler

    def asynchronous(self, name: str) -> Any:
        async def handler(**kwargs: Any) -> str:
            self.calls.append((name, kwargs))
            return f"{name}:ok"

        return handler


def _mesh(
    tmp_path: Path, *, arm: str = "C3", ledger: Ledger | None = None, agent: str = "buyer"
) -> tuple[CausalMesh, Recorder]:
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT.replace("{arm}", arm), encoding="utf-8")
    mesh = CausalMesh(
        agent_id=agent,
        contract=Contract.find(tmp_path),
        seed=b"resource-kinds-0000000000000000",
        ledger=ledger,
    )
    rec = Recorder()
    mesh.register_tool(
        Tool(name="write", handler=rec.sync("write"), resource_args=["path"], kind="filesystem")
    )
    mesh.register_tool(
        Tool(
            name="fetch",
            handler=rec.sync("fetch"),
            resource_args=["url"],
            resource_kind="endpoint",
        )
    )
    mesh.register_tool(
        Tool(
            name="pay",
            handler=rec.sync("pay"),
            resource_args=["to"],
            resource_kind="spend",
            amount_arg="usd",
        )
    )
    mesh.register_tool(
        Tool(
            name="apay",
            handler=rec.asynchronous("apay"),
            resource_args=["to"],
            resource_kind="spend",
            amount_arg="usd",
        )
    )
    mesh.register_tool(
        Tool(
            name="afetch",
            handler=rec.asynchronous("afetch"),
            resource_args=["url"],
            resource_kind="endpoint",
        )
    )
    mesh.register_tool(
        Tool(
            name="think",
            handler=rec.sync("think"),
            resource_args=["budget"],
            resource_kind="budget",
            amount_arg="used",
            unit="tokens",
        )
    )
    return mesh, rec


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[Ledger]:
    with Ledger(tmp_path / "ledger.db", run_id="sdk") as led:
        yield led


# ---------------------------------------------------------------------------
# PATH: one file, however it is spelled
# ---------------------------------------------------------------------------


class TestPathSpellings:
    """`bob` owns `forbidden/`. `alice` must be refused every spelling of it."""

    @pytest.mark.parametrize(
        "spelling",
        [
            "forbidden/secret.txt",
            "allowed/../forbidden/secret.txt",
            "./forbidden/secret.txt",
            "forbidden//secret.txt",
            "forbidden/./secret.txt",
            "forbidden\\secret.txt",
            "Forbidden/secret.txt",
            "FORBIDDEN/SECRET.TXT",
            "forbidden./secret.txt",
            "forbidden /secret.txt",
            "forbidden/x/../secret.txt",
            "forbidden/secret.txt/",
            "allowed/./../forbidden/./secret.txt",
        ],
    )
    def test_every_spelling_of_a_protected_file_is_refused(
        self, tmp_path: Path, spelling: str
    ) -> None:
        mesh, rec = _mesh(tmp_path, agent="alice")
        result = mesh.execute(tool="write", arguments={"path": spelling})
        assert result.denied, f"{spelling!r} walked around the ownership rule"
        assert result.rule == "ownership"
        assert rec.calls == []

    def test_an_absolute_spelling_inside_the_contract_directory_is_refused(
        self, tmp_path: Path
    ) -> None:
        mesh, rec = _mesh(tmp_path, agent="alice")
        absolute = (tmp_path.resolve() / "forbidden" / "secret.txt").as_posix()
        assert mesh.execute(tool="write", arguments={"path": absolute}).denied
        assert rec.calls == []

    def test_an_absolute_spelling_outside_the_contract_directory_is_not_this_contracts_to_decide(
        self, tmp_path: Path
    ) -> None:
        # The contract speaks for the directory that holds it. Anything else is
        # outside its domain, so it is not refused (a contract states
        # exceptions), and the handler is the one place that knows what an
        # outside path means.
        mesh, rec = _mesh(tmp_path, agent="alice")
        assert mesh.execute(tool="write", arguments={"path": "/elsewhere/forbidden/x"}).executed
        assert len(rec.calls) == 1

    @pytest.mark.parametrize(
        "spelling",
        ["allowed/x.txt", "allowed/../allowed/x.txt", "./allowed/x.txt", "ALLOWED/x.txt"],
    )
    def test_the_owner_is_still_allowed_under_any_spelling(
        self, tmp_path: Path, spelling: str
    ) -> None:
        mesh, rec = _mesh(tmp_path, agent="alice")
        assert mesh.execute(tool="write", arguments={"path": spelling}).executed
        assert len(rec.calls) == 1

    @pytest.mark.parametrize("neighbour", ["forbidden-other/x", "forbiddenx", "not-forbidden/x"])
    def test_a_neighbouring_name_is_not_swallowed_by_the_declaration(
        self, tmp_path: Path, neighbour: str
    ) -> None:
        # Folding case and stripping dots must not turn a prefix test into a
        # substring test.
        mesh, _ = _mesh(tmp_path, agent="alice")
        assert mesh.execute(tool="write", arguments={"path": neighbour}).executed

    def test_the_event_records_the_spelling_that_was_asked_for(self, tmp_path: Path) -> None:
        # The decision is made on the canonical file; the evidence says what
        # the agent actually asked for.
        mesh, _ = _mesh(tmp_path, agent="alice")
        mesh.execute(tool="write", arguments={"path": "allowed/../forbidden/x"})
        event = mesh.audit_events()[-1]["event"]
        assert event["event_type"] == "FAILURE"
        assert event["paths"] == ["allowed/../forbidden/x"]

    def test_a_path_the_gate_cannot_form_is_refused_as_data_not_raised(
        self, tmp_path: Path
    ) -> None:
        # `paths=` bypasses the resolver, so it used to reach Resource.path("")
        # and raise a bare ResourceError from inside the gate.
        mesh, rec = _mesh(tmp_path, agent="alice")
        result = mesh.execute(tool="write", arguments={"path": "allowed/x"}, paths=("",))
        assert result.denied
        assert result.rule == "malformed"
        assert rec.calls == []


class TestMalformedPathArguments:
    @pytest.mark.parametrize(
        "value", [None, 5, 1.5, True, b"allowed/x", ["allowed/a", "forbidden/b"], ("a",), {"p": 1}]
    )
    def test_a_value_that_is_not_text_never_reaches_the_handler(
        self, tmp_path: Path, value: object
    ) -> None:
        mesh, rec = _mesh(tmp_path, agent="alice")
        with pytest.raises(InvalidResourceError):
            mesh.execute(tool="write", arguments={"path": value})
        assert rec.calls == []
        assert mesh.audit_events() == []

    def test_a_pathlib_path_is_accepted_and_decided_as_its_text(self, tmp_path: Path) -> None:
        mesh, rec = _mesh(tmp_path, agent="alice")
        assert mesh.execute(tool="write", arguments={"path": Path("allowed") / "x"}).executed
        assert mesh.execute(tool="write", arguments={"path": Path("forbidden") / "x"}).denied
        assert len(rec.calls) == 1

    def test_a_missing_declared_argument_is_refused(self, tmp_path: Path) -> None:
        mesh, rec = _mesh(tmp_path, agent="alice")
        with pytest.raises(MissingResourceError):
            mesh.execute(tool="write", arguments={})
        assert rec.calls == []

    def test_the_two_errors_are_one_family(self) -> None:
        # The server (422) and the OpenAI adapter (a tool message) catch the
        # parent, so the child needs no new handling anywhere.
        assert issubclass(InvalidResourceError, MissingResourceError)


# ---------------------------------------------------------------------------
# ENDPOINT
# ---------------------------------------------------------------------------


class TestEndpoint:
    @pytest.mark.parametrize(
        "url",
        [
            "https://api.example.com/v1/x",
            "api.example.com",
            "api.example.com:8443",
            "https://sub.api.example.com/",
            "HTTPS://API.EXAMPLE.COM/x",
        ],
    )
    def test_a_listed_host_is_allowed_however_it_is_written(self, tmp_path: Path, url: str) -> None:
        mesh, rec = _mesh(tmp_path)
        assert mesh.execute(tool="fetch", arguments={"url": url}).executed
        assert len(rec.calls) == 1

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example/x",
            "evil.example",
            "https://notapi.example.com/",
            # What follows `#`, `?` or `@` is not the host the request connects to.
            "https://evil.example#.api.example.com",
            "https://evil.example?.api.example.com",
            "https://api.example.com@evil.example/",
            "https://api.example.com:pw@evil.example/",
            "//evil.example/x",
        ],
    )
    def test_an_unlisted_host_is_refused_and_the_handler_does_not_run(
        self, tmp_path: Path, url: str
    ) -> None:
        mesh, rec = _mesh(tmp_path)
        result = mesh.execute(tool="fetch", arguments={"url": url})
        assert result.denied, f"{url!r} reached an unlisted host"
        assert result.rule == "allowlist"
        assert rec.calls == []

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.example.com\\@evil.example/",  # parsers and clients disagree
            "https://api.example.com evil.example/",
            "https://api.example.com/\n",
            "https://",
            "http://:80/",
            "",
            "   ",
            None,
            ["api.example.com"],
            b"api.example.com",
        ],
    )
    def test_a_value_the_gate_cannot_read_as_one_host_is_refused(
        self, tmp_path: Path, url: object
    ) -> None:
        mesh, rec = _mesh(tmp_path)
        with pytest.raises(InvalidResourceError):
            mesh.execute(tool="fetch", arguments={"url": url})
        assert rec.calls == []

    def test_an_agent_with_no_allowlist_is_unrestricted(self, tmp_path: Path) -> None:
        # Absent means unrestricted, everywhere in the contract. The agent has
        # a key (a role) but declares no `allow`.
        mesh, _ = _mesh(tmp_path, agent="alice")
        assert mesh.execute(tool="fetch", arguments={"url": "https://anywhere.example"}).executed

    def test_the_decision_is_recorded_with_the_resource_it_was_about(self, tmp_path: Path) -> None:
        mesh, _ = _mesh(tmp_path)
        mesh.execute(tool="fetch", arguments={"url": "https://evil.example#.api.example.com"})
        payload = mesh.audit_events()[-1]["event"]["payload"]
        assert payload["rule"] == "allowlist"
        assert payload["resources"][0]["identity"] == "endpoint:evil.example"

    async def test_an_async_endpoint_call_is_refused_and_never_awaited(
        self, tmp_path: Path
    ) -> None:
        mesh, rec = _mesh(tmp_path)
        result = await mesh.execute_async(tool="afetch", arguments={"url": "https://evil.example"})
        assert result.denied
        assert rec.calls == []
        allowed = await mesh.execute_async(
            tool="afetch", arguments={"url": "https://api.example.com"}
        )
        assert allowed.executed
        assert [name for name, _ in rec.calls] == ["afetch"]

    def test_an_unenforced_arm_runs_it_and_says_what_c3_would_have_done(
        self, tmp_path: Path
    ) -> None:
        mesh, rec = _mesh(tmp_path, arm="C1")
        result = mesh.execute(tool="fetch", arguments={"url": "https://evil.example"})
        assert result.executed
        assert result.would_refuse
        assert result.shadow_rule == "allowlist"
        assert len(rec.calls) == 1


# ---------------------------------------------------------------------------
# SPEND
# ---------------------------------------------------------------------------


class TestSpend:
    def test_a_spend_inside_every_limit_runs_and_is_recorded(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        mesh, rec = _mesh(tmp_path, ledger=ledger)
        result = mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "0.05"})
        assert result.executed and result.recorded
        assert ledger.total(agent_id="buyer", resource=_spend("0")) == Decimal("0.05")
        assert len(rec.calls) == 1

    def test_the_evidence_carries_the_amount_that_was_allowed(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        # An allowed payment used to leave a bare WRITE event with no amount.
        mesh, _ = _mesh(tmp_path, ledger=ledger)
        mesh.execute(tool="pay", arguments={"to": "API.example.com", "usd": "0.05"})
        (resource,) = mesh.audit_events()[-1]["event"]["payload"]["resources"]
        assert resource["kind"] == "spend"
        assert resource["amount"] == "0.05"
        assert resource["name"] == "api.example.com"
        assert resource["unit"] == "USD"

    @pytest.mark.parametrize("amount", ["0.11", "1", 1, Decimal("0.100001"), "1e3"])
    def test_a_call_over_the_ceiling_is_refused(
        self, tmp_path: Path, ledger: Ledger, amount: object
    ) -> None:
        mesh, rec = _mesh(tmp_path, ledger=ledger)
        result = mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": amount})
        assert result.denied
        assert result.rule == "ceiling"
        assert rec.calls == []
        assert ledger.total(agent_id="buyer", resource=_spend("0")) == 0

    @pytest.mark.parametrize("amount", ["0.10", 0, "0", Decimal("0.1"), "0.0999999"])
    def test_a_call_at_or_under_the_ceiling_is_allowed(
        self, tmp_path: Path, ledger: Ledger, amount: object
    ) -> None:
        mesh, _ = _mesh(tmp_path, ledger=ledger)
        assert mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": amount}).executed

    def test_an_unlisted_destination_is_refused_even_for_a_tiny_amount(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        mesh, rec = _mesh(tmp_path, ledger=ledger)
        for to in ("evil.example", "https://evil.example/pay", "notapi.example.com"):
            result = mesh.execute(tool="pay", arguments={"to": to, "usd": "0.01"})
            assert result.denied and result.rule == "allowlist", to
        assert rec.calls == []

    def test_a_url_destination_is_decided_on_its_host(self, tmp_path: Path, ledger: Ledger) -> None:
        mesh, _ = _mesh(tmp_path, ledger=ledger)
        ok = mesh.execute(
            tool="pay", arguments={"to": "https://api.example.com/pay", "usd": "0.01"}
        )
        assert ok.executed
        bad = mesh.execute(
            tool="pay", arguments={"to": "https://evil.example#.api.example.com", "usd": "0.01"}
        )
        assert bad.denied

    def test_the_total_holds_exactly_at_the_limit(self, tmp_path: Path, ledger: Ledger) -> None:
        """Fifty calls of 0.10 make 5.00 exactly: the fiftieth is allowed, the next is not.

        Float arithmetic would reach 5.000000000000001 and refuse the fiftieth.
        """
        mesh, rec = _mesh(tmp_path, ledger=ledger)
        for i in range(50):
            result = mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "0.10"})
            assert result.executed, f"call {i + 1} was refused: {result.reason}"
        over = mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "0.01"})
        assert over.denied and over.rule == "budget"
        assert len(rec.calls) == 50
        assert ledger.total(agent_id="buyer", resource=_spend("0")) == Decimal("5.00")

    def test_a_refused_spend_is_not_counted_against_the_total(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        mesh, _ = _mesh(tmp_path, ledger=ledger)
        mesh.execute(tool="pay", arguments={"to": "evil.example", "usd": "0.05"})
        mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "9"})
        assert ledger.entries() == []

    @pytest.mark.failure
    def test_a_handler_that_raises_is_not_recorded_as_spent(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        mesh, _ = _mesh(tmp_path, ledger=ledger)

        def boom(**_: Any) -> None:
            raise RuntimeError("card declined")

        mesh.register_tool(
            Tool(
                name="boom",
                handler=boom,
                resource_args=["to"],
                resource_kind="spend",
                amount_arg="usd",
            )
        )
        result = mesh.execute(tool="boom", arguments={"to": "api.example.com", "usd": "0.05"})
        assert result.failed
        assert ledger.entries() == []

    def test_a_total_with_no_ledger_is_refused_because_nothing_could_enforce_it(
        self, tmp_path: Path
    ) -> None:
        mesh, rec = _mesh(tmp_path)  # `buyer` declares usd_total, and no ledger is attached
        result = mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "0.05"})
        assert result.denied
        assert result.rule == "budget"
        assert "no ledger" in result.reason
        assert rec.calls == []

    def test_no_ledger_is_fine_when_no_total_is_declared(self, tmp_path: Path) -> None:
        # `capped` declares only a per-call ceiling, which needs no memory.
        mesh, _ = _mesh(tmp_path, agent="capped")
        ok = mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "0.05"})
        assert ok.executed
        over = mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "0.50"})
        assert over.denied and over.rule == "ceiling"

    def test_an_unenforced_arm_runs_the_spend_and_still_records_it(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        mesh, rec = _mesh(tmp_path, arm="C2", ledger=ledger)
        result = mesh.execute(tool="pay", arguments={"to": "evil.example", "usd": "9"})
        assert result.executed and result.would_refuse
        assert len(rec.calls) == 1
        assert ledger.total(agent_id="buyer", resource=_spend("0")) == Decimal("9")

    async def test_an_async_spend_is_refused_and_never_awaited(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        mesh, rec = _mesh(tmp_path, ledger=ledger)
        result = await mesh.execute_async(
            tool="apay", arguments={"to": "api.example.com", "usd": "5"}
        )
        assert result.denied and result.rule == "ceiling"
        assert rec.calls == []
        ok = await mesh.execute_async(
            tool="apay", arguments={"to": "api.example.com", "usd": "0.05"}
        )
        assert ok.executed
        assert ledger.total(agent_id="buyer", resource=_spend("0")) == Decimal("0.05")

    @pytest.mark.parametrize(
        "amount",
        [
            1.5,  # a float is already imprecise; refused, not converted
            True,  # a bool is an int to Python and would read as 1
            None,
            [1],
            "abc",
            "",
            "-0.05",
            -1,
            "NaN",
            "Infinity",
            "-Infinity",
            Decimal("NaN"),
        ],
    )
    def test_an_amount_that_is_not_a_finite_non_negative_number_is_refused(
        self, tmp_path: Path, ledger: Ledger, amount: object
    ) -> None:
        mesh, rec = _mesh(tmp_path, ledger=ledger)
        with pytest.raises(InvalidResourceError):
            mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": amount})
        assert rec.calls == []
        assert ledger.entries() == []

    def test_a_missing_amount_is_refused(self, tmp_path: Path, ledger: Ledger) -> None:
        mesh, rec = _mesh(tmp_path, ledger=ledger)
        with pytest.raises(MissingResourceError, match="usd"):
            mesh.execute(tool="pay", arguments={"to": "api.example.com"})
        assert rec.calls == []

    def test_a_missing_destination_is_refused(self, tmp_path: Path, ledger: Ledger) -> None:
        mesh, rec = _mesh(tmp_path, ledger=ledger)
        with pytest.raises(MissingResourceError, match="to"):
            mesh.execute(tool="pay", arguments={"usd": "0.01"})
        assert rec.calls == []

    @pytest.mark.failure
    def test_a_ledger_that_cannot_be_written_is_reported_not_raised(
        self, tmp_path: Path, ledger: Ledger, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mesh, _ = _mesh(tmp_path, ledger=ledger)

        def broken(**_: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(ledger, "record", broken)
        result = mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "0.05"})
        assert result.executed, "the outcome must stand"
        assert result.audit_error is not None and "disk full" in result.audit_error


def _spend(amount: str) -> Any:
    from causalmesh.policy.resource import Resource

    return Resource.spend(to="api.example.com", amount=amount)


# ---------------------------------------------------------------------------
# BUDGET
# ---------------------------------------------------------------------------


class TestBudget:
    def test_consumption_counts_toward_the_declared_total(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        mesh, rec = _mesh(tmp_path, ledger=ledger, agent="alice")
        assert mesh.execute(tool="think", arguments={"budget": "tokens", "used": 600}).executed
        second = mesh.execute(tool="think", arguments={"budget": "tokens", "used": 600})
        assert second.denied and second.rule == "budget"
        assert len(rec.calls) == 1

    def test_the_total_holds_exactly_at_the_limit(self, tmp_path: Path, ledger: Ledger) -> None:
        mesh, _ = _mesh(tmp_path, ledger=ledger, agent="alice")
        assert mesh.execute(tool="think", arguments={"budget": "tokens", "used": 1000}).executed
        assert mesh.execute(tool="think", arguments={"budget": "tokens", "used": 1}).denied

    def test_a_declared_budget_with_no_ledger_is_refused(self, tmp_path: Path) -> None:
        mesh, rec = _mesh(tmp_path, agent="alice")
        result = mesh.execute(tool="think", arguments={"budget": "tokens", "used": 1})
        assert result.denied and "no ledger" in result.reason
        assert rec.calls == []

    def test_a_budget_nobody_declared_is_unlimited_and_says_so(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        # Absent means unrestricted. A misspelled name ("token") is therefore
        # unlimited, which is why the name is the tool's declaration, not the
        # model's argument: `resource_args` takes the value from the call, so a
        # tool that must be held to one budget should hard-code it in a wrapper.
        mesh, _ = _mesh(tmp_path, ledger=ledger, agent="alice")
        result = mesh.execute(tool="think", arguments={"budget": "token", "used": 10**9})
        assert result.executed

    def test_the_consumption_is_recorded_per_agent(self, tmp_path: Path, ledger: Ledger) -> None:
        mesh, _ = _mesh(tmp_path, ledger=ledger, agent="alice")
        mesh.execute(tool="think", arguments={"budget": "tokens", "used": 400})
        mesh.execute(tool="think", arguments={"budget": "tokens", "used": 500}, agent_id="bob")
        from causalmesh.policy.resource import Resource

        tokens = Resource.budget(name="tokens", amount="0")
        assert ledger.total(agent_id="alice", resource=tokens) == Decimal("400")
        assert ledger.total(agent_id="bob", resource=tokens) == Decimal("500")

    def test_a_malformed_amount_is_refused(self, tmp_path: Path, ledger: Ledger) -> None:
        mesh, rec = _mesh(tmp_path, ledger=ledger, agent="alice")
        for bad in (1.5, "many", -1, None, True):
            with pytest.raises(InvalidResourceError):
                mesh.execute(tool="think", arguments={"budget": "tokens", "used": bad})
        assert rec.calls == []


# ---------------------------------------------------------------------------
# What the SDK deliberately does not decide
# ---------------------------------------------------------------------------


class TestTheBoundaryIsExecutable:
    def test_a_mutating_tool_that_declares_no_resource_is_checked_against_nothing(
        self, tmp_path: Path
    ) -> None:
        """Documented, not accidental: the contract states exceptions.

        A call that names nothing gives the gate nothing to refuse, so it
        runs. The tool is still recorded, and the gate is still consulted
        (it just has no resource to consult about).
        """
        mesh, rec = _mesh(tmp_path, agent="buyer")
        mesh.register_tool(Tool(name="ping", handler=rec.sync("ping")))
        result = mesh.execute(tool="ping", arguments={"anything": "goes"})
        assert result.executed and not result.would_refuse
        assert result.recorded
        assert mesh._gate.verdicts == [], "no resource means no verdict, and none is invented"

    def test_a_read_only_tool_skips_the_gate_for_every_kind(self, tmp_path: Path) -> None:
        """`mutating=False` is a statement someone made, and it skips the gate.

        A read-only tool that reaches a network is therefore not held to an
        endpoint allowlist. That is the documented boundary (reads are not
        gated), not an oversight; an operator who wants egress checked declares
        the tool mutating.
        """
        mesh, rec = _mesh(tmp_path, agent="buyer")
        mesh.register_tool(
            Tool(
                name="peek",
                handler=rec.sync("peek"),
                resource_args=["url"],
                resource_kind="endpoint",
                mutating=False,
            )
        )
        assert mesh.execute(tool="peek", arguments={"url": "https://evil.example"}).executed
        assert mesh._gate.verdicts == []

    def test_the_default_tool_is_still_a_path_tool_and_still_gated(self, tmp_path: Path) -> None:
        tool = Tool(name="t", handler=lambda: None)
        assert tool.resource_kind == "path"
        assert tool.mutating is True


class TestToolDeclarationIsValidatedAtRegistration:
    def _tool(self, **kwargs: Any) -> Tool:
        return Tool(name="t", handler=lambda **_: None, **kwargs)

    def test_an_unknown_kind_is_refused_and_the_known_ones_are_named(self) -> None:
        with pytest.raises(ValueError, match="known kinds: budget, endpoint, path, spend"):
            self._tool(resource_kind="paymnt", resource_args=["x"])

    @pytest.mark.parametrize("kind", ["spend", "budget"])
    def test_a_consumable_kind_needs_an_amount(self, kind: str) -> None:
        with pytest.raises(ValueError, match="needs amount_arg"):
            self._tool(resource_kind=kind, resource_args=["x"])

    @pytest.mark.parametrize("kind", ["path", "endpoint"])
    def test_an_amount_on_a_kind_with_no_amount_is_refused(self, kind: str) -> None:
        with pytest.raises(ValueError, match="only applies to spend and budget"):
            self._tool(resource_kind=kind, resource_args=["x"], amount_arg="n")

    @pytest.mark.parametrize("kind", ["endpoint", "spend", "budget"])
    def test_a_non_path_kind_with_no_resource_args_would_check_nothing(self, kind: str) -> None:
        extra = {"amount_arg": "n"} if kind in ("spend", "budget") else {}
        with pytest.raises(ValueError, match="needs resource_args"):
            self._tool(resource_kind=kind, **extra)

    @pytest.mark.parametrize("kind", ["spend", "budget"])
    def test_a_spending_tool_cannot_declare_itself_read_only(self, kind: str) -> None:
        with pytest.raises(ValueError, match="cannot be mutating=False"):
            self._tool(resource_kind=kind, resource_args=["x"], amount_arg="n", mutating=False)


class TestTheImportOrderThatOnlyAFreshInterpreterSees:
    def test_the_resolver_imports_first_without_a_cycle(self) -> None:
        # `causalmesh.sdk` imports the gateway, which imports the resolver, so a
        # module-level import of the SDK's errors there is circular. pytest has
        # usually imported `causalmesh` already, which hides it; a fresh
        # interpreter does not.
        for module in (
            "causalmesh.gateway.resolver",
            "causalmesh.gateway.tool",
            "causalmesh.sdk.errors",
            "causalmesh.hooks.policy_gate",
        ):
            done = subprocess.run(
                [sys.executable, "-c", f"import {module}"], capture_output=True, text=True
            )
            assert done.returncode == 0, f"{module}: {done.stderr[-300:]}"
