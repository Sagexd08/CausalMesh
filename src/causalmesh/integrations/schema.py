import inspect
import types
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

_SCALARS: dict[Any, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
}
_ARRAYS = (list, tuple, set, frozenset)


def _unwrap_optional(hint: Any) -> Any:
    """``X | None`` and ``Optional[X]`` describe X to a model; ``None`` is omission."""
    if get_origin(hint) in (Union, types.UnionType):
        members = [arg for arg in get_args(hint) if arg is not type(None)]
        if len(members) == 1:
            return members[0]
    return hint


def _describe(hint: Any) -> dict[str, Any] | None:
    """The JSON Schema fragment for one annotation, or ``None`` when it is not known."""
    hint = _unwrap_optional(hint)
    origin = get_origin(hint) or hint
    if origin is Literal:
        values = list(get_args(hint))
        kinds = {_SCALARS.get(type(value)) for value in values}
        if len(kinds) == 1 and None not in kinds:
            return {"type": kinds.pop(), "enum": values}
        return None
    if origin in _SCALARS:
        return {"type": _SCALARS[origin]}
    if origin is dict:
        return {"type": "object"}
    if origin in _ARRAYS:
        fragment: dict[str, Any] = {"type": "array"}
        args = get_args(hint)
        item = _describe(args[0]) if len(args) == 1 else None
        if item is not None:
            fragment["items"] = item
        return fragment
    return None


def tool_to_json_schema(name: str, description: str, handler: Any) -> dict[str, Any]:
    """Extracts a JSON Schema (OpenAI ``parameters``, Anthropic ``input_schema``) from a handler.

    This function relies solely on the standard library `inspect` module and
    Python type hints. It intentionally avoids dependencies on frameworks like Pydantic.

    ``*args`` and ``**kwargs`` are left out: a model cannot supply them by name,
    and listing them would invite a call the handler cannot bind. An annotation
    that cannot be resolved falls back to a string property, so a required
    parameter is never silently dropped from the schema.
    """
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):
        # Fallback for builtins or callables lacking an inspectable signature
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }
    try:
        hints = get_type_hints(handler)
    except (TypeError, ValueError, NameError):
        hints = {}

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        described = _describe(hints[param_name]) if param_name in hints else None
        properties[param_name] = described or {"type": "string"}  # Default fallback

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
