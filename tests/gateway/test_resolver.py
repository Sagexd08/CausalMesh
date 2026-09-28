import pytest

from causalmesh.gateway.resolver import ResourceResolver
from causalmesh.gateway.tool import Tool
from causalmesh.sdk.errors import MissingResourceError


def test_resolver_no_resources_returns_empty():
    tool = Tool(name="no_res", handler=lambda: None)
    resolver = ResourceResolver()
    assert resolver.resolve(tool, {"a": 1}) == ()


def test_resolver_single_resource_resolves():
    tool = Tool(name="read", handler=lambda: None, resource_args=["path"])
    resolver = ResourceResolver()
    assert resolver.resolve(tool, {"path": "file.txt", "extra": 42}) == ("file.txt",)


def test_resolver_multiple_resources_resolves():
    tool = Tool(name="copy", handler=lambda: None, resource_args=["source", "dest"])
    resolver = ResourceResolver()
    assert resolver.resolve(tool, {"source": "a", "dest": "b"}) == ("a", "b")


def test_resolver_missing_resource_raises():
    tool = Tool(name="read", handler=lambda: None, resource_args=["path"])
    resolver = ResourceResolver()
    with pytest.raises(MissingResourceError, match="requires resource argument 'path'"):
        resolver.resolve(tool, {"extra": 42})


def test_resolver_converts_to_string():
    tool = Tool(name="read", handler=lambda: None, resource_args=["path"])
    resolver = ResourceResolver()
    # A path argument passed as an int or Path object should be stringified
    assert resolver.resolve(tool, {"path": 123}) == ("123",)
