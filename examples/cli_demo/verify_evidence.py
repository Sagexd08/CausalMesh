"""Read the gateway's evidence and verify it, using only public APIs.

    python verify_evidence.py            # verify what the gateway recorded
    python verify_evidence.py --tamper   # forge a record, show verification refuse it

The key ring is built here, from the operator's own keys, not read from the
evidence. A verifier that took the public keys out of the records it is
checking could not tell a forged, re-signed log from a real one (docs/security.md,
"Attribution is checked against the key ring, not the record").

Exit codes: 0 when the outcome is the expected one (valid without --tamper,
tamper detected with it), 1 when it is not, 2 when the gateway could not be read.
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
from typing import Any

from client import DEFAULT_URL, request

from causalmesh.crypto import KeyPair, PublicKeyRing
from causalmesh.verifier import verify_chain
from gateway import DEMO_SEED, build_mesh


def demo_key_ring() -> PublicKeyRing:
    """The operator's key ring: one public key per agent the mesh signs for."""
    agents = build_mesh().agents
    return PublicKeyRing.from_keypairs({a: KeyPair.derive(DEMO_SEED, a) for a in agents})


def describe(record: dict[str, Any]) -> str:
    event = record["event"]
    payload = event.get("payload", {})
    paths = ",".join(event.get("paths", [])) or "-"
    detail = payload.get("outcome", "?")
    if payload.get("rule"):
        detail += f" (rule: {payload['rule']})"
    return (
        f"{event['event_id']}  {event['event_type']:<8} agent={event['identity']['agent_id']}  "
        f"path={paths}  {detail}"
    )


def report(label: str, records: list[dict[str, Any]], ring: PublicKeyRing) -> bool:
    result = verify_chain(records, ring)
    print(f"{label}: valid={result.valid} events={result.events} failures={len(result.failures)}")
    for failure in result.failures[:3]:
        print(f"  - {failure.kind.value}: {failure.detail}")
    return result.valid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the demo gateway's evidence.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--tamper", action="store_true", help="verify a forged copy as well")
    args = parser.parse_args(argv)

    token = os.environ.get("CODING_AGENT_TOKEN")
    if not token:
        print("error: set CODING_AGENT_TOKEN", file=sys.stderr)
        return 2
    status, records = request("GET", f"{args.url}/v1/evidence", token=token)
    if status != 200 or not isinstance(records, list):
        print(f"error: could not read evidence (HTTP {status})", file=sys.stderr)
        return 2

    print(f"{len(records)} recorded events:")
    for record in records:
        print("  " + describe(record))

    ring = demo_key_ring()
    valid = report("recorded chain", records, ring)
    if not args.tamper:
        return 0 if valid else 1

    # Forge one record: claim the denied call was executed.
    forged = copy.deepcopy(records)
    victim = next((r for r in forged if r["event"]["payload"].get("outcome") == "denied"), None)
    if victim is None:
        print("error: nothing denied to forge; make a denied call first", file=sys.stderr)
        return 2
    victim["event"]["payload"]["outcome"] = "executed"
    print("\nforged copy: the denied call is rewritten as 'executed'")
    detected = not report("forged chain  ", forged, ring)
    print("tampering detected" if detected else "TAMPERING NOT DETECTED")
    return 0 if valid and detected else 1


if __name__ == "__main__":
    raise SystemExit(main())
