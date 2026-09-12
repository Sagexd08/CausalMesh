"""Deterministic canonicalization of events into bytes.

Spec §25. This module is load-bearing: the hash chain, every signature and the
offline verifier all derive from the bytes produced here. If two runs can
serialize the same logical event into different bytes, every downstream
integrity claim silently becomes false.

The guarantee is:

    same event -> same canonical bytes -> same digest

on any platform, any Python build, any dict insertion order.

Rather than trusting a JSON encoder's defaults, this module rejects every
construct whose serialization is ambiguous. Each rejection below corresponds to
a hazard verified empirically against CPython 3.13:

    json.dumps(float('nan'))  ->  'NaN'      (not valid JSON; parsers disagree)
    json.dumps({2: 'b'})      ->  '{"2":"b"}' (int key silently coerced to str)
    True == 1 and hash alike  ->  bool/int collide as mapping keys
    'café' (NFC) != 'café' (NFD)            (same text, different bytes)
    default separators        ->  '{"a": 1}' (insignificant whitespace)
    ensure_ascii=True         ->  '\\u00e9'   (escaping changes the bytes)

Floats are rejected rather than rounded. A measurement that needs a fractional
value carries it as an integer in a fixed unit (e.g. `duration_ms`) or as a
decimal string, so that no binary rounding ever enters an integrity digest.
"""

from __future__ import annotations

import json
import math
import unicodedata
from typing import Any

__all__ = [
    "MAX_NESTING_DEPTH",
    "CanonicalizationError",
    "canonical_json",
    "canonicalize",
    "normalize_text",
]


# A deeply nested structure is not a legitimate event; the bound also stops a
# malformed payload from exhausting the stack during verification.
MAX_NESTING_DEPTH = 32


class CanonicalizationError(ValueError):
    """Raised when a value has no unambiguous canonical representation.

    This is deliberately a hard failure. Silently coercing an ambiguous value
    would produce bytes that another implementation could not reproduce, which
    is precisely the failure mode canonicalization exists to prevent.
    """


def normalize_text(text: str) -> str:
    """Normalize a string to Unicode NFC.

    Composed and decomposed spellings of the same text compare unequal in
    Python and hash differently. Paths are the acute case: an agent on one
    platform may emit a decomposed filename while another emits the composed
    form of the same file. Normalizing at the boundary makes the digest depend
    on the text rather than on its encoding.
    """
    return unicodedata.normalize("NFC", text)


def _canonicalize_value(value: Any, depth: int, path: str) -> Any:
    """Recursively convert a value into its canonical form.

    `path` names the offending location so a rejection is actionable rather
    than a bare type error from somewhere inside a nested payload.
    """
    if depth > MAX_NESTING_DEPTH:
        raise CanonicalizationError(
            f"at {path}: nesting exceeds {MAX_NESTING_DEPTH} levels; "
            "events must be shallow enough to verify without deep recursion"
        )

    # Order matters: bool is a subclass of int, so it must be tested first or
    # True would be canonicalized as the integer 1.
    if value is None or isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        # Rejected even when finite: 0.1 has no exact binary representation, so
        # its shortest-repr text can differ across implementations. Integrity
        # digests must not depend on floating-point formatting.
        detail = "NaN" if math.isnan(value) else "infinite" if math.isinf(value) else "finite"
        raise CanonicalizationError(
            f"at {path}: float ({detail}) has no canonical form. Use an integer "
            "in a fixed unit (e.g. duration_ms) or a decimal string instead."
        )

    if isinstance(value, str):
        return normalize_text(value)

    if isinstance(value, bytes):
        raise CanonicalizationError(
            f"at {path}: raw bytes have no canonical JSON form. "
            "Encode as a hex or base64 string at the call site."
        )

    if isinstance(value, (list, tuple)):
        # Sequence order is meaningful and is preserved exactly.
        return [_canonicalize_value(v, depth + 1, f"{path}[{i}]") for i, v in enumerate(value)]

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            # Non-string keys would be coerced by the encoder, letting 2 and
            # "2" collide into one entry. Reject instead.
            if not isinstance(key, str) or isinstance(key, bool):
                raise CanonicalizationError(
                    f"at {path}: mapping key {key!r} is {type(key).__name__}, not str. "
                    "Non-string keys are silently coerced by JSON encoders and would collide."
                )
            normalized_key = normalize_text(key)
            if normalized_key in result:
                # Two distinct spellings normalized to the same key; keeping
                # either one would discard data without telling anyone.
                raise CanonicalizationError(
                    f"at {path}: keys collide after Unicode NFC normalization: {normalized_key!r}"
                )
            result[normalized_key] = _canonicalize_value(item, depth + 1, f"{path}.{normalized_key}")
        return result

    raise CanonicalizationError(
        f"at {path}: value of type {type(value).__name__} has no canonical form. "
        "Convert it to a str, int, bool, None, list or dict first."
    )


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text for a value.

    Keys are sorted by Unicode code point, no insignificant whitespace is
    emitted, and non-ASCII characters are written literally as UTF-8 rather
    than escaped.
    """
    prepared = _canonicalize_value(value, depth=0, path="$")
    return json.dumps(
        prepared,
        sort_keys=True,           # order independent of dict insertion order
        ensure_ascii=False,       # emit real UTF-8, not \uXXXX escapes
        separators=(",", ":"),    # no insignificant whitespace
        allow_nan=False,          # belt-and-braces; floats already rejected
        check_circular=True,
    )


def canonicalize(value: Any) -> bytes:
    """Return the canonical UTF-8 bytes for a value.

    This is the function the hash chain and every signature consume. It is the
    single definition of "what these bytes are" for the whole system.
    """
    return canonical_json(value).encode("utf-8")
