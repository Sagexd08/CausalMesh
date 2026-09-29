"""Tests for ResourceResolver.

Coverage targets
----------------
Happy-path explicit declaration
    • single resource_args entry
    • multiple resource_args entries
    • argument value is an integer (stringified)
    • argument value is a Path object (stringified)
    • argument value is None — recorded as the string "None"
    • duplicate resource_args names — each is extracted independently

Fail-closed behaviour
    • declared resource absent → MissingResourceError (never silently passes)
    • first declared resource absent → raises before processing later entries
    • empty string resource value is extracted as "" (not skipped)

Deprecated fallback (regression guard)
    • no resource_args but "path" present → single-element tuple + DeprecationWarning
    • no resource_args and no "path" → empty tuple, no warning
    • no resource_args and "path" is None → empty tuple, no warning

Adversarial inputs (resource extraction is value-agnostic — the gate
decides whether the path is allowed, not the resolver)
    • traversal string  "../secret"   is extracted without modification
    • absolute path     "/etc/passwd" is extracted without modification
    • empty string      ""            is extracted without modification
    • argument name changes at runtime (structural contract held via resource_args)
    • missing resource_args key after partial match → MissingResourceError
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from causalmesh.gateway.resolver import ResourceResolver
from causalmesh.gateway.tool import Tool
from causalmesh.sdk.errors import InvalidResourceError, MissingResourceError

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool(name: str = "t", *, resource_args: list[str] | None = None) -> Tool:
    kwargs: dict = {"name": name, "handler": lambda: None}
    if resource_args is not None:
        kwargs["resource_args"] = resource_args
    return Tool(**kwargs)


def _resolve(tool: Tool, arguments: dict) -> tuple[str, ...]:
    return ResourceResolver().resolve(tool, arguments)


# ---------------------------------------------------------------------------
# Happy-path: explicit resource_args
# ---------------------------------------------------------------------------


class TestExplicitResourceArgs:
    def test_single_resource(self) -> None:
        tool = _tool(resource_args=["path"])
        assert _resolve(tool, {"path": "src/main.py"}) == ("src/main.py",)

    def test_multiple_resources(self) -> None:
        tool = _tool(resource_args=["source", "dest"])
        assert _resolve(tool, {"source": "a.py", "dest": "b.py"}) == ("a.py", "b.py")

    def test_extra_arguments_ignored(self) -> None:
        tool = _tool(resource_args=["path"])
        assert _resolve(tool, {"path": "file.txt", "content": "data"}) == ("file.txt",)

    @pytest.mark.parametrize("value", [123, 1.5, True, None, b"a/b", ["a", "b"], ("a",), {"a": 1}])
    def test_a_value_that_is_not_text_is_refused(self, value: object) -> None:
        """The handler receives the raw object; the gate would have seen `str(value)`.

        These were once stringified ("123", "None", the repr of a list). A list
        of two paths was then checked as one odd string while the handler
        wrote both, so the gate decided about a resource the handler never
        touched. A resource argument has to be text, or nothing is decided.
        """
        tool = _tool(resource_args=["path"])
        with pytest.raises(InvalidResourceError, match="must be a str or a path"):
            _resolve(tool, {"path": value})

    def test_path_object_stringified(self) -> None:
        tool = _tool(resource_args=["path"])
        result = _resolve(tool, {"path": Path("src") / "main.py"})
        assert result == (str(Path("src") / "main.py"),)

    @pytest.mark.parametrize("value", ["", "   ", "\t\n"])
    def test_an_empty_or_blank_path_is_refused_with_a_typed_error(self, value: str) -> None:
        # It used to reach the gate and raise a bare ResourceError from inside it.
        tool = _tool(resource_args=["path"])
        with pytest.raises(InvalidResourceError, match="is empty"):
            _resolve(tool, {"path": value})

    def test_a_path_containing_nul_is_refused(self) -> None:
        tool = _tool(resource_args=["path"])
        with pytest.raises(InvalidResourceError, match="NUL"):
            _resolve(tool, {"path": "allowed/x\x00/../forbidden/y"})

    def test_duplicate_resource_args_extracted_twice(self) -> None:
        """Duplicate entries in resource_args are unusual but must not silently collapse."""
        tool = _tool(resource_args=["path", "path"])
        assert _resolve(tool, {"path": "f.py"}) == ("f.py", "f.py")

    def test_ordering_matches_resource_args_order(self) -> None:
        tool = _tool(resource_args=["dest", "source"])
        assert _resolve(tool, {"source": "s", "dest": "d"}) == ("d", "s")


# ---------------------------------------------------------------------------
# Fail-closed: explicit resource absent → MissingResourceError
# ---------------------------------------------------------------------------


class TestMissingResourceFailsClosed:
    def test_single_missing_resource_raises(self) -> None:
        tool = _tool(resource_args=["path"])
        with pytest.raises(MissingResourceError, match="'path'"):
            _resolve(tool, {})

    def test_missing_resource_raises_with_key_in_message(self) -> None:
        tool = _tool(resource_args=["path"])
        with pytest.raises(MissingResourceError, match="path"):
            _resolve(tool, {"content": "data"})

    def test_error_message_lists_tool_name(self) -> None:
        tool = _tool(name="write_file", resource_args=["path"])
        with pytest.raises(MissingResourceError, match="write_file"):
            _resolve(tool, {})

    def test_first_missing_raises_before_processing_second(self) -> None:
        tool = _tool(resource_args=["source", "dest"])
        with pytest.raises(MissingResourceError, match="'source'"):
            _resolve(tool, {"dest": "b.py"})  # source missing

    def test_partial_match_raises_for_second_missing(self) -> None:
        tool = _tool(resource_args=["source", "dest"])
        with pytest.raises(MissingResourceError, match="'dest'"):
            _resolve(tool, {"source": "a.py"})  # dest missing

    def test_completely_empty_arguments_raises(self) -> None:
        tool = _tool(resource_args=["path"])
        with pytest.raises(MissingResourceError):
            _resolve(tool, {})

    def test_argument_name_change_raises(self) -> None:
        """Renaming the argument in the call without updating resource_args fails closed."""
        tool = _tool(resource_args=["path"])
        with pytest.raises(MissingResourceError):
            _resolve(tool, {"filepath": "src/main.py"})  # wrong name


# ---------------------------------------------------------------------------
# Adversarial inputs: resolver extracts; gate decides
# ---------------------------------------------------------------------------


class TestAdversarialInputs:
    def test_path_traversal_string_extracted(self) -> None:
        """'../secret' must be extracted and presented to the gate, not silently blocked."""
        tool = _tool(resource_args=["path"])
        assert _resolve(tool, {"path": "../secret"}) == ("../secret",)

    def test_absolute_path_extracted(self) -> None:
        tool = _tool(resource_args=["path"])
        assert _resolve(tool, {"path": "/etc/passwd"}) == ("/etc/passwd",)

    def test_windows_absolute_path_extracted(self) -> None:
        tool = _tool(resource_args=["path"])
        assert _resolve(tool, {"path": r"C:\Windows\system32"}) == (r"C:\Windows\system32",)

    def test_deep_traversal_extracted(self) -> None:
        tool = _tool(resource_args=["path"])
        assert _resolve(tool, {"path": "../../../../etc/shadow"}) == ("../../../../etc/shadow",)

    def test_multiple_resources_one_adversarial(self) -> None:
        tool = _tool(resource_args=["source", "dest"])
        result = _resolve(tool, {"source": "../secret", "dest": "safe/output.txt"})
        assert result == ("../secret", "safe/output.txt")


# ---------------------------------------------------------------------------
# Deprecated fallback: no resource_args + "path" key
# ---------------------------------------------------------------------------


class TestDeprecatedPathFallback:
    """Regression guard: the fallback must keep working but must emit a warning."""

    def test_fallback_returns_path_value(self) -> None:
        tool = _tool()  # no resource_args
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _resolve(tool, {"path": "src/main.py"})
        assert result == ("src/main.py",)
        assert len(caught) == 1
        assert issubclass(caught[0].category, DeprecationWarning)

    def test_fallback_warning_mentions_tool_name(self) -> None:
        tool = _tool(name="legacy_writer")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _resolve(tool, {"path": "out.txt"})
        assert "legacy_writer" in str(caught[0].message)

    def test_fallback_warning_mentions_resource_args(self) -> None:
        tool = _tool(name="legacy_writer")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _resolve(tool, {"path": "out.txt"})
        assert "resource_args" in str(caught[0].message)

    def test_no_path_key_returns_empty_no_warning(self) -> None:
        tool = _tool()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _resolve(tool, {"content": "data"})
        assert result == ()
        assert len(caught) == 0

    def test_path_key_is_none_returns_empty_no_warning(self) -> None:
        """None path in fallback mode means no resource to check — no warning emitted."""
        tool = _tool()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _resolve(tool, {"path": None})
        assert result == ()
        assert len(caught) == 0

    def test_explicit_resource_args_suppresses_fallback(self) -> None:
        """Once resource_args is set the fallback is never reached."""
        tool = _tool(resource_args=["path"])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _resolve(tool, {"path": "f.txt"})
        assert result == ("f.txt",)
        assert len(caught) == 0
