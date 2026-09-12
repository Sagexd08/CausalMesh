"""Verification certificates (spec §59).

A certificate is the durable record of a verification: what was checked, what
passed, what failed, and under exactly which software version and inputs. A
result that exists only as a console line cannot be cited by a report, so
every verification the CLI performs writes one of these.

Certificates are *derived* artifacts. They belong under `artifacts/`, never
under `data/raw/`, which stays immutable once a run finalizes (§31).
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..events.schema import SCHEMA_VERSION
from .result import VerificationResult

__all__ = ["VerificationCertificate", "write_certificate"]

# Bumped when the certificate's own shape changes, so a consumer can tell
# whether it understands the document it is reading.
CERTIFICATE_VERSION = 1


@dataclass(frozen=True)
class VerificationCertificate:
    """A verification result plus the context needed to interpret it later.

    The context matters as much as the verdict: "the chain verified" is only
    meaningful alongside which key ring was used, which software produced the
    answer, and which inputs were read. Without those, a stored `valid: true`
    is an assertion rather than evidence.
    """

    result: VerificationResult
    run_id: str
    chain_path: str
    software_version: str
    created_at: str
    anchors_supplied: int
    inputs: dict[str, str]

    @classmethod
    def create(
        cls,
        result: VerificationResult,
        run_id: str,
        chain_path: Path | str,
        *,
        software_version: str,
        anchors_supplied: int = 0,
        inputs: dict[str, str] | None = None,
    ) -> VerificationCertificate:
        return cls(
            result=result,
            run_id=run_id,
            chain_path=str(chain_path),
            software_version=software_version,
            created_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            anchors_supplied=anchors_supplied,
            inputs=inputs or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "certificate_version": CERTIFICATE_VERSION,
            "created_at": self.created_at,
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "inputs": dict(self.inputs),
            "kind": "verification",
            "run_id": self.run_id,
            "schema_version": SCHEMA_VERSION,
            "software_version": self.software_version,
            "verification": {
                **self.result.to_dict(),
                "anchors_supplied": self.anchors_supplied,
                "chain_path": self.chain_path,
            },
        }


def write_certificate(certificate: VerificationCertificate, path: Path) -> Path:
    """Write a certificate as indented JSON, creating parent directories.

    Written sorted and indented rather than canonically: this is a document
    for people and for report generation, not an input to a digest.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(certificate.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path
