import inspect
from typing import Any, get_type_hints


def tool_to_json_schema(name: str, description: str, handler: Any) -> dict[str, Any]:
    """Extracts an OpenAI-compatible JSON Schema from a tool handler's signature.

    This function relies solely on the standard library `inspect` module and
    Python type hints. It intentionally avoids dependencies on frameworks like Pydantic.
    """
    try:
        sig = inspect.signature(handler)
        hints = get_type_hints(handler)
    except (TypeError, ValueError):
        # Fallback for builtins or callables lacking an inspectable signature
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        param_type = "string"  # Default fallback
        if param_name in hints:
            hint = hints[param_name]
            if hint is int:
                param_type = "integer"
            elif hint is bool:
                param_type = "boolean"
            elif hint is float:
                param_type = "number"
            elif hint is dict or getattr(hint, "__origin__", None) is dict:
                param_type = "object"
            elif hint is list or getattr(hint, "__origin__", None) is list:
                param_type = "array"

        properties[param_name] = {"type": param_type}

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
