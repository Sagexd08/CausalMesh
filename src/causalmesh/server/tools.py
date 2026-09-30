"""Load operator-written tool registrations into a server session.

`causalmesh serve --tools SPEC` imports code and runs it. That is the whole
feature, so it is stated plainly here and in `docs/security.md`:

- The spec is the **operator's**, typed on the command line (or set in the
  service definition that starts the process). It is never taken from the
  contract, from a request, from a header, or from anything a client sends.
  The `tools:` section of `causalmesh.yaml` names tools; it does not name
  code, and nothing here reads it as an import.
- The code runs with the server's own privileges, at startup, before the
  first request. Anyone who can change the spec or the file it points at can
  run code as the server, exactly as anyone who can edit the service's
  command line can. Treat it like any other code you deploy.
- Every tool it registers is still called through the gateway: the contract
  gate decides, and the evidence is recorded. Loading a tool grants nothing.

Two spec forms:

    package.module:function     imported with `importlib.import_module`
    path/to/file.py:function    executed from that file, by path

`function(mesh)` is called once with the `CausalMesh` session and registers
tools with `mesh.register_tool(Tool(...))`.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import re
import sys
from pathlib import Path
from typing import Any

from causalmesh.sdk.mesh import CausalMesh

__all__ = ["ToolLoadError", "load_tools"]

_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_FUNC = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_EXAMPLE = "for example `my_tools:register` or `./my_tools.py:register`"


class ToolLoadError(ValueError):
    """A `--tools` spec could not be loaded. The message says what to fix."""


def _split(spec: str) -> tuple[str, str, bool]:
    """`(target, function, is_file)` for a spec, or raise `ToolLoadError`.

    The split is on the *last* colon so a Windows drive letter
    (`C:\\ops\\tools.py:register`) stays part of the path.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise ToolLoadError(f"--tools needs MODULE:FUNC or FILE.py:FUNC, {_EXAMPLE}")
    target, sep, func = spec.strip().rpartition(":")
    if not sep or not target or not func:
        raise ToolLoadError(
            f"--tools {spec!r} must look like MODULE:FUNC or FILE.py:FUNC, {_EXAMPLE}"
        )
    if not _FUNC.fullmatch(func):
        raise ToolLoadError(f"--tools {spec!r}: {func!r} is not a valid function name")
    is_file = target.endswith(".py") or "/" in target or "\\" in target
    if not is_file and not _MODULE.fullmatch(target):
        raise ToolLoadError(
            f"--tools {spec!r}: {target!r} is neither a dotted module name nor a path to a .py file"
        )
    return target, func, is_file


def _import_file(target: str, index: int) -> Any:
    path = Path(target).expanduser()
    if not path.is_file():
        raise ToolLoadError(f"--tools: no such file: {path}")
    if path.suffix != ".py":
        raise ToolLoadError(f"--tools: {path} is not a .py file")
    # A unique, private module name: two files called tools.py must not shadow
    # each other, and neither may shadow a real module.
    name = f"_causalmesh_operator_tools_{index}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ToolLoadError(f"--tools: cannot load {path} as a Python module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def load_tools(mesh: CausalMesh, spec: str, *, index: int = 0) -> list[str]:
    """Import the code `spec` names, call `function(mesh)`, return the names it added.

    Raises `ToolLoadError` for a malformed spec, a module or file that cannot
    be imported, a missing or non-callable function, a function that raises,
    a function that registers nothing, and a tool name registered twice. The
    operator's own exception text is included: it is the operator's terminal,
    and "the import failed" without the reason is not something to act on.
    """
    target, func_name, is_file = _split(spec)

    try:
        module = _import_file(target, index) if is_file else importlib.import_module(target)
    except ToolLoadError:
        raise
    except ModuleNotFoundError as exc:
        hint = (
            " (a module is found on PYTHONPATH, not in the current directory; "
            "use FILE.py:FUNC for a file)"
            if not is_file
            else ""
        )
        raise ToolLoadError(f"--tools {spec!r}: cannot import: {exc}{hint}") from exc
    except Exception as exc:  # noqa: BLE001 - operator code may raise anything at import
        raise ToolLoadError(
            f"--tools {spec!r}: importing raised {type(exc).__name__}: {exc}"
        ) from exc

    func = getattr(module, func_name, None)
    if func is None:
        raise ToolLoadError(f"--tools {spec!r}: {target} has no attribute {func_name!r}")
    if not callable(func):
        raise ToolLoadError(f"--tools {spec!r}: {func_name!r} is not callable")
    if inspect.iscoroutinefunction(func):
        raise ToolLoadError(f"--tools {spec!r}: {func_name!r} must be a plain function, not async")
    try:
        inspect.signature(func).bind(mesh)
    except TypeError:
        raise ToolLoadError(
            f"--tools {spec!r}: {func_name!r} must accept one argument, the CausalMesh session"
        ) from None
    except ValueError:  # a builtin with no signature: let the call decide
        pass

    before = {name: mesh.get_tool(name) for name in mesh.registered_tools()}
    try:
        func(mesh)
    except Exception as exc:  # noqa: BLE001 - operator code may raise anything
        raise ToolLoadError(
            f"--tools {spec!r}: {func_name}() raised {type(exc).__name__}: {exc}"
        ) from exc

    after = mesh.registered_tools()
    replaced = sorted(name for name, tool in before.items() if mesh.get_tool(name) is not tool)
    if replaced:
        raise ToolLoadError(
            f"--tools {spec!r}: {func_name}() re-registered tool(s) already registered: "
            f"{', '.join(replaced)}"
        )
    added = [name for name in after if name not in before]
    if not added:
        raise ToolLoadError(
            f"--tools {spec!r}: {func_name}() registered no tools; "
            "call mesh.register_tool(Tool(...)) inside it"
        )
    return added
