"""`causalmesh serve --tools`: operator tools, end to end over real HTTP.

A real `causalmesh serve` subprocess loads a tool file the operator named on
the command line, and a real HTTP client calls it. The point is the invariant
around the new feature: a tool that got in through `--tools` is still called
through the gateway, so the gate decides (allowed, denied), authentication
comes first (401, 403), and the errors are the server's (404, 422).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from serve_process import ServeProcess, run_to_exit

pytestmark = [pytest.mark.integration]

CONTRACT = """\
version: 1
roles:
  - agent_id: coder
    owns:
      - allowed/
  - agent_id: admin
    owns:
      - forbidden/
policy:
  arm: C3
evidence:
  sign: false
"""

# The operator's tool file. Handlers record their calls in a file next to it,
# so a test can prove a denied call never reached one.
TOOLS = """\
import os
from pathlib import Path

from causalmesh import Tool

LOG = Path(__file__).with_name("calls.log")


def write_file(path, content=""):
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(path + "\\n")
    return "wrote " + path


def boom(path):
    raise RuntimeError("could not use " + os.environ["CAUSALMESH_API_TOKEN"])


def register(mesh):
    mesh.register_tool(
        Tool(name="write_file", handler=write_file, kind="filesystem", mutating=True,
             description="Write a file", resource_args=["path"])
    )
    mesh.register_tool(
        Tool(name="boom", handler=boom, kind="filesystem", mutating=True,
             description="Always fails", resource_args=["path"])
    )
