"""Fixtures for the adversarial battery (spec §27, §58).

The battery works by building a genuine, valid chain and then performing one
specific attack on it. Every attack must be *detected* by the offline
verifier, except suffix truncation without an anchor, which is a documented
limitation rather than a defect.

Attacks operate on the serialized record dicts — the same form that lands in
`data/raw/` — rather than on in-memory objects, because that is exactly the
surface an attacker with filesystem access has.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from causalmesh.crypto.chain import GENESIS_HASH, link_event
from causalmesh.crypto.keys import KeyPair, PublicKeyRing
from chain_fixtures import ACTORS, SCRIPT, SEED, build_event


@pytest.fixture(scope="session")
def keypairs() -> dict[str, KeyPair]:
    return {actor: KeyPair.derive(SEED, actor) for actor in ACTORS}


@pytest.fixture(scope="session")
def key_ring(keypairs: dict[str, KeyPair]) -> PublicKeyRing:
    return PublicKeyRing.from_keypairs(keypairs)


@pytest.fixture
def clean_records(keypairs: dict[str, KeyPair]) -> list[dict[str, Any]]:
    """A genuine, fully valid chain in its persisted form.

    Returned as fresh copies each time so an attack in one test cannot leak
    into another.
    """
    records: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    for sequence, (actor, event_type, paths) in enumerate(SCRIPT):
        event = build_event(sequence, actor, event_type, paths)
        linked = link_event(event, previous, keypairs[actor])
        records.append(copy.deepcopy(linked.to_dict()))
        previous = linked.chain_hash
    return records
