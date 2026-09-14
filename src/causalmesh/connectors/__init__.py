"""Connecting to the coding agents and infrastructure on this machine.

Two halves:

- `discovery` probes what is installed. A tool on `PATH` is not a working
  tool, so every probe actually invokes the thing and reports `available`,
  `degraded` or `absent`.
- `process` drives an installed agent headlessly as a subprocess.

**A run driven by a real agent is not reproducible**, and its artifact says
so: the scheduler stamps `reproducible: false` whenever a connector was
used. Hosted models are nondeterministic, the agent's own version moves
under it, and §84 already records that temperature alone is not a
reproducibility guarantee. The chain still signs and verifies — it records
what happened, which is a different property from being repeatable.

**A run driven by a real agent costs money.** Nothing here runs an agent
unless the caller named it.
"""

from __future__ import annotations

from .discovery import Availability, Probe, available_agents, discover, probe
from .process import AgentInvocation, ConnectorError, ConnectorSpec, invoke, spec_for

__all__ = [
    "AgentInvocation",
    "Availability",
    "ConnectorError",
    "ConnectorSpec",
    "Probe",
    "available_agents",
    "discover",
    "invoke",
    "probe",
    "spec_for",
]
