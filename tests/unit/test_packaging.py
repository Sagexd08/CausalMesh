"""The package's metadata says what the code is, and a wheel can carry it.

These check the facts a release depends on without building anything (the build
itself is `scripts/release_check.py` and `scripts/smoke_wheel.py`, which need
the network): that there is one version and it is written once, that the
metadata does not overclaim, and that the package still reads no data file the
wheel would not ship.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import causalmesh

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "causalmesh"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_version_is_written_once_and_read_from_the_package(pyproject: dict) -> None:
    project = pyproject["project"]
    assert "version" not in project
    assert "version" in project["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "causalmesh.__version__"
    }
    assert re.fullmatch(r"\d+\.\d+\.\d+([abrc.]\w*)?", causalmesh.__version__)


def test_no_other_source_file_hard_codes_the_version() -> None:
    literal = re.compile(f"""['"]{re.escape(causalmesh.__version__)}['"]""")
    offenders = [
        str(path.relative_to(ROOT))
        for path in SRC.rglob("*.py")
        if path != SRC / "__init__.py" and literal.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_metadata_does_not_overclaim(pyproject: dict) -> None:
    classifiers = pyproject["project"]["classifiers"]
    assert "Development Status :: 2 - Pre-Alpha" in classifiers
    assert not [c for c in classifiers if "Production" in c or "Stable" in c]
    assert "Typing :: Typed" in classifiers
    assert "Operating System :: OS Independent" in classifiers


def test_license_is_spdx_and_shipped(pyproject: dict) -> None:
    project = pyproject["project"]
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert not [c for c in project["classifiers"] if c.startswith("License ::")]
    assert (ROOT / "LICENSE").is_file()
    assert "setuptools>=77" in pyproject["build-system"]["requires"]


def test_urls_and_python_range(pyproject: dict) -> None:
    project = pyproject["project"]
    for name in ("Homepage", "Source", "Issues", "Changelog"):
        assert project["urls"][name].startswith("https://github.com/Sagexd08/CausalMesh")
    assert project["requires-python"] == ">=3.11"
    versions = {c.rsplit(" ", 1)[-1] for c in project["classifiers"] if "Python :: 3." in c}
    assert versions == {"3.11", "3.12", "3.13"}


def test_console_script_and_module_entry_point_agree(pyproject: dict) -> None:
    assert pyproject["project"]["scripts"]["causalmesh"] == "causalmesh.cli.main:app"
    assert (SRC / "__main__.py").is_file()
    assert (SRC / "py.typed").is_file()
    assert pyproject["tool"]["setuptools"]["package-data"]["causalmesh"] == ["py.typed"]


def test_the_package_reads_no_data_file_a_wheel_would_omit() -> None:
    """A non-Python file the code opens from its own directory must be package data.

    The wheel ships `py.typed` and nothing else that is not Python. If the code
    starts reading a template or a schema next to itself (via `__file__` or
    `importlib.resources`), it has to be added to `package-data` first, and this
    is where that gets noticed instead of on someone's machine.
    """
    allowed = {"cli/commands_doctor.py"}  # reads the package directory listing only
    reading = re.compile(r"importlib\.resources|importlib_resources|pkg_resources|__file__")
    offenders = [
        rel
        for path in SRC.rglob("*.py")
        if (rel := path.relative_to(SRC).as_posix()) not in allowed
        and reading.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    stray = [
        p.relative_to(SRC).as_posix()
        for p in SRC.rglob("*")
        if p.is_file()
        and p.suffix not in {".py", ".pyc"}
        and p.name not in {"py.typed", ".gitkeep"}
    ]
    assert stray == []


def test_sdist_keeps_fixtures_and_bulk_out() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    for directory in ("fixtures", "data", "videos", "frontend"):
        assert f"prune {directory}" in manifest


def test_dockerignore_keeps_the_build_context_small() -> None:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "*" in lines
    assert {"!pyproject.toml", "!src/"} <= set(lines)


def test_version_flag_prints_the_package_version() -> None:
    from typer.testing import CliRunner

    from causalmesh.cli.main import app

    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"causalmesh {causalmesh.__version__}"


def test_quickstart_outside_a_checkout_explains_and_stops(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from causalmesh.cli.main import app

    result = CliRunner().invoke(app, ["quickstart", "--root", str(tmp_path)])
    assert result.exit_code == 1
    assert "checkout" in result.output
    assert not (tmp_path / "causalmesh.yaml").exists()
