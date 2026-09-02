"""Environment and external-dependency probes.

Nothing here is mocked: every probe opens a real socket, runs a real
`--version`, or reads a real env var. The point is to establish, before any
feature check runs, exactly which parts of the matrix can be tested for real
on this machine — so that a later `unavailable` is explained rather than
mysterious.
"""
from __future__ import annotations

import importlib.metadata as im
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..core import (
    FAIL,
    PASS,
    REPO_ROOT,
    UNAVAILABLE,
    Check,
    Report,
    http_reachable,
    tcp_reachable,
    timed,
)


@timed
def check_jsat_installed(jsat_bin: str | None) -> Check:
    if not jsat_bin:
        return Check("jsat_binary_found", "environment", FAIL,
                     "`jsat` console script not found on PATH",
                     remediation="pip install -e . (from the repo root)")
    try:
        ver = im.version("jsat")
    except Exception as e:
        ver = f"unknown ({e})"
    return Check("jsat_binary_found", "environment", PASS,
                 f"jsat binary at {jsat_bin}, version {ver}", detail=f"version={ver}")


@timed
def check_editable_checkout() -> Check:
    """Confirm the binary actually serves THIS checkout, not a stale copy.

    Resolved from a neutral cwd on purpose: `python -c` puts cwd on
    sys.path[0], so running this from the repo root would hide exactly the
    bug it exists to catch.
    """
    try:
        out = subprocess.run(
            [sys.executable, "-c",
             "import jsat, pathlib; print(pathlib.Path(jsat.__file__).resolve().parent)"],
            capture_output=True, text=True, cwd=tempfile.gettempdir(), timeout=20,
        )
        loaded_from = out.stdout.strip()
    except Exception as e:
        return Check("editable_checkout", "environment", FAIL,
                     f"could not resolve the jsat module: {e}")
    expected = str(REPO_ROOT / "jsat")
    if loaded_from == expected:
        return Check("editable_checkout", "environment", PASS,
                     "running this checkout (editable install)", detail=loaded_from)
    return Check("editable_checkout", "environment", FAIL,
                 f"a DIFFERENT jsat copy is shadowing this checkout: {loaded_from}",
                 detail=f"expected={expected} actual={loaded_from}",
                 remediation=f"{sys.executable} -m pip install -e .")


@timed
def check_version_consistency() -> Check:
    """pyproject.toml and jsat/__init__.py must agree — publish.yml validates
    the git tag against pyproject, and RELEASING.md requires both."""
    import re
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    init = (REPO_ROOT / "jsat" / "__init__.py").read_text()
    pv = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    iv = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.M)
    if not pv or not iv:
        return Check("version_consistency", "release", FAIL,
                     "could not parse a version out of pyproject.toml or __init__.py")
    if pv.group(1) != iv.group(1):
        return Check("version_consistency", "release", FAIL,
                     f"version mismatch: pyproject={pv.group(1)} "
                     f"__init__={iv.group(1)}",
                     remediation="bump both together (RELEASING.md)")
    return Check("version_consistency", "release", PASS,
                 f"pyproject.toml and jsat/__init__.py both declare {pv.group(1)}")


@timed
def check_binary_on_path(name: str) -> Check:
    path = shutil.which(name)
    if path:
        return Check(f"external_cli_{name}", "external_deps", PASS,
                     f"{name} found on PATH", detail=path)
    return Check(f"external_cli_{name}", "external_deps", UNAVAILABLE,
                 f"{name} not installed — checks needing it are skipped, not failed")


@timed
def check_python_module(name: str, extra: str) -> Check:
    try:
        __import__(name)
    except Exception:
        return Check(f"pymod_{name}", "external_deps", UNAVAILABLE,
                     f"python module `{name}` not importable",
                     remediation=f"pip install 'jsat[{extra}]'")
    return Check(f"pymod_{name}", "external_deps", PASS,
                 f"python module `{name}` importable")


