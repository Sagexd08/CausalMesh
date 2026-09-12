"""Offline verification of signed event chains (spec §26).

This package depends only on `causalmesh.events` and `causalmesh.crypto`. It
must never import the relay: evidence that can only be checked by the system
that produced it is not evidence. `tests/integration/test_import_boundaries.py`
enforces that mechanically.
"""

from __future__ import annotations

from .certificate import (
    CERTIFICATE_VERSION,
    VerificationCertificate,
    write_certificate,
)
from .offline import (
    SUPPORTED_SCHEMA_VERSIONS,
    load_chain,
    parse_record,
    verify_chain,
)
from .result import (
    AnchorStatus,
    FailureKind,
    VerificationFailure,
    VerificationResult,
)

__all__ = [
    "CERTIFICATE_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "AnchorStatus",
    "FailureKind",
    "VerificationCertificate",
    "VerificationFailure",
    "VerificationResult",
    "load_chain",
    "parse_record",
    "verify_chain",
    "write_certificate",
]
