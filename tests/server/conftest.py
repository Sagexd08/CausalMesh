import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from causalmesh import CausalMesh, Tool
from causalmesh.policy.contract import Contract
from causalmesh.server import create_app

MINIMAL_CONTRACT_YAML = """
version: 1
roles:
  - agent_id: test-agent
    archetype: writer
    owns:
      - allowed/
  - agent_id: admin-agent
    archetype: admin
    owns:
      - forbidden/
policy:
  arm: C3
  contested:
    forbidden/: exclusive
evidence:
  sign: true
  verify_on_exit: false
"""


@pytest.fixture
def contract(tmp_path):
    p = tmp_path / "causalmesh.yaml"
    p.write_text(MINIMAL_CONTRACT_YAML)
    return Contract.find(tmp_path)


@pytest.fixture
def mesh(contract):
    m = CausalMesh(
        agent_id="test-agent",
        contract=contract,
        seed=b"test-seed-00000000000000000000000",
    )
    called = []

    def write_handler(path: str, content: str = "") -> str:
        called.append(path)
        return f"written:{path}"

    async def async_write_handler(path: str, content: str = "") -> str:
        called.append(path)
        return f"async-written:{path}"

    m.register_tool(
        Tool(
            name="write_file",
            handler=write_handler,
            kind="filesystem",
            mutating=True,
            description="Write a file",
            resource_args=["path"],
        )
    )
    m.register_tool(
        Tool(
            name="async_write",
            handler=async_write_handler,
            kind="filesystem",
            mutating=True,
            description="Async write",
            resource_args=["path"],
        )
    )
    m.register_tool(
        Tool(
            name="read_file",
            handler=lambda path: f"content of {path}",
            kind="filesystem",
            mutating=False,
            description="Read a file",
            resource_args=["path"],
        )
    )
    m._called = called
    return m


@pytest.fixture
def app(mesh):
    return create_app(mesh=mesh, auth_disabled=True)


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def authed_app(mesh):
    return create_app(mesh=mesh, api_tokens={"good-token"})


@pytest.fixture
def authed_client(authed_app):
    return TestClient(authed_app, raise_server_exceptions=False)
