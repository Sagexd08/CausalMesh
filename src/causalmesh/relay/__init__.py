"""The relay: the single point through which every event enters the record.

Spec §55. The relay owns sequencing, signing, chaining, persistence and
fan-out. It does not judge task correctness, does not touch agent reasoning,
and never rewrites an event it has accepted.

Arm behaviour is supplied from outside as a `DeliveryPolicy`, so C0's
isolation is a property of which policy was installed rather than of a branch
inside the ingestion path.
"""

from __future__ import annotations

from .core import (
    DeliveryPolicy,
    IngestError,
    IngestResult,
    NullDelivery,
    Relay,
    RelayStats,
)
from .delivery import (
    BROADCAST,
    DELIVERY_MODES,
    MUTATING_EVENT_TYPES,
    PATH_SCOPED,
    BroadcastDelivery,
    PathScopedDelivery,
    policy_for_arm,
)
from .store import ChainStore, StoreError

__all__ = [
    "BROADCAST",
    "DELIVERY_MODES",
    "MUTATING_EVENT_TYPES",
    "PATH_SCOPED",
    "BroadcastDelivery",
    "ChainStore",
    "DeliveryPolicy",
    "IngestError",
    "IngestResult",
    "NullDelivery",
    "PathScopedDelivery",
    "Relay",
    "RelayStats",
    "StoreError",
    "policy_for_arm",
]
