"""Property-based invariants for the signed chain (spec §24, §84).

The unit tests check the tampering cases I thought of. These check that the
chain's defining properties hold across generated histories — in particular
that *any* single-event change invalidates the chain from that point on,
rather than only the mutations that happened to occur to me.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from causalmesh.crypto.chain import GENESIS_HASH, ChainedEvent, compute_chain_hash, link_event
from causalmesh.crypto.keys import KeyPair
from causalmesh.events.schema import Event, EventIdentity, EventType

pytestmark = pytest.mark.property

SEED = b"causalmesh-property-master-seed"
ACTORS = ("agent_a", "agent_b", "agent_c")
KEYRING = {actor: KeyPair.derive(SEED, actor) for actor in ACTORS}

# Path components stay ASCII-safe here; Unicode path handling is covered
# directly by the canonicalization property tests.
paths_strategy = st.lists(
    st.sampled_from(["src/schema.py", "src/api.py", "src/util.py", "tests/test_api.py"]),
    min_size=0,
    max_size=3,
).map(tuple)


@st.composite
def event_specs(draw: st.DrawFn) -> tuple[str, EventType, tuple[str, ...]]:
    return (
        draw(st.sampled_from(ACTORS)),
        draw(st.sampled_from(list(EventType))),
        draw(paths_strategy),
    )


def build_event(sequence: int, spec: tuple[str, EventType, tuple[str, ...]]) -> Event:
    actor, event_type, paths = spec
    return Event(
        event_id=f"evt_{sequence:04d}",
        identity=EventIdentity(
            experiment_id="exp_property",
            task_id="task_property",
            run_id="run_001",
            agent_id=actor,
            arm="C2",
        ),
        event_type=event_type,
        sequence=sequence,
        timestamp_us=1_700_000_000_000_000 + sequence,
        paths=paths,
    )


def build_chain(specs: list[tuple[str, EventType, tuple[str, ...]]]) -> list[ChainedEvent]:
    chain: list[ChainedEvent] = []
    previous = GENESIS_HASH
    for sequence, spec in enumerate(specs):
        event = build_event(sequence, spec)
        linked = link_event(event, previous, KEYRING[event.identity.agent_id])
        chain.append(linked)
        previous = linked.chain_hash
    return chain


chain_specs = st.lists(event_specs(), min_size=1, max_size=8)

# Chain construction does real Ed25519 signing, so keep example counts modest
# and suppress the too-slow health check rather than weakening the property.
chain_settings = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@given(chain_specs)
@chain_settings
def test_every_built_chain_verifies(specs: list[tuple[str, EventType, tuple[str, ...]]]) -> None:
    chain = build_chain(specs)
    assert all(link.verify_hash() and link.verify_signature() for link in chain)


@given(chain_specs)
@chain_settings
def test_links_are_contiguous(specs: list[tuple[str, EventType, tuple[str, ...]]]) -> None:
    chain = build_chain(specs)
    assert chain[0].previous_hash == GENESIS_HASH
    assert all(nxt.previous_hash == cur.chain_hash for cur, nxt in pairwise(chain))


@given(chain_specs)
@chain_settings
def test_chain_hashes_are_unique(specs: list[tuple[str, EventType, tuple[str, ...]]]) -> None:
    # A repeated digest would mean two positions in history are
    # indistinguishable, which would let one be substituted for the other.
    chain = build_chain(specs)
    assert len({link.chain_hash for link in chain}) == len(chain)


@given(chain_specs, st.data())
@chain_settings
def test_altering_any_event_invalidates_that_link(
    specs: list[tuple[str, EventType, tuple[str, ...]]], data: st.DataObject
) -> None:
    chain = build_chain(specs)
    index = data.draw(st.integers(min_value=0, max_value=len(chain) - 1))
    target = chain[index]

    # Replace the event with a demonstrably different one at the same position.
    altered_paths = ("tampered/path.py",)
    if target.event.paths == altered_paths:
        altered_paths = ("tampered/other.py",)
    altered = build_event(
        target.event.sequence,
        (target.event.identity.agent_id, target.event.event_type, altered_paths),
    )

    # The recorded digest no longer matches the recomputed one.
    assert compute_chain_hash(target.previous_hash, altered) != target.chain_hash


@given(chain_specs, st.data())
@chain_settings
def test_truncating_a_suffix_leaves_a_self_consistent_chain(
    specs: list[tuple[str, EventType, tuple[str, ...]]], data: st.DataObject
) -> None:
    """The documented limitation (§27, §87), asserted rather than hidden.

    Dropping events from the end yields a shorter chain that still verifies
    internally. Nothing inside the chain can detect it — which is precisely
    why anchors (§28) are required, and why the security documentation must
    not claim truncation resistance without one.
    """
    chain = build_chain(specs)
    keep = data.draw(st.integers(min_value=1, max_value=len(chain)))
    truncated = chain[:keep]

    assert all(link.verify_hash() and link.verify_signature() for link in truncated)
    assert truncated[0].previous_hash == GENESIS_HASH
