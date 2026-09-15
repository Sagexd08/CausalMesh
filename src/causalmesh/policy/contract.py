"""The contract: `causalmesh.yaml`, parsed and validated.

**What it is for.** AGENTS.md says what agents *should* do; it is read by
every major agent and enforced by none. This file says what they *may* do,
and the gate holds them to it. The two are siblings on purpose — a convention
every agent reads and no agent is held to is a convention without a
substrate, and this is the substrate half.

**Declared, never inferred.** Ownership, allowlists and budgets are written
by a person and read by the gate. Nothing here is learned from what agents
did, because a rule derived from behaviour cannot refuse that behaviour.

**Validation is strict, and says what to fix.** An unknown key is an error
rather than a shrug: a typo in `budgets` that silently parses as nothing is a
budget that does not exist, and a budget that does not exist reports a
confident zero. That is the same defect class recorded in `docs/backlog.md`,
so it fails loudly here.

**Absent means unrestricted; present means enforced.** A role with no
allowlist may reach anywhere; a role with an empty one may reach nowhere. The
distinction is deliberate and is what makes incremental adoption possible —
you declare the parts you care about and the rest keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from causalmesh.policy.resource import Resource, ResourceKind

__all__ = ["Contract", "ContractError", "Role"]

CONTRACT_FILENAME = "causalmesh.yaml"

# Every key this version understands, by section. Used to reject typos with a
# message naming the valid neighbours rather than ignoring them.
_TOP_LEVEL = {"version", "identity", "roles", "policy", "evidence"}
_ROLE_KEYS = {"agent_id", "archetype", "owns", "allow", "budget"}
_BUDGET_KEYS = {"usd_total", "usd_per_call", "tokens", "wall_clock_s", "coordination_bytes"}
_POLICY_KEYS = {"arm", "contested", "budgets", "checkpoints"}

SUPPORTED_VERSION = 1


class ContractError(ValueError):
    """The contract could not be read, or says something invalid."""


@dataclass(frozen=True, slots=True)
class Role:
    """One agent, and what it is permitted."""

    agent_id: str
    archetype: str = ""
    owns: tuple[str, ...] = ()
    # None means unrestricted; an empty frozenset means nothing is allowed.
    allow: frozenset[str] | None = None
    budget: dict[str, Decimal] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "allow": sorted(self.allow) if self.allow is not None else None,
            "archetype": self.archetype,
            "budget": {key: f"{value:f}" for key, value in sorted(self.budget.items())},
            "owns": list(self.owns),
        }


@dataclass(frozen=True, slots=True)
class Contract:
    """A whole `causalmesh.yaml`, validated."""

    version: int = SUPPORTED_VERSION
    roles: tuple[Role, ...] = ()
    arm: str = "C3"
    contested: dict[str, str] = field(default_factory=dict)
    budgets: dict[str, Decimal] = field(default_factory=dict)
    sign: bool = True
    source: Path | None = None

    # -- lookups the gate uses --------------------------------------------

    def role(self, agent_id: str) -> Role | None:
        return next((role for role in self.roles if role.agent_id == agent_id), None)

    def owner_of(self, path: str) -> str | None:
        """Which agent owns this path, if any.

        Longest declaration wins, so a specific file overrides the directory
        containing it. Without that, declaring `src/` and then carving out
        `src/config.py` for another agent would be impossible to express —
        and carving out one contested file is the common case.
        """
        normalized = Resource.path(path).to_dict()["name"]
        best: tuple[int, str] | None = None
        for role in self.roles:
            for owned in role.owns:
                owned_name = Resource.path(owned).to_dict()["name"]
                if _covers(owned_name, normalized) and (best is None or len(owned_name) > best[0]):
                    best = (len(owned_name), role.agent_id)
        return best[1] if best else None

    def allowlist_for(self, agent_id: str) -> set[str] | None:
        """Hosts this agent may reach, or None for unrestricted."""
        role = self.role(agent_id)
        if role is None or role.allow is None:
            return None
        return set(role.allow)

    def per_call_ceiling(self, agent_id: str) -> Decimal | None:
        role = self.role(agent_id)
        if role is None:
            return None
        return role.budget.get("usd_per_call")

    def budget_for(self, agent_id: str, resource: Resource) -> Decimal | None:
        """The total allowance covering this resource, if one is declared.

        A role's own budget takes precedence over the run-wide one: the
        specific statement should win over the general, the same way the
        longest path declaration wins in `owner_of`.
        """
        key = _budget_key(resource)
        if key is None:
            return None
        role = self.role(agent_id)
        if role is not None and key in role.budget:
            return role.budget[key]
        return self.budgets.get(key)

    def is_contested(self, path: str) -> bool:
        """Whether this path is declared as needing an exclusive lease."""
        normalized = Resource.path(path).to_dict()["name"]
        return any(
            _covers(Resource.path(declared).to_dict()["name"], normalized)
            for declared in self.contested
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "budgets": {key: f"{value:f}" for key, value in sorted(self.budgets.items())},
            "contested": dict(sorted(self.contested.items())),
            "roles": [role.to_dict() for role in self.roles],
            "sign": self.sign,
            "version": self.version,
        }

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str) -> Contract:
        """Read and validate a contract file."""
        path = Path(path)
        if not path.is_file():
            raise ContractError(f"no contract at {path}")
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - declared dependency
            raise ContractError("pyyaml is required to read a contract") from exc
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ContractError(f"{path} is not valid YAML: {exc}") from exc
        if raw is None:
            raise ContractError(f"{path} is empty")
        return cls.from_dict(raw, source=path)

    @classmethod
    def find(cls, start: Path | str | None = None) -> Contract | None:
        """Walk upward for a contract, returning None if there is none.

        None rather than raising, because running without a contract is a
        normal state — it is what every user has before they adopt this.
        """
        current = Path(start or Path.cwd()).resolve()
        for candidate in (current, *current.parents):
            found = candidate / CONTRACT_FILENAME
            if found.is_file():
                return cls.load(found)
        return None

    @classmethod
    def from_dict(cls, raw: Any, *, source: Path | None = None) -> Contract:
        if not isinstance(raw, dict):
            raise ContractError("a contract must be a mapping at the top level")
        _reject_unknown(raw, _TOP_LEVEL, "top level")

        version = raw.get("version", SUPPORTED_VERSION)
        if version != SUPPORTED_VERSION:
            raise ContractError(
                f"contract version {version!r} is not supported; this build reads "
                f"version {SUPPORTED_VERSION}"
            )

        policy = raw.get("policy") or {}
        if not isinstance(policy, dict):
            raise ContractError("`policy` must be a mapping")
        _reject_unknown(policy, _POLICY_KEYS, "policy")

        arm = str(policy.get("arm", "C3")).upper()
        if arm not in {"C0", "C1", "C2", "C3"}:
            raise ContractError(f"unknown arm {arm!r}; expected one of C0, C1, C2, C3")

        contested = policy.get("contested") or {}
        if not isinstance(contested, dict):
            raise ContractError("`policy.contested` must be a mapping of path to mode")

        evidence = raw.get("evidence") or {}
        if not isinstance(evidence, dict):
            raise ContractError("`evidence` must be a mapping")

        roles = tuple(
            _parse_role(entry, index) for index, entry in enumerate(raw.get("roles") or [])
        )
        seen: set[str] = set()
        for role in roles:
            if role.agent_id in seen:
                raise ContractError(f"duplicate agent_id {role.agent_id!r} in roles")
            seen.add(role.agent_id)

        return cls(
            arm=arm,
            budgets=_parse_budget(policy.get("budgets") or {}, "policy.budgets"),
            contested={str(key): str(value) for key, value in contested.items()},
            roles=roles,
            sign=bool(evidence.get("sign", True)),
            source=source,
            version=int(version),
        )


def _parse_role(entry: Any, index: int) -> Role:
    where = f"roles[{index}]"
    if not isinstance(entry, dict):
        raise ContractError(f"{where} must be a mapping")
    _reject_unknown(entry, _ROLE_KEYS, where)

    agent_id = entry.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ContractError(f"{where} needs a non-empty `agent_id`")

    owns = entry.get("owns") or []
    if not isinstance(owns, list) or not all(isinstance(item, str) for item in owns):
        raise ContractError(f"{where}.owns must be a list of paths")

    allow = entry.get("allow")
    if allow is not None:
        if not isinstance(allow, list) or not all(isinstance(item, str) for item in allow):
            raise ContractError(f"{where}.allow must be a list of hosts")
        # Lower-cased here so the gate compares like with like; hosts are
        # case-insensitive and `Resource` folds them the same way.
        allow = frozenset(item.strip().lower() for item in allow)

    return Role(
        agent_id=agent_id.strip(),
        allow=allow,
        archetype=str(entry.get("archetype") or ""),
        budget=_parse_budget(entry.get("budget") or {}, f"{where}.budget"),
        owns=tuple(owns),
    )


def _parse_budget(raw: Any, where: str) -> dict[str, Decimal]:
    if not isinstance(raw, dict):
        raise ContractError(f"{where} must be a mapping")
    _reject_unknown(raw, _BUDGET_KEYS, where)
    parsed: dict[str, Decimal] = {}
    for key, value in raw.items():
        if isinstance(value, float):
            # A float budget is already imprecise before it is compared.
            # Rejecting it here points at the line that wrote it.
            raise ContractError(
                f"{where}.{key} must be quoted or an integer, not a float "
                f"({value!r} cannot be represented exactly)"
            )
        try:
            parsed[str(key)] = Decimal(str(value))
        except (InvalidOperation, TypeError) as exc:
            raise ContractError(f"{where}.{key} is not a number: {value!r}") from exc
        if parsed[str(key)] < 0:
            raise ContractError(f"{where}.{key} must not be negative")
    return parsed


def _reject_unknown(mapping: dict[str, Any], known: set[str], where: str) -> None:
    """Fail on a key this version does not understand.

    Named neighbours in the message, because the usual cause is a typo or a
    key from a newer version, and both are fixed by seeing the valid set.
    """
    unknown = set(mapping) - known
    if unknown:
        raise ContractError(
            f"unknown key(s) in {where}: {', '.join(sorted(unknown))}. "
            f"Valid keys here: {', '.join(sorted(known))}"
        )


def _budget_key(resource: Resource) -> str | None:
    """Which declared budget governs this resource."""
    if resource.kind is ResourceKind.SPEND:
        return "usd_total"
    if resource.kind is ResourceKind.BUDGET:
        # A budget resource names its own allowance: Resource.budget(
        # name="tokens", ...) is governed by the `tokens` key.
        return resource.to_dict()["name"]
    return None


def _covers(declaration: str, candidate: str) -> bool:
    """Whether a declared path covers a candidate path.

    Exact match, or the declaration is a directory prefix of the candidate.
    Compared on segment boundaries so `src/app` does not cover
    `src/application.py` — a prefix test without this is how an ownership
    rule silently claims a neighbour's file.
    """
    if declaration == candidate:
        return True
    prefix = declaration if declaration.endswith("/") else f"{declaration}/"
    return candidate.startswith(prefix)
