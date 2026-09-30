"""Load an operator-supplied public key ring from disk.

This is the trust input for `causalmesh verify --keys`. It is the part of
verification that must come from somewhere other than the log being checked:
a ring built from the records' own `actor_public_key` fields proves the log
is self-consistent and nothing about who signed it (`verify_chain`'s own
docstring, and `docs/security.md`).

A key ring directory holds any mix of these, one actor per file name:

- `<agent_id>.pub`: the agent's Ed25519 public key as 64 hex characters,
  surrounding whitespace ignored. This is what to hand an auditor.
- `<agent_id>.key`: the agent's raw 32-byte seed, the same file
  `identity.keys` uses. The public key is derived from it. Prefer `.pub`:
  a verifier host has no business holding signing seeds, and this format
  exists so an operator who already has an `identity.keys` directory can
  point `--keys` at it without converting anything.
- `keyring.json`: a JSON object mapping agent id to public key hex, the file
  `Relay.export` writes.

A single file is read as `keyring.json`.

If two files name the same agent with different keys the load is refused. A
ring that quietly preferred one of them would let a stray file decide who is
trusted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .keys import KeyPair, PublicKeyRing, SignatureError

__all__ = ["KeyRingError", "load_key_ring"]

_HEX_KEY_LENGTH = 64


class KeyRingError(ValueError):
    """Raised when a key ring cannot be loaded or is ambiguous."""


def load_key_ring(path: Path | str) -> PublicKeyRing:
    """Read a `PublicKeyRing` from a directory of key files, or one JSON file.

    Raises `KeyRingError` for a missing path, an unreadable or malformed
    key, a conflict between two files, or a directory that holds no keys at
    all (an empty ring would fail every record as an unknown actor, which is
    an unhelpful way to learn the path was wrong).
    """
    target = Path(path)
    keys: dict[str, tuple[str, str]] = {}  # actor -> (public key hex, source file name)

    def add(actor: str, public_key: str, source: str) -> None:
        normalized = _normalize_public_key(public_key, source)
        known = keys.get(actor)
        if known is not None and known[0] != normalized:
            raise KeyRingError(
                f"{source} and {known[1]} name different keys for {actor!r}; "
                "remove one so the ring says a single thing"
            )
        keys[actor] = (normalized, source)

    if target.is_file():
        _read_json_ring(target, add)
    elif target.is_dir():
        for entry in sorted(target.iterdir(), key=lambda p: p.name):
            if not entry.is_file():
                continue
            if entry.suffix == ".pub" and entry.stem:
                add(entry.stem, _read_text(entry), entry.name)
            elif entry.suffix == ".key" and entry.stem:
                try:
                    pair = KeyPair.from_seed_file(entry, actor_id=entry.stem)
                except (SignatureError, ValueError) as exc:
                    raise KeyRingError(f"{entry.name}: {exc}") from exc
                add(entry.stem, pair.public_key_hex, entry.name)
            elif entry.name == "keyring.json":
                _read_json_ring(entry, add)
    else:
        raise KeyRingError(f"no key ring at {target}")

    if not keys:
        raise KeyRingError(
            f"{target} holds no keys. Expected <agent_id>.pub (64 hex characters), "
            "<agent_id>.key (32-byte seed) or keyring.json"
        )
    return PublicKeyRing(keys={actor: value[0] for actor, value in keys.items()})


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise KeyRingError(f"{path.name}: cannot read as ASCII hex: {exc}") from exc


def _read_json_ring(path: Path, add: Callable[[str, str, str], None]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KeyRingError(f"{path.name}: not a readable JSON key ring: {exc}") from exc
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise KeyRingError(f"{path.name}: must be a JSON object of agent id to public key hex")
    for actor, public_key in data.items():
        add(actor, public_key, path.name)


def _normalize_public_key(value: str, source: str) -> str:
    text = value.strip().lower()
    if len(text) != _HEX_KEY_LENGTH:
        raise KeyRingError(
            f"{source}: a public key is {_HEX_KEY_LENGTH} hex characters, got {len(text)}"
        )
    try:
        bytes.fromhex(text)
    except ValueError as exc:
        raise KeyRingError(f"{source}: public key is not hexadecimal") from exc
    return text
