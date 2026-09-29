"""The dependency floors, and why they are what they are.

Each floor was measured on 2026-09-30, and the numbers below are the evidence:

- `AUDITED_MINIMUMS`: the lowest release of each package with no advisory in
  pip-audit's data (found by auditing candidate versions in order). A floor
  below one of these admits a release with a known vulnerability.
- `FIRST_WHEEL_FOR_313`: the oldest release with a binary wheel for Python 3.13
  (found with `pip download --only-binary`). A floor below it makes
  `pip install causalmesh[analysis]` build from source on 3.13.

Changing a floor means re-running the audit, not editing a number: these tests
fail when a floor moves below the evidence, and the comments in `pyproject.toml`
say how to re-measure.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.version import Version

pytestmark = pytest.mark.unit

PYPROJECT = tomllib.loads(
    (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
)
CORE = [Requirement(r) for r in PYPROJECT["project"]["dependencies"]]
EXTRAS = {
    name: [Requirement(r) for r in reqs]
    for name, reqs in PYPROJECT["project"]["optional-dependencies"].items()
}

AUDITED_MINIMUMS = {
    "cryptography": "50.0",
    "click": "8.3.3",
    "starlette": "1.3.1",
    "pydantic": "2.4",
    "pyyaml": "6.0.2",
    "langchain-core": "1.3.3",
}
# The oldest release for which every CLI command runs with click 8.3.
WORKING_MINIMUMS = {"typer": "0.16", "fastapi": "0.133"}

FIRST_WHEEL_FOR_313 = {
    "numpy": "2.1",
    "scipy": "1.14.1",
    "pandas": "2.2.3",
    "statsmodels": "0.14.4",
    "matplotlib": "3.9.2",
}
# The oldest release with a wheel for 3.12 (and 3.11), where it differs from the old floor.
FIRST_WHEEL_FOR_312 = {"scipy": "1.11.2", "pandas": "2.1.1", "pyyaml": "6.0.1"}


def _floor(requirement: Requirement) -> Version | None:
    lowers = [Version(s.version) for s in requirement.specifier if s.operator in (">=", "==", "~=")]
    return max(lowers) if lowers else None


def _every_requirement() -> list[Requirement]:
    return CORE + [r for reqs in EXTRAS.values() for r in reqs]


def _applies(requirement: Requirement, python: str) -> bool:
    if requirement.marker is None:
        return True
    return Marker(str(requirement.marker)).evaluate({"python_version": python, "extra": ""})


def _floor_for(name: str, python: str) -> Version | None:
    floors = [
        _floor(r) for r in _every_requirement() if r.name.lower() == name and _applies(r, python)
    ]
    return max((f for f in floors if f is not None), default=None)


class TestEveryRuntimeDependencyHasAFloor:
    @pytest.mark.parametrize("requirement", CORE, ids=lambda r: r.name)
    def test_core(self, requirement: Requirement) -> None:
        assert _floor(requirement) is not None, f"{requirement.name} has no lower bound"

    @pytest.mark.parametrize("extra", ["analysis", "server", "langchain"])
    def test_the_extras_that_ship_are_floored(self, extra: str) -> None:
        for requirement in EXTRAS[extra]:
            assert _floor(requirement) is not None, (
                f"{extra}: {requirement.name} has no lower bound"
            )


class TestNoFloorAdmitsAKnownAdvisory:
    @pytest.mark.parametrize(("name", "minimum"), AUDITED_MINIMUMS.items())
    def test_the_floor_is_at_or_above_the_lowest_audited_release(
        self, name: str, minimum: str
    ) -> None:
        for python in ("3.11", "3.12", "3.13"):
            floor = _floor_for(name, python)
            assert floor is not None, f"{name} is not floored on Python {python}"
            assert floor >= Version(minimum), (
                f"{name}>={floor} admits releases below {minimum}, which have advisories"
            )

    @pytest.mark.parametrize(("name", "minimum"), WORKING_MINIMUMS.items())
    def test_the_floor_is_at_or_above_the_lowest_release_that_works(
        self, name: str, minimum: str
    ) -> None:
        floor = _floor_for(name, "3.12")
        assert floor is not None and floor >= Version(minimum)


class TestEveryFloorInstallsFromAWheelOnEverySupportedPython:
    def test_python_313_is_claimed(self) -> None:
        # If 3.13 stops being supported the wheel table below stops being needed.
        assert "Programming Language :: Python :: 3.13" in PYPROJECT["project"]["classifiers"]

    @pytest.mark.parametrize(("name", "first"), FIRST_WHEEL_FOR_313.items())
    def test_313(self, name: str, first: str) -> None:
        floor = _floor_for(name, "3.13")
        assert floor is not None and floor >= Version(first), (
            f"{name}>={floor} has no wheel for Python 3.13 (first is {first})"
        )

    @pytest.mark.parametrize(("name", "first"), FIRST_WHEEL_FOR_312.items())
    def test_312(self, name: str, first: str) -> None:
        for python in ("3.12", "3.13"):
            floor = _floor_for(name, python)
            assert floor is not None and floor >= Version(first), (
                f"{name}>={floor} has no wheel for Python {python} (first is {first})"
            )

    @pytest.mark.parametrize("name", sorted(FIRST_WHEEL_FOR_313))
    def test_each_analysis_package_is_split_by_python_version(self, name: str) -> None:
        # One unconditional floor cannot be right for both 3.11 and 3.13.
        markers = [str(r.marker) for r in EXTRAS["analysis"] if r.name.lower() == name and r.marker]
        assert len(markers) == 2, f"{name} needs one floor below 3.13 and one from 3.13"


class TestTheExtrasAreComplete:
    def test_the_server_extra_names_the_package_that_carries_the_advisories(self) -> None:
        assert "starlette" in {r.name.lower() for r in EXTRAS["server"]}

    def test_the_langchain_extra_exists_because_the_tests_need_it(self) -> None:
        assert [r.name for r in EXTRAS["langchain"]] == ["langchain-core"]

    def test_click_is_declared_directly_because_the_cli_depends_on_it(self) -> None:
        assert "click" in {r.name.lower() for r in CORE}
