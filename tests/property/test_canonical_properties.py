"""Property-based invariants for canonicalization (spec §25, §84).

The unit tests check hazards I anticipated. These check the invariants hold
across inputs I did not think of — which is the point, since an integrity
digest is only as trustworthy as its least-anticipated input.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings, strategies as st

from causalmesh.events.canonical import canonicalize

pytestmark = pytest.mark.property


# Values the canonicalizer accepts: no floats, no bytes, string keys only.
canonical_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda children: st.lists(children, max_size=6)
    | st.dictionaries(st.text(min_size=1), children, max_size=6),
    max_leaves=25,
)


@given(canonical_values)
@settings(max_examples=300)
def test_canonicalization_is_deterministic(value: object) -> None:
    """The same value always produces identical bytes."""
    assert canonicalize(value) == canonicalize(value)


@given(canonical_values)
@settings(max_examples=300)
def test_output_is_always_valid_json(value: object) -> None:
    """Output must parse. This is what catches NaN-style invalid emissions."""
    json.loads(canonicalize(value).decode("utf-8"))


@given(canonical_values)
@settings(max_examples=300)
def test_output_is_always_valid_utf8(value: object) -> None:
    canonicalize(value).decode("utf-8")


@given(st.dictionaries(st.text(min_size=1), st.integers(), min_size=2, max_size=8))
@settings(max_examples=300)
def test_key_insertion_order_never_matters(mapping: dict) -> None:
    """Rebuilding a dict in reverse order must not change the bytes."""
    reversed_mapping = dict(reversed(list(mapping.items())))
    assert canonicalize(mapping) == canonicalize(reversed_mapping)


@given(canonical_values)
@settings(max_examples=300)
def test_round_trip_preserves_structure(value: object) -> None:
    """Parsing the canonical bytes and re-canonicalizing is a fixed point.

    This is the property that matters for verification: a verifier reads bytes
    from disk, parses them, and must arrive at the same canonical form.
    """
    first = canonicalize(value)
    assert canonicalize(json.loads(first.decode("utf-8"))) == first


@given(st.lists(st.integers(), min_size=2, max_size=8))
@settings(max_examples=200)
def test_sequence_order_is_significant(items: list[int]) -> None:
    """Unlike mapping keys, list order must be preserved, not normalized."""
    if items != list(reversed(items)):
        assert canonicalize(items) != canonicalize(list(reversed(items)))
