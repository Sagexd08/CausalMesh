from causalmesh.integrations.schema import tool_to_json_schema


def dummy_tool_no_types(a, b):
    pass


def dummy_tool_basic(a: str, b: int, c: bool, d: float):
    pass


def dummy_tool_complex(data: dict, items: list, e: str = "default"):
    pass


def dummy_tool_with_self(self, path: str):
    pass


def test_tool_to_json_schema_extracts_properties():
    schema = tool_to_json_schema("dummy", "desc", dummy_tool_basic)
    assert schema["type"] == "object"

    props = schema["properties"]
    assert props["a"]["type"] == "string"
    assert props["b"]["type"] == "integer"
    assert props["c"]["type"] == "boolean"
    assert props["d"]["type"] == "number"


def test_tool_to_json_schema_enforces_required_fields():
    schema = tool_to_json_schema("dummy", "desc", dummy_tool_complex)

    props = schema["properties"]
    assert props["data"]["type"] == "object"
    assert props["items"]["type"] == "array"
    assert props["e"]["type"] == "string"

    # a, data, items are required, 'e' is not because it has a default
    assert "data" in schema["required"]
    assert "items" in schema["required"]
    assert "e" not in schema["required"]


def test_tool_to_json_schema_falls_back_to_string_for_untyped():
    schema = tool_to_json_schema("dummy", "desc", dummy_tool_no_types)
    props = schema["properties"]
    assert props["a"]["type"] == "string"
    assert props["b"]["type"] == "string"
    assert "a" in schema["required"]
    assert "b" in schema["required"]


def test_tool_to_json_schema_ignores_self_parameter():
    schema = tool_to_json_schema("dummy", "desc", dummy_tool_with_self)
    props = schema["properties"]
    assert "self" not in props
    assert "path" in props
