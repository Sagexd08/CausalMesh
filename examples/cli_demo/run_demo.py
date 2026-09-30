"""Run the whole demo journey, unattended, against a real gateway process.

    python run_demo.py

It starts gateway.py on a free port, drives it over HTTP, asks the CLI for
policy verdicts, reads back and verifies the evidence, then stops the gateway.
No API key, model or network beyond localhost. Every expectation is checked:
the exit code is 0 only if all of them held.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from client import execute, request
from verify_evidence import demo_key_ring

from causalmesh.verifier import verify_chain

HERE = Path(__file__).resolve().parent
TOKEN = "cm-demo-token-0001-abcdef"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> bool:
    results.append((ok, label))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    return ok


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the real `causalmesh` command line, from the demo directory."""
    code = "from causalmesh.cli.main import app; app()"
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", code, *args],
        cwd=HERE,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=60,
    )


class Gateway:
    def __init__(self, port: int) -> None:
        self.port = port
        self.lines: list[str] = []
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0  # type: ignore[attr-defined]
        self.proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-u", str(HERE / "gateway.py"), "--port", str(port)],
            cwd=HERE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "CODING_AGENT_TOKEN": TOKEN, "PYTHONIOENCODING": "utf-8"},
            creationflags=flags,
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.append(line.rstrip())

    def wait_ready(self) -> bool:
        for _ in range(120):
            if self.proc.poll() is not None:
                return False
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.3).close()
                return True
            except OSError:
                time.sleep(0.25)
        return False

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)  # type: ignore[attr-defined]
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def handler_calls(self) -> list[str]:
        return [ln for ln in self.lines if ln.startswith("[handler]")]


def main() -> int:
    print("CausalMesh CLI demo: policy, gateway, tool, evidence")

    print("\n1. the contract, as the CLI reads it")
    r = cli("policy", "validate")
    check(r.returncode == 0 and "VALID" in r.stdout, "causalmesh policy validate: VALID")
    r = cli("policy", "check", "--agent", "coding-agent", "--kind", "path", "--name", "src/app.py")
    check(
        r.returncode == 0 and r.stdout.startswith("ALLOW"),
        "policy check src/app.py: ALLOW (exit 0)",
    )
    r = cli(
        "policy",
        "check",
        "--agent",
        "coding-agent",
        "--kind",
        "path",
        "--name",
        "production/schema.sql",
    )
    check(
        r.returncode == 1 and r.stdout.startswith("REFUSE"),
        "policy check production/schema.sql: REFUSE (exit 1)",
    )

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"\n2. start the gateway (port {port})")
    gw = Gateway(port)
    try:
        if not check(gw.wait_ready(), "gateway is listening"):
            print("\n".join(gw.lines))
            return 1

        status, body = request("GET", f"{base}/v1/tools", token=TOKEN)
        names = [t["name"] for t in body["tools"]] if status == 200 else []
        check(status == 200 and names == ["write_file"], "GET /v1/tools lists write_file")

        print("\n3. an authorized call")
        status, body = execute(
            base, TOKEN, "write_file", "coding-agent", {"path": "src/app.py", "content": "print(1)"}
        )
        check(
            status == 200 and body["executed"] and body["allowed"],
            "src/app.py: HTTP 200, allowed and executed",
        )
        check(
            body.get("recorded") is True and bool(body.get("event_id")),
            "the call was recorded with an event_id",
        )
        time.sleep(0.3)
        check(
            gw.handler_calls() == ["[handler] write_file src/app.py"],
            "the handler ran exactly once",
        )

        print("\n4. a denied call")
        status, body = execute(
            base,
            TOKEN,
            "write_file",
            "coding-agent",
            {"path": "production/schema.sql", "content": "DROP TABLE users;"},
        )
        detail = body.get("detail", {}) if isinstance(body, dict) else {}
        check(
            status == 403 and detail.get("rule") == "ownership",
            "production/schema.sql: HTTP 403, rule ownership",
        )
        check(detail.get("recorded") is True, "the denial was recorded")
        time.sleep(0.3)
        check(
            not any("production" in ln for ln in gw.handler_calls())
            and len(gw.handler_calls()) == 1,
            "the handler did NOT run for the denied call",
        )

        print("\n5. authentication and malformed input")
        args = {"path": "src/x.py", "content": "x"}
        status, _ = execute(base, None, "write_file", "coding-agent", args)
        check(status == 401, "no token: HTTP 401")
        status, _ = execute(base, "wrong-token-value-000000", "write_file", "coding-agent", args)
        check(status == 401, "wrong token: HTTP 401")
        status, _ = execute(
            base, TOKEN, "write_file", "dba-agent", {"path": "production/x.sql", "content": "x"}
        )
        check(status == 403, "coding-agent's token claiming to be dba-agent: HTTP 403")
        status, _ = execute(base, TOKEN, "no_such_tool", "coding-agent", args)
        check(status == 404, "unknown tool: HTTP 404")
        status, _ = execute(base, TOKEN, "write_file", "coding-agent", {"content": "no path given"})
        check(status == 422, "missing the declared path argument: HTTP 422")
        status, _ = request(
            "POST", f"{base}/v1/tools/write_file/execute", token=TOKEN, body=b"{not json"
        )
        check(status == 422, "a body that is not JSON: HTTP 422")
        time.sleep(0.3)
        check(len(gw.handler_calls()) == 1, "none of those reached the handler")

        print("\n6. the evidence")
        status, records = request("GET", f"{base}/v1/evidence", token=TOKEN)
        check(
            status == 200 and isinstance(records, list) and len(records) == 2,
            "two events recorded: one allowed, one denied",
        )
        outcomes = [r["event"]["payload"]["outcome"] for r in records] if status == 200 else []
        check(outcomes == ["executed", "denied"], "outcomes in order: executed, denied")
        status, _ = request("GET", f"{base}/v1/evidence", token=None)
        check(status == 401, "evidence without a token: HTTP 401")

        ring = demo_key_ring()
        result = verify_chain(records, ring)
        check(
            result.valid and result.events == 2,
            "verify_chain against the operator's key ring: valid",
        )
        forged = [dict(r) for r in records]
        forged[1] = {
            **records[1],
            "event": {
                **records[1]["event"],
                "payload": {**records[1]["event"]["payload"], "outcome": "executed"},
            },
        }
        check(
            not verify_chain(forged, ring).valid,
            "a record rewritten to say the denial 'executed': verification fails",
        )
    finally:
        gw.stop()

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for label in failed:
        print(f"  FAILED: {label}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
