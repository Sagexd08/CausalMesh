"""Run the real `causalmesh serve` as a subprocess, and talk to it over a socket.

The unit tests of the server use `TestClient`, which never opens a port. This
is for the tests that must: TLS is a property of the socket, `--tools` is a
property of the command, and a shutdown is a property of the process.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

_LAUNCH = "from causalmesh.cli.main import main; main()"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ServeProcess:
    """`causalmesh serve ARGS` on a free port, from this checkout's `src`."""

    def __init__(
        self,
        root: Path,
        *args: str,
        tls_ca: Path | None = None,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> None:
        self.port = free_port()
        self._output: str | None = None
        self.tls_ca = tls_ca
        self.scheme = "https" if tls_ca is not None else "http"
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(REPO / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        for name in list(environment):
            if name.startswith("CAUSALMESH_"):
                del environment[name]
        extra = dict(env or {})
        if "PYTHONPATH" in extra:  # keep this checkout's src ahead of the caller's paths
            extra["PYTHONPATH"] = os.pathsep.join([str(REPO / "src"), extra["PYTHONPATH"]])
        environment.update(extra)
        self.command = [
            sys.executable,
            "-P",  # like the console script: the current directory is not on sys.path
            "-c",
            _LAUNCH,
            "serve",
            "--root",
            str(root),
            "--port",
            str(self.port),
            *args,
        ]
        self.process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
            cwd=str(cwd or root),
            text=True,
        )

    @property
    def base(self) -> str:
        return f"{self.scheme}://127.0.0.1:{self.port}"

    def _context(self) -> ssl.SSLContext | None:
        if self.tls_ca is None:
            return None
        context = ssl.create_default_context(cafile=str(self.tls_ca))
        return context

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        """One request; returns `(status, headers, parsed JSON or raw text)`."""
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=10, context=self._context()) as response:
                status, raw, received = response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            status, raw, received = error.code, error.read(), dict(error.headers)
        try:
            parsed: Any = json.loads(raw)
        except ValueError:
            parsed = raw.decode("utf-8", "replace")
        return status, received, parsed

    def wait_ready(self, timeout: float = 30.0) -> None:
        """Block until `/health` answers; fail with the process output if it never does."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"serve exited early ({self.process.returncode}):\n{self.output()}"
                )
            try:
                if self.request("GET", "/health")[0] == 200:
                    return
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)
        self.stop()
        raise RuntimeError(f"serve did not become ready:\n{self.output()}")

    def output(self) -> str:
        if self.process.poll() is None:
            return ""
        assert self.process.stdout is not None
        return self.process.stdout.read()

    def stop(self) -> str:
        """Terminate the server and return everything it wrote. Safe to call twice."""
        if self._output is not None:
            return self._output
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        assert self.process.stdout is not None
        self._output = self.process.stdout.read()
        self.process.stdout.close()
        return self._output

    def __enter__(self) -> ServeProcess:
        self.wait_ready()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


def run_to_exit(
    root: Path, *args: str, env: dict[str, str] | None = None, timeout: float = 30.0
) -> tuple[int, str]:
    """Run `serve` expecting it to refuse to start; returns `(exit code, output)`."""
    server = ServeProcess(root, *args, env=env)
    try:
        server.process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        output = server.stop()
        raise AssertionError(f"serve started, but was expected to refuse:\n{output}") from None
    assert server.process.stdout is not None
    return server.process.returncode, server.process.stdout.read()
