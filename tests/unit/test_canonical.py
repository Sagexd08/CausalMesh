"""Unit tests for canonicalization (spec §25).

Each rejection test below maps to a hazard verified empirically against
CPython 3.13 before this module was written. They are regression guards
against a future "convenience" change quietly reintroducing ambiguity.
"""

from __future__ import annotations

import json

import pytest

from causalmesh.events.canonical import (
    MAX_NESTING_DEPTH,
    CanonicalizationError,
    canonical_json,
    canonicalize,
    normalize_text,
)

pytestmark = pytest.mark.unit


class TestDeterminism:
    def test_key_order_does_not_affect_output(self) -> None:
        assert canonicalize({"a": 1, "b": 2, "c": 3}) == canonicalize({"c": 3, "b": 2, "a": 1})

    def test_nested_key_order_does_not_affect_output(self) -> None:
        first = {"outer": {"z": 1, "a": {"y": 2, "b": 3}}}
        second = {"outer": {"a": {"b": 3, "y": 2}, "z": 1}}
        assert canonicalize(first) == canonicalize(second)

    def test_repeated_calls_are_stable(self) -> None:
        value = {"k": [1, 2, {"nested": "value"}], "other": None}
        assert len({canonicalize(value) for _ in range(50)}) == 1

    def test_output_is_valid_utf8_json(self) -> None:
        raw = canonicalize({"k": "café", "n": 1})
        assert json.loads(raw.decode("utf-8")) == {"k": "café", "n": 1}


class TestFormatting:
    def test_no_insignificant_whitespace(self) -> None:
        # Python's default would emit '{"a": 1, "b": [1, 2]}'.
        assert canonical_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'

    def test_non_ascii_is_literal_not_escaped(self) -> None:
        # Default ensure_ascii=True would emit '\\u00e9' and change the bytes.
        assert canonical_json({"k": "café"}) == '{"k":"café"}'

    def test_list_order_is_preserved(self) -> None:
        assert canonical_json([3, 1, 2]) == "[3,1,2]"

    def test_tuple_and_list_agree(self) -> None:
        # Tuples are used for immutable event fields; they must not produce
        # different bytes from the equivalent list.
        assert canonicalize((1, 2, 3)) == canonicalize([1, 2, 3])


class TestUnicodeNormalization:
    def test_composed_and_decomposed_strings_agree(self) -> None:
        composed = "café"  # é as one code point
        decomposed = "café"  # e + combining acute
        assert composed != decomposed  # distinct in Python
        assert canonicalize(composed) == canonicalize(decomposed)

    def test_normalization_applies_to_keys(self) -> None:
        assert canonicalize({"café": 1}) == canonicalize({"café": 1})

    def test_colliding_keys_are_rejected_not_silently_merged(self) -> None:
        # Both keys normalize to the same string; keeping one would drop data.
        with pytest.raises(CanonicalizationError, match="collide"):
            canonicalize({"café": 1, "café": 2})

    def test_normalize_text_is_idempotent(self) -> None:
        once = normalize_text("café")
        assert normalize_text(once) == once


class TestRejections:
    @pytest.mark.parametrize(
        "value",
        [float("nan"), float("inf"), float("-inf"), 1.5, 0.1, 1.0],
        ids=["nan", "inf", "-inf", "fraction", "inexact", "whole"],
    )
    def test_floats_are_rejected(self, value: float) -> None:
        # json.dumps(float('nan')) emits bare NaN, which is not valid JSON.
        # Whole floats are rejected too: accepting 1.0 invites 0.1 later.
        with pytest.raises(CanonicalizationError, match="float"):
            canonicalize({"k": value})

    def test_non_string_keys_are_rejected(self) -> None:
        # json.dumps({2: 'b'}) silently yields {"2": "b"}, colliding with "2".
        with pytest.raises(CanonicalizationError, match="not str"):
            canonicalize({2: "b"})

    def test_bool_keys_are_rejected(self) -> None:
        # True == 1 and hashes identically, so bool keys collide with int keys.
        with pytest.raises(CanonicalizationError, match="not str"):
            canonicalize({True: "x"})

    def test_bytes_are_rejected(self) -> None:
        with pytest.raises(CanonicalizationError, match="bytes"):
            canonicalize({"k": b"raw"})

    def test_unknown_types_are_rejected(self) -> None:
        class Custom:
            pass

        with pytest.raises(CanonicalizationError, match="no canonical form"):
            canonicalize({"k": Custom()})

    def test_excessive_nesting_is_rejected(self) -> None:
        deep: dict = {}
        cursor = deep
        for _ in range(MAX_NESTING_DEPTH + 5):
            cursor["n"] = {}
            cursor = cursor["n"]
        with pytest.raises(CanonicalizationError, match="nesting"):
            canonicalize(deep)

    def test_error_message_names_the_offending_path(self) -> None:
        with pytest.raises(CanonicalizationError, match=r"\$\.outer\.inner\[1\]"):
            canonicalize({"outer": {"inner": [1, 2.5]}})


class TestTypePreservation:
    def test_bool_is_not_conflated_with_int(self) -> None:
        # True == 1 in Python; the canonical bytes must still differ.
        assert canonicalize({"k": True}) != canonicalize({"k": 1})

    def test_none_is_preserved(self) -> None:
        assert canonical_json({"k": None}) == '{"k":null}'

    def test_large_integers_survive_exactly(self) -> None:
        # Large ints must not be truncated or converted to float on the way
        # through JSON; the parsed value has to equal the original exactly.
        big = 2**70 + 12345
        parsed = json.loads(canonicalize({"k": big}).decode())["k"]
        assert parsed == big
        assert isinstance(parsed, int)

    def test_empty_containers(self) -> None:
        assert canonical_json({"a": {}, "b": []}) == '{"a":{},"b":[]}'
