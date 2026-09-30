"""The helpers every framework adapter shares: schema derivation and argument binding."""

from __future__ import annotations

import inspect
from typing import Literal, Optional

import pytest

from causalmesh.integrations import BaseFrameworkAdapter, tool_to_json_schema

pytestmark = pytest.mark.unit


def _props(handler) -> dict:
    return tool_to_json_schema("t", "d", handler)["properties"]


def test_optional_and_union_with_none_describe_the_inner_type() -> None:
    def handler(a: int | None = None, c: float | None = None):
        pass

    def legacy(b: Optional[str] = None):  # noqa: UP007, UP045
        pass

    assert _props(handler) == {"a": {"type": "integer"}, "c": {"type": "number"}}
    assert _props(legacy) == {"b": {"type": "string"}}


def test_literal_becomes_an_enum_of_its_type() -> None:
    def handler(mode: Literal["r", "w"], level: Literal[1, 2]):
        pass

    assert _props(handler) == {
        "mode": {"type": "string", "enum": ["r", "w"]},
        "level": {"type": "integer", "enum": [1, 2]},
    }


def test_a_mixed_literal_falls_back_to_a_string() -> None:
    def handler(x: Literal[1, "a"]):
        pass

    assert _props(handler) == {"x": {"type": "string"}}


def test_arrays_describe_their_items_only_when_the_item_type_is_known() -> None:
    def handler(a: list[int], b: list, c: list[object], d: tuple[str], e: set[float]):
        pass

    props = _props(handler)
    assert props["a"] == {"type": "array", "items": {"type": "integer"}}
    assert props["b"] == {"type": "array"}
    assert props["c"] == {"type": "array"}
    assert props["d"] == {"type": "array", "items": {"type": "string"}}
    assert props["e"] == {"type": "array", "items": {"type": "number"}}


def test_dict_generics_are_objects() -> None:
    def handler(a: dict[str, int], b: dict):
        pass

    assert _props(handler) == {"a": {"type": "object"}, "b": {"type": "object"}}


def test_var_positional_and_var_keyword_are_not_offered_to_the_model() -> None:
    def handler(path: str, *rest: int, **extra: str):
        pass

    schema = tool_to_json_schema("t", "d", handler)
    assert list(schema["properties"]) == ["path"]
    assert schema["required"] == ["path"]


def test_an_unresolvable_annotation_keeps_every_parameter_as_a_string() -> None:
    # `get_type_hints` raises NameError here. Losing the whole schema would drop
    # a required argument from what the model is told.
    def handler(path: Undefined, count: AlsoUndefined = 1):  # type: ignore[name-defined]  # noqa: F821
        pass

    schema = tool_to_json_schema("t", "d", handler)

    assert schema["properties"] == {"path": {"type": "string"}, "count": {"type": "string"}}
    assert schema["required"] == ["path"]


def _sig(handler) -> inspect.Signature:
    return inspect.signature(handler)


def test_bind_arguments_applies_defaults_so_the_gate_sees_what_the_handler_gets() -> None:
    def handler(path: str, content: str = "x"):
        pass

    bound = BaseFrameworkAdapter.bind_arguments(_sig(handler), ("a",), {})

    assert bound == {"path": "a", "content": "x"}


def test_bind_arguments_flattens_var_keyword() -> None:
    def handler(path: str, **extra):
        pass

    bound = BaseFrameworkAdapter.bind_arguments(_sig(handler), (), {"path": "a", "k": 1})

    assert bound == {"path": "a", "k": 1}


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [((), {}), ((), {"path": "a", "nope": 1}), (("a", "b"), {})],
    ids=["missing", "unexpected", "too-many-positional"],
)
def test_bind_arguments_returns_a_message_for_a_call_that_cannot_bind(args, kwargs) -> None:
    def handler(path: str):
        pass

    bound = BaseFrameworkAdapter.bind_arguments(_sig(handler), args, kwargs)

    assert isinstance(bound, str)
    assert bound.startswith("Action failed: Invalid arguments")


def test_bind_arguments_refuses_extra_positionals_for_a_star_args_handler() -> None:
    def handler(path: str, *rest):
        pass

    bound = BaseFrameworkAdapter.bind_arguments(_sig(handler), ("a", "b"), {})

    assert isinstance(bound, str)
    assert "positional" in bound
