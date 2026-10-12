"""The local CLI demo (`examples/cli_demo/`), kept honest.

A demo that is only ever run by hand stops working without anyone noticing.
These tests run the real journey: a real gateway process, real HTTP, the real
`causalmesh` command line, and a real verification of the evidence it records.

The invariants that make the demo worth showing:

- a denied call never reaches the tool's handler;
- every call, allowed or denied, is recorded;
- the evidence verifies against the operator's key ring, and a forged record
  does not;
- a key ring that is not the operator's rejects even an untouched log, which
  is what verifying against the records' own embedded keys could not do.
"""

from __future__ import annotations

import copy
import importlib
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from causalmesh.cli._output import Exit
from causalmesh.cli.main import app as cli_app
from causalmesh.crypto import KeyPair, PublicKeyRing
from causalmesh.verifier import verify_chain

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "examples" / "cli_demo"
TOKEN = "cm-demo-token-0001-abcdef"
_MODULES = ("gateway", "client", "verify_evidence", "run_demo")


@pytest.fixture()
def demo(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    """The demo's modules, imported fresh and removed afterwards, so their
    module-level state (the handler's call list) cannot leak between tests."""
    monkeypatch.syspath_prepend(str(DEMO))
    for name in _MODULES:
        sys.modules.pop(name, None)
    ns = SimpleNamespace(gateway=importlib.import_module("gateway"))
    ns.gateway.HANDLER_CALLS.clear()
    yield ns
    for name in _MODULES:
        sys.modules.pop(name, None)


def client_for(demo: SimpleNamespace):
    from fastapi.testclient import TestClient

    app, mesh = demo.gateway.build_app(TOKEN)
    return TestClient(app), mesh


def write(client, path: str, *, agent: str = "coding-agent", token: str | None = TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        "/v1/tools/write_file/execute",
        json={"agent_id": agent, "arguments": {"path": path, "content": "x"}},
        headers=headers,
    )


def evidence(client, token: str | None = TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/v1/evidence", headers=headers)


def operator_ring(demo: SimpleNamespace, seed: bytes | None = None) -> PublicKeyRing:
    agents = demo.gateway.build_mesh().agents
    seed = seed if seed is not None else demo.gateway.DEMO_SEED
    return PublicKeyRing.from_keypairs({a: KeyPair.derive(seed, a) for a in agents})


class TestTheContract:
    def test_the_demo_contract_validates_and_answers_policy_checks(self) -> None:
        runner = CliRunner()
        valid = runner.invoke(cli_app, ["policy", "validate", str(DEMO / "causalmesh.yaml")])
        assert valid.exit_code == Exit.OK, valid.output

        allow = runner.invoke(
            cli_app,
            ["policy", "check", "--root", str(DEMO), "--agent", "coding-agent",
             "--kind", "path", "--name", "src/app.py"],
        )  # fmt: skip
        assert allow.exit_code == Exit.OK, allow.output

        refuse = runner.invoke(
            cli_app,
            ["policy", "check", "--root", str(DEMO), "--agent", "coding-agent",
             "--kind", "path", "--name", "production/schema.sql"],
        )  # fmt: skip
        assert refuse.exit_code == Exit.FAILED, refuse.output


class TestTheGateway:
    def test_a_denied_call_never_reaches_the_handler(self, demo: SimpleNamespace) -> None:
        client, _ = client_for(demo)

        allowed = write(client, "src/app.py")
        denied = write(client, "production/schema.sql")

        assert allowed.status_code == 200 and allowed.json()["executed"] is True
        assert denied.status_code == 403
        assert denied.json()["detail"]["rule"] == "ownership"
        assert demo.gateway.HANDLER_CALLS == ["src/app.py"]

    def test_every_call_is_recorded_allowed_or_denied(self, demo: SimpleNamespace) -> None:
        client, _ = client_for(demo)
        write(client, "src/app.py")
        write(client, "production/schema.sql")

        records = evidence(client).json()

        outcomes = [r["event"]["payload"]["outcome"] for r in records]
        assert outcomes == ["executed", "denied"]

    def test_the_tool_is_listed_and_the_token_is_required(self, demo: SimpleNamespace) -> None:
        client, _ = client_for(demo)
        listed = client.get("/v1/tools", headers={"Authorization": f"Bearer {TOKEN}"})
        assert [t["name"] for t in listed.json()["tools"]] == ["write_file"]
        assert write(client, "src/app.py", token=None).status_code == 401
        assert write(client, "src/app.py", token="wrong-token-value-000000").status_code == 401
        assert demo.gateway.HANDLER_CALLS == []

    def test_a_bound_token_cannot_speak_for_another_agent(self, demo: SimpleNamespace) -> None:
        client, _ = client_for(demo)
        response = write(client, "production/schema.sql", agent="dba-agent")
        assert response.status_code == 403
        assert demo.gateway.HANDLER_CALLS == []

    def test_malformed_input_is_refused_before_the_handler(self, demo: SimpleNamespace) -> None:
        client, _ = client_for(demo)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        no_path = client.post(
            "/v1/tools/write_file/execute",
            json={"agent_id": "coding-agent", "arguments": {"content": "x"}},
            headers=headers,
        )
        not_json = client.post(
            "/v1/tools/write_file/execute", content=b"{not json", headers=headers
        )
        unknown = client.post(
            "/v1/tools/nope/execute",
            json={"agent_id": "coding-agent", "arguments": {}},
            headers=headers,
        )
        assert (no_path.status_code, not_json.status_code, unknown.status_code) == (422, 422, 404)
        assert demo.gateway.HANDLER_CALLS == []

    def test_the_evidence_route_needs_the_token(self, demo: SimpleNamespace) -> None:
        client, _ = client_for(demo)
        assert evidence(client, token=None).status_code == 401
        assert evidence(client, token="wrong-token-value-000000").status_code == 401
        assert evidence(client).status_code == 200

    def test_the_gateway_refuses_to_start_with_a_weak_token(
        self, demo: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODING_AGENT_TOKEN", "short")
        assert demo.gateway.main([]) == 2
        monkeypatch.delenv("CODING_AGENT_TOKEN")
        assert demo.gateway.main([]) == 2


class TestTheEvidence:
    def _records(self, demo: SimpleNamespace) -> list[dict]:
        client, _ = client_for(demo)
        write(client, "src/app.py")
        write(client, "production/schema.sql")
        return evidence(client).json()  # type: ignore[no-any-return]

    def test_it_verifies_against_the_operators_key_ring(self, demo: SimpleNamespace) -> None:
        result = verify_chain(self._records(demo), operator_ring(demo))
        assert result.valid and result.events == 2

    def test_a_record_rewritten_after_the_fact_fails_verification(
        self, demo: SimpleNamespace
    ) -> None:
        records = self._records(demo)
        forged = copy.deepcopy(records)
        forged[1]["event"]["payload"]["outcome"] = "executed"  # "the denial actually ran"
        assert verify_chain(records, operator_ring(demo)).valid
        assert not verify_chain(forged, operator_ring(demo)).valid

    def test_a_key_ring_that_is_not_the_operators_rejects_an_untouched_log(
        self, demo: SimpleNamespace
    ) -> None:
        wrong = operator_ring(demo, seed=b"not the operator's seed, 32 bytes!")
        assert not verify_chain(self._records(demo), wrong).valid


class TestTheJourney:
    def test_the_whole_journey_runs_unattended(self) -> None:
        # pytest's `pythonpath = src` is not inherited by a subprocess, so without this the
        # demo imports whatever `causalmesh` the editable install points at.
        paths = [str(REPO / "src"), *filter(None, [os.environ.get("PYTHONPATH")])]
        done = subprocess.run(  # noqa: S603
            [sys.executable, str(DEMO / "run_demo.py")],
            cwd=DEMO,
            env={**os.environ, "PYTHONPATH": os.pathsep.join(paths)},
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert "[FAIL]" not in done.stdout
        assert "checks passed" in done.stdout
