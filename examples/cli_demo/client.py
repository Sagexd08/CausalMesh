"""A small HTTP client for the demo gateway. Standard library only, so it
behaves the same on Windows, macOS and Linux.

    python client.py tools
    python client.py write src/app.py "print(1)"
    python client.py write production/schema.sql "DROP TABLE users;"
    python client.py evidence

The token comes from CODING_AGENT_TOKEN. Prints `HTTP <status>` and the JSON
body; exits 0 for a 2xx answer and 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8420"


def request(
    method: str,
    url: str,
    *,
    token: str | None,
    body: dict[str, Any] | bytes | None = None,
) -> tuple[int, Any]:
    """One HTTP call. Returns (status, parsed JSON or raw text)."""
    data = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            status, raw = resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode("utf-8")
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def execute(
    base: str, token: str | None, tool: str, agent_id: str, arguments: dict[str, Any]
) -> tuple[int, Any]:
    return request(
        "POST",
        f"{base}/v1/tools/{tool}/execute",
        token=token,
        body={"agent_id": agent_id, "arguments": arguments},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Talk to the CausalMesh demo gateway.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--agent", default="coding-agent", help="agent_id sent in the request body")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("tools", help="list the registered tools")
    write = sub.add_parser("write", help="call the write_file tool")
    write.add_argument("path")
    write.add_argument("content", nargs="?", default="print(1)")
    sub.add_parser("evidence", help="read the recorded evidence")
    args = parser.parse_args(argv)

    token = os.environ.get("CODING_AGENT_TOKEN")
    if not token:
        print(
            "error: set CODING_AGENT_TOKEN (the same value the gateway was started with)",
            file=sys.stderr,
        )
        return 2

    if args.command == "tools":
        status, body = request("GET", f"{args.url}/v1/tools", token=token)
    elif args.command == "write":
        status, body = execute(
            args.url, token, "write_file", args.agent, {"path": args.path, "content": args.content}
        )
    else:
        status, body = request("GET", f"{args.url}/v1/evidence", token=token)

    print(f"HTTP {status}")
    print(json.dumps(body, indent=2) if not isinstance(body, str) else body)
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
