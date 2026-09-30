"""Install a BUILT wheel into a fresh virtualenv and prove the installed package works.

    python scripts/smoke_wheel.py dist/causalmesh-0.1.0-py3-none-any.whl
    python scripts/smoke_wheel.py dist/*.whl --examples examples/cli_demo

Why this exists: the test suite runs against the source tree (`pythonpath = src`),
so it cannot notice a file the wheel forgot to ship, an import that only works
because the repository is next to it, or a console script that does not start.
This runs the wheel the way a person who typed `pip install causalmesh` would,
in a scratch directory that contains nothing of the repository.

What it checks, in order:

1. base install (no extras): `causalmesh --version`, `python -m causalmesh`,
   `import causalmesh.sdk`, that the package really came from site-packages, that
   the typing marker shipped, and `doctor`, `init`, `policy validate|show|check`
   and `quickstart` in an empty directory;
2. that `causalmesh serve` without the `server` extra fails with a message that
   names the extra, rather than a traceback;
3. `[server]` install: `causalmesh.server` imports, and a copy of
   `examples/cli_demo` (copied out of the tree, so nothing leaks into sys.path)
   runs to completion.

It needs network access to the package index for the dependencies, and nothing
else. It never uploads anything. Output is ASCII (AGENTS.md); the exit code is 0
only if every check held.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

results: list[tuple[bool, str]] = []


def record(ok: bool, label: str, detail: str = "") -> bool:
    results.append((ok, label))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok and detail:
        for line in detail.strip().splitlines()[-12:]:
            print("         " + line.encode("ascii", "replace").decode("ascii"))
    return ok


def run(argv: list[str], *, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    # A clean environment: no PYTHONPATH, no editable install of the repository.
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env.pop("CAUSALMESH_API_TOKEN", None)
    return subprocess.run(  # noqa: S603
        argv, cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout, encoding="utf-8"
    )


def venv_python(env_dir: Path) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def venv_script(env_dir: Path, name: str) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / f"{name}.exe"
    return env_dir / "bin" / name


def pip_install(py: Path, spec: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return run([str(py), "-m", "pip", "install", "--quiet", spec], cwd=cwd, timeout=900)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("wheel", type=Path, help="the built .whl to install")
    parser.add_argument(
        "--examples",
        type=Path,
        default=ROOT / "examples" / "cli_demo",
        help="the example directory to copy out and run (default: examples/cli_demo)",
    )
    parser.add_argument("--keep", action="store_true", help="keep the scratch directory")
    args = parser.parse_args()

    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        print(f"error: {args.wheel} is not a .whl file", file=sys.stderr)
        return 2
    if not wheel.name.endswith("-py3-none-any.whl"):
        print(f"  [FAIL] wheel {wheel.name} is not pure-Python py3-none-any")
        return 1

    scratch = Path(tempfile.mkdtemp(prefix="cm-smoke-"))
    try:
        print(f"python {sys.version.split()[0]} on {sys.platform}; wheel {wheel.name}")
        env_dir = scratch / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
        py = venv_python(env_dir)
        cli_exe = venv_script(env_dir, "causalmesh")
        work = scratch / "empty"
        work.mkdir()

        print("1. base install (no extras)")
        done = pip_install(py, str(wheel), work)
        if not record(done.returncode == 0, "pip install <wheel>", done.stderr):
            return 1

        version = run([str(py), "-c", "import causalmesh; print(causalmesh.__version__)"], cwd=work)
        expected = version.stdout.strip()
        record(bool(expected), f"import causalmesh (version {expected})", version.stderr)

        cli = str(cli_exe)
        try:
            done = run([cli, "--version"], cwd=work)
        except OSError as exc:
            # Windows Application Control (Smart App Control / WDAC) can refuse to
            # start a freshly generated, unsigned console-script launcher. That is
            # the machine's policy, not the package: say so and use the module form
            # for the remaining steps so they still exercise the installed wheel.
            print(f"  [NOTE] the console script could not be launched here: {exc}")
            print("         using `python -m causalmesh` for the remaining steps")
            cli = ""
            done = run([str(py), "-m", "causalmesh", "--version"], cwd=work)

        def causalmesh(*rest: str) -> list[str]:
            return [cli, *rest] if cli else [str(py), "-m", "causalmesh", *rest]

        record(
            done.returncode == 0 and done.stdout.strip() == f"causalmesh {expected}",
            "causalmesh --version matches the package",
            done.stdout + done.stderr,
        )
        done = run([str(py), "-m", "causalmesh", "--version"], cwd=work)
        record(
            done.returncode == 0 and expected in done.stdout,
            "python -m causalmesh --version",
            done.stdout + done.stderr,
        )

        code = (
            "import causalmesh, causalmesh.sdk, pathlib; "
            "p = pathlib.Path(causalmesh.__file__).parent; "
            "print('site-packages' in p.parts, (p / 'py.typed').is_file())"
        )
        done = run([str(py), "-c", code], cwd=work)
        record(
            done.stdout.split() == ["True", "True"],
            "imported from site-packages, py.typed shipped, causalmesh.sdk imports",
            done.stdout + done.stderr,
        )

        done = run(causalmesh("doctor"), cwd=work)
        record(
            "Python" in done.stdout and "Traceback" not in done.stderr,
            "causalmesh doctor runs in an empty directory",
            done.stdout + done.stderr,
        )
        done = run(causalmesh("init"), cwd=work)
        record(
            done.returncode == 0 and (work / "causalmesh.yaml").is_file(),
            "causalmesh init writes causalmesh.yaml",
            done.stdout + done.stderr,
        )
        done = run(causalmesh("policy", "validate"), cwd=work)
        record(done.returncode == 0, "causalmesh policy validate", done.stdout + done.stderr)
        done = run(causalmesh("policy", "show"), cwd=work)
        record(done.returncode == 0, "causalmesh policy show", done.stdout + done.stderr)
        done = run(
            causalmesh("policy", "check", "--agent", "a", "--kind", "path", "--name", "x.txt"),
            cwd=work,
        )
        record(
            done.returncode in (0, 1) and "Traceback" not in done.stderr,
            f"causalmesh policy check answers (exit {done.returncode})",
            done.stdout + done.stderr,
        )

        # `quickstart` drives the experiment harness, which needs a repository
        # checkout (tasks/, fixtures/, configs/) that a wheel does not carry. The
        # requirement is that it says so and stops, not that it succeeds.
        qs = scratch / "quickstart"
        qs.mkdir()
        done = run(causalmesh("quickstart"), cwd=qs, timeout=600)
        text = done.stdout + done.stderr
        record(
            done.returncode == 1 and "checkout" in text and "Traceback" not in text,
            "causalmesh quickstart says it needs a checkout and stops cleanly",
            text,
        )
        for words in (("task", "validate"), ("experiment", "run", "--profile", "smoke")):
            done = run(causalmesh(*words), cwd=qs)
            text = done.stdout + done.stderr
            record(
                done.returncode != 0 and "Traceback" not in text,
                f"causalmesh {' '.join(words)} outside a checkout fails without a traceback",
                text,
            )

        print("2. a missing extra is named, not a traceback")
        done = run(causalmesh("serve"), cwd=work)
        text = done.stdout + done.stderr
        record(
            done.returncode != 0 and "causalmesh[server]" in text and "Traceback" not in text,
            "causalmesh serve without [server] says how to install it",
            text,
        )

        print("3. [server] install and the CLI demo, run outside the tree")
        done = pip_install(py, f"{wheel}[server]", work)
        if not record(done.returncode == 0, "pip install <wheel>[server]", done.stderr):
            return 1
        done = run(
            [str(py), "-c", "import causalmesh.server.app as a; print(a.create_app)"], cwd=work
        )
        record(done.returncode == 0, "causalmesh.server imports", done.stderr)

        demo = scratch / "cli_demo"
        if args.examples.is_dir():
            shutil.copytree(args.examples, demo, ignore=shutil.ignore_patterns("__pycache__"))
            done = run([str(py), "run_demo.py"], cwd=demo, timeout=600)
            record(
                done.returncode == 0 and "FAIL" not in done.stdout,
                "examples/cli_demo/run_demo.py against the installed wheel",
                done.stdout + done.stderr,
            )
        else:
            record(False, f"examples directory {args.examples} not found")
    finally:
        if args.keep:
            print(f"scratch kept at {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)

    failed = [label for ok, label in results if not ok]
    print(f"{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