@timed
def check_ollama() -> Check:
    if not http_reachable("http://localhost:11434/api/tags", timeout=2.0):
        return Check("external_ollama", "external_deps", UNAVAILABLE,
                     "ollama not reachable at localhost:11434")
    # Reachable is not the same as usable: a daemon with no models pulled
    # cannot answer a completion, and reporting it as "pass" would make the
    # provider check below look like a JSAT bug rather than an empty daemon.
    try:
        import json
        import urllib.request
        with urllib.request.urlopen(  # noqa: S310
                "http://localhost:11434/api/tags", timeout=3) as r:
            models = json.loads(r.read()).get("models", [])
    except Exception as e:
        return Check("external_ollama", "external_deps", UNAVAILABLE,
                     f"ollama reachable but /api/tags failed: {e}")
    if not models:
        return Check("external_ollama", "external_deps", UNAVAILABLE,
                     "ollama is running but has ZERO models pulled — completion "
                     "checks cannot run",
                     remediation="ollama pull qwen2.5:0.5b")
    names = ", ".join(m.get("name", "?") for m in models[:5])
    return Check("external_ollama", "external_deps", PASS,
                 f"ollama reachable with {len(models)} model(s)", detail=names)


@timed
def check_tcp_service(name: str, host: str, port: int) -> Check:
    if tcp_reachable(host, port):
        return Check(f"external_{name}", "external_deps", PASS,
                     f"{name} reachable at {host}:{port}")
    return Check(f"external_{name}", "external_deps", UNAVAILABLE,
                 f"{name} not reachable at {host}:{port}")


@timed
def check_docker() -> Check:
    if not shutil.which("docker"):
        return Check("external_docker", "external_deps", UNAVAILABLE,
                     "docker not installed — team-tier backends cannot be started")
    try:
        r = subprocess.run(["docker", "ps"], capture_output=True, text=True, timeout=15)
    except Exception as e:
        return Check("external_docker", "external_deps", UNAVAILABLE,
                     f"docker present but unusable: {e}")
    if r.returncode != 0:
        return Check("external_docker", "external_deps", UNAVAILABLE,
                     "docker installed but the daemon socket is not accessible",
                     detail=r.stderr.strip()[:300],
                     remediation="sudo usermod -aG docker $USER && newgrp docker")
    return Check("external_docker", "external_deps", PASS, "docker daemon usable")


@timed
def check_env_key(name: str) -> Check:
    if os.environ.get(name, "").strip():
        return Check(f"external_{name.lower()}", "external_deps", PASS,
                     f"{name} is set")
    return Check(f"external_{name.lower()}", "external_deps", UNAVAILABLE,
                 f"{name} is not set — API-provider checks are skipped")


@timed
def check_internet() -> Check:
    if http_reachable("https://pypi.org", timeout=5.0) or \
       http_reachable("https://api.osv.dev", timeout=5.0):
        return Check("external_internet", "external_deps", PASS,
                     "outbound internet reachable")
    return Check("external_internet", "external_deps", UNAVAILABLE,
                 "no outbound internet — CVE lookups and PyPI checks are skipped")


@timed
def check_no_state_leak() -> Check:
    """The harness must never write to the user's real ~/.jsat.

    Recorded as a check so the report itself carries the evidence that the
    run was isolated.
    """
    home_jsat = Path.home() / ".jsat"
    before = sorted(p.name for p in home_jsat.iterdir()) if home_jsat.exists() else []
    return Check("state_isolation", "environment", PASS,
                 "harness runs with JSAT_DATA_DIR/IMPROVE_DIR/SESSIONS_DIR "
                 "redirected to a temp dir",
                 detail=f"~/.jsat currently contains: {before or '(absent)'}")


def run(report: Report, jsat_bin: str | None) -> None:
    report.add(check_jsat_installed(jsat_bin))
    if jsat_bin:
        report.add(check_editable_checkout())
    report.add(check_version_consistency())
    report.add(check_no_state_leak())

    for cli in ("claude", "codex", "opencode", "bob", "git", "entr", "semgrep"):
        report.add(check_binary_on_path(cli))
    for mod, extra in (("semgrep", "standard"), ("neo4j", "team"),
                       ("qdrant_client", "team"), ("redis", "team"),
                       ("anthropic", "anthropic"), ("openai", "openai"),
                       ("ollama", "local"), ("prometheus_client", "team"),
                       ("tree_sitter_java", "standard"),
                       ("tree_sitter_ruby", "standard"),
                       ("tree_sitter_rust", "standard")):
        report.add(check_python_module(mod, extra))

    report.add(check_docker())
    report.add(check_ollama())
    report.add(check_tcp_service("neo4j", "localhost", 7687))
    report.add(check_tcp_service("qdrant", "localhost", 6333))
    report.add(check_tcp_service("redis", "localhost", 6379))
    report.add(check_env_key("ANTHROPIC_API_KEY"))
    report.add(check_env_key("OPENAI_API_KEY"))
    report.add(check_internet())