"""

TOKEN = "tools-test-token-0123456789abcdef"
CODER = "coder-token-0123456789abcdefgh"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT, encoding="utf-8")
    (tmp_path / "my_tools.py").write_text(TOOLS, encoding="utf-8")
    return tmp_path


def calls(root: Path) -> list[str]:
    log = root / "calls.log"
    return log.read_text(encoding="utf-8").split() if log.exists() else []


class TestOperatorToolsOverHttp:
    def test_the_whole_status_surface(self, root: Path) -> None:
        spec = f"{root / 'my_tools.py'}:register"
        with ServeProcess(
            root,
            "--tools",
            spec,
            "--agent-token",
            f"coder={CODER}",
            env={"CAUSALMESH_API_TOKEN": TOKEN},
        ) as server:

            def execute(tool: str, body: dict, token: str | None = TOKEN):
                return server.request("POST", f"/v1/tools/{tool}/execute", body=body, token=token)

            # The tools are listed, and only to a caller who authenticated.
            status, _, listed = server.request("GET", "/v1/tools", token=TOKEN)
            assert status == 200
            assert {t["name"] for t in listed["tools"]} == {"write_file", "boom"}
            assert server.request("GET", "/v1/tools")[0] == 401

            # Allowed: the gate said yes, the handler ran, the value came back.
            status, _, body = execute(
                "write_file", {"agent_id": "coder", "arguments": {"path": "allowed/a.txt"}}
            )
            assert status == 200, body
            assert body["allowed"] and body["executed"] and body["recorded"]
            assert body["value"] == "wrote allowed/a.txt"
            assert calls(root) == ["allowed/a.txt"]

            # Denied: another agent's path. 403, the rule is named, no handler ran.
            status, _, body = execute(
                "write_file", {"agent_id": "coder", "arguments": {"path": "forbidden/b.txt"}}
            )
            assert status == 403
            assert body["detail"]["rule"] == "ownership"
            assert calls(root) == ["allowed/a.txt"], "a denied call reached the handler"

            # 401: no credential, and a wrong one.
            assert (
                execute("write_file", {"agent_id": "coder", "arguments": {}}, token=None)[0] == 401
            )
            assert (
                execute("write_file", {"agent_id": "coder", "arguments": {}}, token="nope")[0]
                == 401
            )

            # 403: a token bound to `coder` cannot act as `admin`.
            status, _, body = execute(
                "write_file",
                {"agent_id": "admin", "arguments": {"path": "forbidden/c.txt"}},
                token=CODER,
            )
            assert status == 403
            assert "bound to a different agent" in body["detail"]
            assert "forbidden/c.txt" not in calls(root)

            # 404: no such tool.
            assert execute("no_such_tool", {"agent_id": "coder", "arguments": {}})[0] == 404

            # 422: a missing required argument, and a malformed body.
            assert execute("write_file", {"agent_id": "coder", "arguments": {}})[0] == 422
            assert execute("write_file", {"arguments": {}})[0] == 422

            # A handler that raises: the caller learns it failed, not why; the
            # operator's log has the reason but never the configured token.
            status, _, body = execute(
                "boom", {"agent_id": "coder", "arguments": {"path": "allowed/d.txt"}}
            )
            assert status == 200
            assert body["failed"] is True
            assert TOKEN not in str(body)
            assert "could not use" not in str(body)
        output = server.stop()
        assert "tools loaded by --tools" in output
        assert "could not use" in output, "the handler's failure should be in the operator's log"
        assert TOKEN not in output, "a configured token reached the log"
        assert CODER not in output
        assert "[redacted]" in output

    def test_the_module_form_needs_the_module_on_pythonpath(self, root: Path) -> None:
        with ServeProcess(
            root,
            "--tools",
            "my_tools:register",
            env={"CAUSALMESH_API_TOKEN": TOKEN, "PYTHONPATH": str(root)},
        ) as server:
            status, _, listed = server.request("GET", "/v1/tools", token=TOKEN)
            assert status == 200
            assert {t["name"] for t in listed["tools"]} == {"write_file", "boom"}

    def test_a_module_in_the_current_directory_is_not_found_without_pythonpath(
        self, root: Path
    ) -> None:
        code, output = run_to_exit(
            root, "--tools", "my_tools:register", env={"CAUSALMESH_API_TOKEN": TOKEN}
        )
        assert code == 2
        assert "PYTHONPATH" in output


class TestToolsAreNeverDerivedFromTheContractOrARequest:
    def test_a_tools_section_names_tools_and_imports_nothing(self, root: Path) -> None:
        marker = root / "imported.marker"
        (root / "evil_mod.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n"
            "def register(mesh):\n    raise SystemExit('should never run')\n",
            encoding="utf-8",
        )
        (root / "causalmesh.yaml").write_text(
            CONTRACT + "tools:\n  evil_mod:register:\n  evil_mod:\n", encoding="utf-8"
        )
        with ServeProcess(
            root, env={"CAUSALMESH_API_TOKEN": TOKEN, "PYTHONPATH": str(root)}
        ) as server:
            status, _, listed = server.request("GET", "/v1/tools", token=TOKEN)
            assert (status, listed) == (200, {"tools": []})
            # A request cannot name code either: an unknown tool is a 404.
            status, _, _ = server.request(
                "POST",
                "/v1/tools/evil_mod:register/execute",
                body={"agent_id": "coder", "arguments": {}},
                token=TOKEN,
            )
            assert status == 404
        assert not marker.exists(), "the server imported a module named only in the contract"


class TestBadSpecsAreUsageErrors:
    """Each names what to fix, exits 2, and never shows a traceback."""

    @pytest.fixture(autouse=True)
    def _files(self, root: Path) -> None:
        (root / "syntax_error.py").write_text("def register(mesh:\n", encoding="utf-8")
        (root / "no_func.py").write_text("X = 1\n", encoding="utf-8")
        (root / "not_callable.py").write_text("register = 3\n", encoding="utf-8")
        (root / "raises.py").write_text(
            "def register(mesh):\n    raise ValueError('bad config')\n", encoding="utf-8"
        )
        (root / "raises_at_import.py").write_text(
            "raise RuntimeError('at import')\n", encoding="utf-8"
        )
        (root / "registers_nothing.py").write_text(
            "def register(mesh):\n    pass\n", encoding="utf-8"
        )
        (root / "no_args.py").write_text("def register():\n    pass\n", encoding="utf-8")
        (root / "async_reg.py").write_text(
            "async def register(mesh):\n    pass\n", encoding="utf-8"
        )

    @pytest.mark.parametrize(
        ("spec", "needle"),
        [
            ("nocolon", "MODULE:FUNC"),
            (":register", "MODULE:FUNC"),
            ("my_tools:", "MODULE:FUNC"),
            ("my tools:register", "neither a dotted module name nor a path"),
            ("my_tools:reg-ister", "not a valid function name"),
            ("does_not_exist_xyz:register", "cannot import"),
            ("missing.py:register", "no such file"),
            ("syntax_error.py:register", "SyntaxError"),
            ("raises_at_import.py:register", "importing raised RuntimeError"),
            ("no_func.py:register", "no attribute 'register'"),
            ("not_callable.py:register", "not callable"),
            ("no_args.py:register", "one argument"),
            ("async_reg.py:register", "not async"),
            ("raises.py:register", "register() raised ValueError: bad config"),
            ("registers_nothing.py:register", "registered no tools"),
        ],
    )
    def test_bad_spec(self, root: Path, spec: str, needle: str) -> None:
        target, _, func = spec.rpartition(":")
        arg = f"{root / target}:{func}" if target.endswith(".py") else spec
        code, output = run_to_exit(root, "--dev", "--tools", arg)
        assert code == 2, output
        assert needle in " ".join(output.split()), output
        assert "Traceback" not in output

    def test_the_same_tool_registered_twice_is_refused(self, root: Path) -> None:
        spec = f"{root / 'my_tools.py'}:register"
        code, output = run_to_exit(root, "--dev", "--tools", spec, "--tools", spec)
        assert code == 2
        assert "already registered" in " ".join(output.split())

    def test_two_files_with_the_same_name_do_not_shadow_each_other(self, root: Path) -> None:
        (root / "a").mkdir()
        (root / "b").mkdir()
        for name in ("a", "b"):
            (root / name / "tools.py").write_text(
                "from causalmesh import Tool\n"
                "def register(mesh):\n"
                f"    mesh.register_tool(Tool(name={name!r}, handler=lambda: 1, mutating=False,"
                " resource_args=[]))\n",
                encoding="utf-8",
            )
        with ServeProcess(
            root,
            "--dev",
            "--tools",
            f"{root / 'a' / 'tools.py'}:register",
            "--tools",
            f"{root / 'b' / 'tools.py'}:register",
        ) as server:
            _, _, listed = server.request("GET", "/v1/tools")
            assert {t["name"] for t in listed["tools"]} == {"a", "b"}


def test_the_test_runs_the_worktrees_source() -> None:
    """A guard on the harness: the subprocess must import this checkout, not an installed copy."""
    import causalmesh

    assert (
        Path(causalmesh.__file__)
        .resolve()
        .is_relative_to(Path(__file__).resolve().parents[2] / "src")
    ), sys.path[:3]
