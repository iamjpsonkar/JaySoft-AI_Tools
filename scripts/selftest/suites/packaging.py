"""
Phase L — the release gate.

Every other suite tests the editable checkout. This one tests the artifact
that would actually be published: build it, validate its metadata, inspect
what went into the wheel, then install it into a genuinely clean virtualenv
and drive the CLI and the MCP server from there. An editable install can
pass everything and still ship a broken wheel — a missing package-data glob
is invisible until someone pip-installs it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

from ..core import FAIL, PASS, REPO_ROOT, UNAVAILABLE, Check, Report, timed

DIST = REPO_ROOT / "dist"


def _run(cmd: list[str], timeout: int = 900,
         cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          cwd=str(cwd or REPO_ROOT))


@timed
def check_build() -> Check:
    try:
        import build  # noqa: F401
    except Exception:
        return Check("release_build", "release", UNAVAILABLE,
                     "the `build` package is not installed",
                     remediation="pip install build")
    if DIST.exists():
        shutil.rmtree(DIST)
    r = _run([sys.executable, "-m", "build"], timeout=900)
    if r.returncode != 0:
        return Check("release_build", "release", FAIL,
                     "python -m build failed",
                     detail=(r.stdout + r.stderr)[-800:])
    wheels = list(DIST.glob("*.whl"))
    sdists = list(DIST.glob("*.tar.gz"))
    if not wheels or not sdists:
        return Check("release_build", "release", FAIL,
                     f"build produced wheels={len(wheels)} sdists={len(sdists)}",
                     detail=r.stdout[-400:])
    return Check("release_build", "release", PASS,
                 f"built {wheels[0].name} and {sdists[0].name}")


@timed
def check_twine_metadata() -> Check:
    if not shutil.which("twine") and not _module_ok("twine"):
        return Check("release_twine_check", "release", UNAVAILABLE,
                     "twine is not installed", remediation="pip install twine")
    files = [str(p) for p in DIST.glob("*")] if DIST.exists() else []
    if not files:
        return Check("release_twine_check", "release", UNAVAILABLE,
                     "no dist/ artifacts to validate")
    r = _run([sys.executable, "-m", "twine", "check", *files], timeout=300)
    if r.returncode != 0 or "FAILED" in r.stdout:
        return Check("release_twine_check", "release", FAIL,
                     "twine check rejected the built artifacts",
                     detail=(r.stdout + r.stderr)[-600:])
    return Check("release_twine_check", "release", PASS,
                 "twine check passed on the wheel and sdist",
                 detail=r.stdout.strip()[-300:])


def _module_ok(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


@timed
def check_wheel_contents() -> Check:
    """The slash commands must be inside the wheel; tests must not be."""
    wheels = sorted(DIST.glob("*.whl")) if DIST.exists() else []
    if not wheels:
        return Check("release_wheel_contents", "release", UNAVAILABLE,
                     "no wheel to inspect")
    with zipfile.ZipFile(wheels[-1]) as z:
        names = z.namelist()
    commands = [n for n in names if "/commands/" in n and n.endswith(".md")]
    strays = [n for n in names
              if n.startswith(("tests/", "scripts/")) or "/tests/" in n]
    problems = []
    if not commands:
        problems.append("no jsat/commands/*.md files are in the wheel, so "
                        "`jsat connect claude` would install nothing")
    if strays:
        problems.append(f"{len(strays)} test/script file(s) leaked into the wheel")
    if problems:
        return Check("release_wheel_contents", "release", FAIL,
                     "; ".join(problems),
                     detail=f"commands={len(commands)} strays={strays[:5]}")
    return Check("release_wheel_contents", "release", PASS,
                 f"wheel contains {len(commands)} slash-command file(s) and no "
                 f"test/script strays ({len(names)} members total)")


@timed
def check_clean_venv_install() -> Check:
    """Install the wheel into a fresh venv and drive it for real.

    This is the only check that exercises the published artifact rather than
    the checkout: a non-editable install resolves package data, entry points
    and dependency pins the way a user's `pip install jsat` would.
    """
    wheels = sorted(DIST.glob("*.whl")) if DIST.exists() else []
    if not wheels:
        return Check("release_clean_install", "release", UNAVAILABLE,
                     "no wheel to install")
    work = Path(tempfile.mkdtemp(prefix="jsat-wheel-venv-"))
    try:
        venv.create(work / "venv", with_pip=True, clear=True)
        py = work / "venv" / "bin" / "python"
        if not py.exists():
            py = work / "venv" / "Scripts" / "python.exe"
        pip = _run([str(py), "-m", "pip", "install", "-q", str(wheels[-1])],
                   timeout=900)
        if pip.returncode != 0:
            return Check("release_clean_install", "release", FAIL,
                         "pip install of the built wheel failed in a clean venv",
                         detail=(pip.stdout + pip.stderr)[-700:])
        jsat_bin = py.parent / "jsat"
        if not jsat_bin.exists():
            return Check("release_clean_install", "release", FAIL,
                         "the wheel did not install a `jsat` console script",
                         detail=str(list(py.parent.iterdir()))[:400])

        ver = _run([str(jsat_bin), "version"], timeout=180)
        helped = _run([str(jsat_bin), "--help"], timeout=180)
        if ver.returncode != 0 or helped.returncode != 0:
            return Check("release_clean_install", "release", FAIL,
                         "the wheel-installed CLI could not run version/--help",
                         detail=f"version rc={ver.returncode} "
                                f"{ver.stderr[:250]} | help rc="
                                f"{helped.returncode} {helped.stderr[:250]}")

        # Package data: connect must find the shipped slash commands.
        import jsat as _local  # noqa: F401
        pkg = _run([str(py), "-c",
                    "import jsat, pathlib; "
                    "d = pathlib.Path(jsat.__file__).parent / 'commands'; "
                    "print(len(list(d.glob('jsat-*.md'))))"], timeout=120)
        n_cmds = pkg.stdout.strip()
        if not n_cmds.isdigit() or int(n_cmds) == 0:
            return Check("release_clean_install", "release", FAIL,
                         "the installed package has no jsat/commands/*.md, so "
                         "connecting an AI tool would install no skills",
                         detail=f"stdout={pkg.stdout[:200]} "
                                f"stderr={pkg.stderr[:200]}")

        # And it must serve MCP: a real index plus a real JSON-RPC handshake.
        repo = work / "wheel-repo"
        repo.mkdir()
        (repo / "app.py").write_text(
            "def add(a, b):\n    return a + b\n\n"
            "def main():\n    return add(1, 2)\n")
        env = {**os.environ,
               "JSAT_DATA_DIR": str(work / "data"),
               "JSAT_IMPROVE_DIR": str(work / "improve"),
               "JSAT_SESSIONS_DIR": str(work / "sessions"),
               "JSAT_MCP_ALLOW_INSECURE": "1"}
        idx = subprocess.run([str(jsat_bin), "index", str(repo)],
                             capture_output=True, text=True, timeout=300, env=env)
        if idx.returncode != 0:
            return Check("release_clean_install", "release", FAIL,
                         "the wheel-installed CLI could not index a repo",
                         detail=(idx.stdout + idx.stderr)[-500:])
        from ..core import MCPClient
        with MCPClient(str(jsat_bin), repo, env) as c:
            init = c.handshake()
            tools = c.call("tools/list")
        if init is None or "result" not in init:
            return Check("release_clean_install", "release", FAIL,
                         "the wheel-installed MCP server failed the initialize "
                         "handshake", detail=str(init)[:300])
        n_tools = len(tools["result"]["tools"]) if tools and "result" in tools else 0
        if n_tools == 0:
            return Check("release_clean_install", "release", FAIL,
                         "the wheel-installed MCP server registered no tools")
        return Check("release_clean_install", "release", PASS,
                     f"the built wheel installed clean into a fresh venv, ran "
                     f"the CLI, shipped {n_cmds} slash commands, indexed a repo "
                     f"and served {n_tools} MCP tools",
                     detail=ver.stdout.strip()[:200])
    finally:
        shutil.rmtree(work, ignore_errors=True)


@timed
def check_ruff() -> Check:
    r = _run([sys.executable, "-m", "ruff", "check", "jsat/", "tests/"],
             timeout=300)
    if r.returncode != 0:
        return Check("release_ruff", "release", FAIL,
                     "ruff check reported findings (CI runs this exact command)",
                     detail=(r.stdout + r.stderr)[-800:])
    return Check("release_ruff", "release", PASS,
                 "ruff check jsat/ tests/ is clean")


# Type-error baseline. `pyproject.toml` declares [tool.mypy] strict = true,
# but the codebase does not satisfy it and CI never runs mypy — so the count
# below is the honest current state, ratcheted so it can only go down. Lower
# it when you fix errors; never raise it to make a red run green.
MYPY_BASELINE = 377


def _mypy_run(extra: list[str]) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "-m", "mypy", "jsat/", *extra], timeout=900)


def _mypy_errors() -> tuple[list[str], str] | None:
    """Return (errors inside jsat/, note) or None if mypy could not run."""
    r = _mypy_run([])
    own = [ln for ln in r.stdout.splitlines() if ln.startswith("jsat/")
           and ": error:" in ln]
    if own or r.returncode == 0:
        return own, ""
    # mypy bailed before reaching jsat/. The usual cause is a third-party stub
    # using syntax newer than the declared python_version (numpy's stubs need
    # 3.12; pyproject targets 3.10 because that is the floor JSAT supports).
    # That is an environment artifact, not a JSAT defect, so retry at this
    # interpreter's version rather than reporting a false failure.
    blockers = [ln for ln in r.stdout.splitlines() if ": error:" in ln]
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    r2 = _mypy_run(["--python-version", ver])
    own2 = [ln for ln in r2.stdout.splitlines() if ln.startswith("jsat/")
            and ": error:" in ln]
    if not own2 and r2.returncode != 0:
        return None
    return own2, (f"the configured python_version could not parse a "
                  f"third-party stub ({blockers[0][:120] if blockers else '?'}), "
                  f"so mypy was re-run at --python-version {ver}")


@timed
def check_mypy_no_regression() -> Check:
    """Ratchet: the type-error count must never grow."""
    if not _module_ok("mypy"):
        return Check("release_mypy_ratchet", "release", UNAVAILABLE,
                     "mypy is not installed")
    result = _mypy_errors()
    if result is None:
        return Check("release_mypy_ratchet", "release", UNAVAILABLE,
                     "mypy could not analyse jsat/ in this environment",
                     remediation="a third-party stub is unparseable at the "
                                 "configured python_version")
    errors, note = result
    n = len(errors)
    files = len({ln.split(":", 1)[0] for ln in errors})
    if n > MYPY_BASELINE:
        return Check("release_mypy_ratchet", "release", FAIL,
                     f"type errors increased: {n} > baseline {MYPY_BASELINE}",
                     detail="\n".join(errors[-25:]),
                     remediation="fix the new errors, or justify raising "
                                 "MYPY_BASELINE in this file")
    summary = (f"no type-error regression: {n} error(s) in {files} file(s), "
               f"baseline {MYPY_BASELINE}")
    if n < MYPY_BASELINE:
        summary += f" — baseline can be lowered to {n}"
    if note:
        summary += f" ({note})"
    return Check("release_mypy_ratchet", "release", PASS, summary)


@timed
def check_mypy_strict_claim() -> Check:
    """`strict = true` must not be a claim the codebase cannot meet.

    Reported separately from the ratchet so the debt shows up exactly once,
    and a genuine regression is never confused with the standing gap.
    """
    import tomllib
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    strict = data.get("tool", {}).get("mypy", {}).get("strict", False)
    if not strict:
        return Check("release_mypy_strict_claim", "release", PASS,
                     "pyproject does not claim mypy strict, so there is no "
                     "gap between the declared and actual type discipline")
    if not _module_ok("mypy"):
        return Check("release_mypy_strict_claim", "release", UNAVAILABLE,
                     "mypy is not installed, cannot verify the strict claim")
    result = _mypy_errors()
    if result is None:
        return Check("release_mypy_strict_claim", "release", UNAVAILABLE,
                     "mypy could not analyse jsat/ in this environment")
    errors, _ = result
    if errors:
        files = len({ln.split(":", 1)[0] for ln in errors})
        kinds: dict[str, int] = {}
        for ln in errors:
            code = ln.rsplit("[", 1)[-1].rstrip("]") if "[" in ln else "other"
            kinds[code] = kinds.get(code, 0) + 1
        top = ", ".join(f"{k}={v}" for k, v in
                        sorted(kinds.items(), key=lambda kv: -kv[1])[:6])
        return Check("release_mypy_strict_claim", "release", FAIL,
                     f"[tool.mypy] strict = true is declared but jsat/ has "
                     f"{len(errors)} error(s) across {files} file(s), and CI "
                     "never runs mypy — the declaration is not enforced",
                     detail=f"by rule: {top}",
                     remediation="either add mypy to ci.yml and fix the "
                                 "errors, or scope the config honestly (e.g. "
                                 "strict per-module) so it reflects reality")
    return Check("release_mypy_strict_claim", "release", PASS,
                 "pyproject claims mypy strict and jsat/ satisfies it")


@timed
def check_docs_build() -> Check:
    if not _module_ok("mkdocs"):
        return Check("release_docs_build", "release", UNAVAILABLE,
                     "mkdocs is not installed",
                     remediation="pip install mkdocs-material")
    r = _run([sys.executable, "-m", "mkdocs", "build", "--strict",
              "--site-dir", str(Path(tempfile.mkdtemp()) / "site")],
             timeout=600)
    if r.returncode != 0:
        return Check("release_docs_build", "release", FAIL,
                     "mkdocs build --strict failed (docs.yml deploys this)",
                     detail=(r.stdout + r.stderr)[-800:])
    return Check("release_docs_build", "release", PASS,
                 "mkdocs build --strict succeeded")


def run(report: Report) -> None:
    report.add(check_ruff())
    report.add(check_build())
    report.add(check_twine_metadata())
    report.add(check_wheel_contents())
    report.add(check_clean_venv_install())
    report.add(check_docs_build())
    report.add(check_mypy_no_regression())
    report.add(check_mypy_strict_claim())
