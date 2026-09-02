#!/usr/bin/env python3
"""
jsat_selftest.py — end-to-end, no-mocking self-test of the CURRENTLY INSTALLED
local `jsat` binary and MCP server.

Every check here exercises the real installed artifact: the actual `jsat`
console script as a subprocess, the actual MCP server over real stdio
JSON-RPC, real external services if reachable (ollama/neo4j/qdrant/redis/
claude-cli/etc). Nothing is stubbed or monkeypatched. A check whose external
dependency is not present on this machine is reported as "unavailable", never
silently skipped and never counted as a failure.

Output: a JSON report (machine-readable, for any AI agent to triage) and a
companion Markdown summary, written next to this script unless --out is given.

Usage:
  python3 scripts/jsat_selftest.py                # full run
  python3 scripts/jsat_selftest.py --quick         # skip pytest --all + heavy MCP calls
  python3 scripts/jsat_selftest.py --out /tmp/rep  # custom output path prefix
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Check:
    id: str
    category: str
    status: str  # "pass" | "fail" | "unavailable"
    summary: str
    detail: str = ""
    remediation: str = ""
    elapsed_ms: int = 0


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, c: Check) -> Check:
        self.checks.append(c)
        icon = {"pass": "✅", "fail": "❌", "unavailable": "⚠️"}[c.status]
        print(f"  {icon} [{c.category}] {c.id} — {c.summary}")
        return c


def timed(fn):
    def wrapper(*a, **kw):
        t0 = time.monotonic()
        c = fn(*a, **kw)
        c.elapsed_ms = round((time.monotonic() - t0) * 1000)
        return c

    return wrapper


def tcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_reachable(url: str, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 (local/dev self-test)
        return True
    except Exception:
        return False


def run_cli(jsat_bin: str, args: list[str], env: dict, cwd: str | None = None,
            timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [jsat_bin, *args], capture_output=True, text=True, timeout=timeout,
        env=env, cwd=cwd,
    )


# ── Environment ────────────────────────────────────────────────────────────

@timed
def check_jsat_installed(jsat_bin: str | None) -> Check:
    if not jsat_bin:
        return Check("jsat_binary_found", "environment", "fail",
                      "`jsat` console script not found on PATH",
                      remediation="pip install -e . (from the repo root) or pip install jsat")
    try:
        import importlib.metadata as m
        ver = m.version("jsat")
    except Exception as e:
        ver = f"unknown ({e})"
    return Check("jsat_binary_found", "environment", "pass",
                 f"jsat binary at {jsat_bin}, version {ver}", detail=f"version={ver}")


@timed
def check_editable_checkout(jsat_bin: str) -> Check:
    """Confirm the binary actually serves THIS checkout, not a stale copy —
    the exact bug local_test.sh's check_env() was written to catch."""
    try:
        out = subprocess.run(
            [sys.executable, "-c",
             "import jsat, pathlib; print(pathlib.Path(jsat.__file__).resolve().parent)"],
            capture_output=True, text=True, cwd=tempfile.gettempdir(), timeout=15,
        )
        loaded_from = out.stdout.strip()
    except Exception as e:
        return Check("editable_checkout", "environment", "fail", f"could not resolve jsat module: {e}")
    expected = str(REPO_ROOT / "jsat")
    if loaded_from == expected:
        return Check("editable_checkout", "environment", "pass",
                      "running this checkout (editable install)", detail=loaded_from)
    return Check("editable_checkout", "environment", "fail",
                  f"a DIFFERENT jsat copy is shadowing this checkout: {loaded_from}",
                  detail=f"expected={expected} actual={loaded_from}",
                  remediation=f"{sys.executable} -m pip install -e .")


# ── External dependency probes (real checks, never mocked) ────────────────

@timed
def check_binary_on_path(name: str) -> Check:
    path = shutil.which(name)
    if path:
        return Check(f"external_cli_{name}", "external_deps", "pass", f"{name} found on PATH",
                      detail=path)
    return Check(f"external_cli_{name}", "external_deps", "unavailable",
                  f"{name} not installed — tests needing it will be skipped, not failed")


@timed
def check_ollama() -> Check:
    if http_reachable("http://localhost:11434/api/tags", timeout=1.5):
        return Check("external_ollama", "external_deps", "pass", "ollama reachable at :11434")
    return Check("external_ollama", "external_deps", "unavailable",
                  "ollama not reachable at localhost:11434 — ollama-backed AI checks will be skipped")


@timed
def check_tcp_service(name: str, host: str, port: int) -> Check:
    if tcp_reachable(host, port):
        return Check(f"external_{name}", "external_deps", "pass", f"{name} reachable at {host}:{port}")
    return Check(f"external_{name}", "external_deps", "unavailable",
                  f"{name} not reachable at {host}:{port} — integration tests needing it will be skipped")


@timed
def check_env_key(name: str) -> Check:
    if os.environ.get(name, "").strip():
        return Check(f"external_{name.lower()}", "external_deps", "pass", f"{name} is set")
    return Check(f"external_{name.lower()}", "external_deps", "unavailable",
                  f"{name} is not set — checks needing it will be skipped")


@timed
def check_internet() -> Check:
    if http_reachable("https://api.anthropic.com", timeout=3.0) or \
       http_reachable("https://pypi.org", timeout=3.0):
        return Check("external_internet", "external_deps", "pass", "outbound internet reachable")
    return Check("external_internet", "external_deps", "unavailable",
                  "no outbound internet reachable — internet-dependent checks will be skipped")


# ── Real CLI smoke tests (actual subprocess calls, real stdout/exit codes) ─

@timed
def check_cli_version(jsat_bin: str, env: dict) -> Check:
    r = run_cli(jsat_bin, ["version"], env)
    if r.returncode == 0 and r.stdout.strip():
        return Check("cli_version", "cli_smoke", "pass", "jsat version ran", detail=r.stdout.strip())
    return Check("cli_version", "cli_smoke", "fail", "jsat version failed",
                 detail=f"rc={r.returncode} stderr={r.stderr[:300]}")


@timed
def check_cli_help(jsat_bin: str, env: dict) -> Check:
    r = run_cli(jsat_bin, ["--help"], env)
    if r.returncode == 0 and "Usage" in r.stdout:
        return Check("cli_help", "cli_smoke", "pass", "jsat --help ran")
    return Check("cli_help", "cli_smoke", "fail", "jsat --help failed",
                 detail=f"rc={r.returncode} stderr={r.stderr[:300]}")


@timed
def check_cli_doctor(jsat_bin: str, env: dict, cwd: str) -> Check:
    r = run_cli(jsat_bin, ["doctor", "--json"], env, cwd=cwd, timeout=30)
    if r.returncode != 0:
        return Check("cli_doctor", "cli_smoke", "fail", "jsat doctor exited non-zero",
                     detail=f"rc={r.returncode} stderr={r.stderr[:400]}")
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return Check("cli_doctor", "cli_smoke", "fail", f"jsat doctor --json produced invalid JSON: {e}",
                     detail=r.stdout[:400])
    return Check("cli_doctor", "cli_smoke", "pass", "jsat doctor --json returned valid JSON",
                 detail=json.dumps(payload)[:400])


@timed
def check_cli_ai_status(jsat_bin: str, env: dict) -> Check:
    r = run_cli(jsat_bin, ["ai", "status"], env, timeout=20)
    if r.returncode == 0:
        return Check("cli_ai_status", "cli_smoke", "pass", "jsat ai status ran")
    return Check("cli_ai_status", "cli_smoke", "fail", "jsat ai status failed",
                 detail=f"rc={r.returncode} stderr={r.stderr[:300]}")


@timed
def check_cli_connect_list(jsat_bin: str, env: dict) -> Check:
    r = run_cli(jsat_bin, ["connect", "list"], env, timeout=20)
    if r.returncode == 0:
        return Check("cli_connect_list", "cli_smoke", "pass", "jsat connect list ran")
    return Check("cli_connect_list", "cli_smoke", "fail", "jsat connect list failed",
                 detail=f"rc={r.returncode} stderr={r.stderr[:300]}")


# ── Real index lifecycle against a synthetic scratch repo ─────────────────

def make_scratch_repo(tmp: Path) -> Path:
    repo = tmp / "scratch_repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "app.py").write_text(
        "def add(a, b):\n"
        "    \"\"\"Add two numbers.\"\"\"\n"
        "    return a + b\n\n"
        "class Greeter:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n\n"
        "    def greet(self):\n"
        "        return add(1, 1) and f'hello {self.name}'\n"
    )
    (repo / "main.py").write_text(
        "from app import Greeter\n\n"
        "def main():\n"
        "    g = Greeter('world')\n"
        "    print(g.greet())\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    return repo


@timed
def check_cli_index(jsat_bin: str, env: dict, repo: Path) -> Check:
    r = run_cli(jsat_bin, ["index", str(repo)], env, timeout=60)
    if r.returncode != 0:
        return Check("cli_index", "index_lifecycle", "fail", "jsat index failed on scratch repo",
                     detail=f"rc={r.returncode} stderr={r.stderr[:400]}")
    return Check("cli_index", "index_lifecycle", "pass", "jsat index completed on scratch repo",
                 detail=r.stdout[:400])


@timed
def check_index_populated(jsat_bin: str, env: dict, repo: Path) -> Check:
    r = run_cli(jsat_bin, ["doctor", "--json"], env, cwd=str(repo), timeout=30)
    if r.returncode != 0:
        return Check("index_populated", "index_lifecycle", "fail",
                     "could not read back index status after indexing",
                     detail=f"rc={r.returncode} stderr={r.stderr[:300]}")
    try:
        payload = json.loads(r.stdout)
        nodes = payload.get("index", {}).get("nodes", 0)
        edges = payload.get("index", {}).get("edges", 0)
    except json.JSONDecodeError:
        return Check("index_populated", "index_lifecycle", "fail",
                     "doctor --json output not parseable after indexing", detail=r.stdout[:300])
    if nodes > 0:
        return Check("index_populated", "index_lifecycle", "pass",
                     f"scratch repo indexed: {nodes} nodes, {edges} edges")
    return Check("index_populated", "index_lifecycle", "fail",
                 "index reports 0 nodes after indexing a real scratch repo with real code",
                 detail=json.dumps(payload)[:300])


# ── Real MCP server: actual stdio JSON-RPC, no mocking ─────────────────────

class MCPClient:
    def __init__(self, jsat_bin: str, repo: Path, env: dict):
        self.proc = subprocess.Popen(
            [jsat_bin, "mcp-server", "--repo", str(repo)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env,
        )
        self._id = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict | None:
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    return None
                continue
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON on stdout is itself a bug (server.py's own contract:
                # stdout carries ONLY JSON-RPC) — surface it rather than skipping.
                raise RuntimeError(f"non-JSON-RPC line on stdout (protocol violation): {line[:200]}")
            if msg.get("id") == req["id"]:
                return msg
        return None

    def notify(self, method: str, params: dict | None = None) -> None:
        assert self.proc.stdin is not None
        note = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(note) + "\n")
        self.proc.stdin.flush()

    def close(self):
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


@timed
def check_mcp_handshake(jsat_bin: str, repo: Path, env: dict) -> Check:
    client = None
    try:
        client = MCPClient(jsat_bin, repo, env)
        init = client.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "jsat_selftest", "version": "1.0"},
        })
        if init is None or "result" not in init:
            stderr_tail = ""
            if client.proc.stderr:
                try:
                    stderr_tail = client.proc.stderr.read(500)
                except Exception:
                    pass
            return Check("mcp_initialize", "mcp_server", "fail",
                         "MCP server did not respond to initialize",
                         detail=f"response={init} stderr={stderr_tail}")
        client.notify("notifications/initialized")
        return Check("mcp_initialize", "mcp_server", "pass", "MCP server initialize handshake OK")
    except RuntimeError as e:
        return Check("mcp_initialize", "mcp_server", "fail", str(e))
    except Exception as e:
        return Check("mcp_initialize", "mcp_server", "fail", f"MCP handshake crashed: {e}")
    finally:
        if client:
            client.close()


@timed
def check_mcp_tools_list(jsat_bin: str, repo: Path, env: dict) -> Check:
    client = None
    try:
        client = MCPClient(jsat_bin, repo, env)
        client.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                    "clientInfo": {"name": "jsat_selftest", "version": "1.0"}})
        client.notify("notifications/initialized")
        resp = client.call("tools/list")
        if resp is None or "result" not in resp:
            return Check("mcp_tools_list", "mcp_server", "fail",
                         "tools/list did not return a result", detail=str(resp))
        tools = resp["result"].get("tools", [])
        if not tools:
            return Check("mcp_tools_list", "mcp_server", "fail",
                         "tools/list returned zero tools")
        return Check("mcp_tools_list", "mcp_server", "pass",
                     f"tools/list returned {len(tools)} tools",
                     detail=", ".join(t.get("name", "?") for t in tools[:10]) + " ...")
    except RuntimeError as e:
        return Check("mcp_tools_list", "mcp_server", "fail", str(e))
    except Exception as e:
        return Check("mcp_tools_list", "mcp_server", "fail", f"tools/list crashed: {e}")
    finally:
        if client:
            client.close()


@timed
def check_mcp_tool_call(jsat_bin: str, repo: Path, env: dict) -> Check:
    """Actually invoke a real graph-native tool end-to-end (get_index_status) —
    no stubbing of the tool handler, real graph read against the just-indexed
    scratch repo."""
    client = None
    try:
        client = MCPClient(jsat_bin, repo, env)
        client.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                    "clientInfo": {"name": "jsat_selftest", "version": "1.0"}})
        client.notify("notifications/initialized")
        resp = client.call("tools/call", {"name": "get_index_status", "arguments": {}})
        if resp is None or "result" not in resp:
            return Check("mcp_tool_call_get_index_status", "mcp_server", "fail",
                         "tools/call get_index_status failed", detail=str(resp))
        return Check("mcp_tool_call_get_index_status", "mcp_server", "pass",
                     "tools/call get_index_status succeeded end-to-end",
                     detail=json.dumps(resp["result"])[:300])
    except RuntimeError as e:
        return Check("mcp_tool_call_get_index_status", "mcp_server", "fail", str(e))
    except Exception as e:
        return Check("mcp_tool_call_get_index_status", "mcp_server", "fail", f"tools/call crashed: {e}")
    finally:
        if client:
            client.close()


# ── AI provider: real completion call, marked unavailable (not failed) when down

@timed
def check_ai_test(jsat_bin: str, env: dict) -> Check:
    r = run_cli(jsat_bin, ["ai", "test", "Reply with the single word: pong"], env, timeout=60)
    combined = (r.stdout + r.stderr).lower()
    if r.returncode == 0 and "response:" in combined:
        return Check("ai_provider_completion", "ai_provider", "pass",
                     "AI provider answered a real completion request", detail=r.stdout[:300])
    if "not available" in combined or "not configured" in combined or "no ai provider" in combined:
        return Check("ai_provider_completion", "ai_provider", "unavailable",
                     "no AI provider configured/reachable — AI-backed jsat features degrade",
                     detail=(r.stdout + r.stderr)[:400],
                     remediation="jsat ai use <provider> (e.g. claude_cli, anthropic, ollama)")
    return Check("ai_provider_completion", "ai_provider", "fail",
                 "jsat ai test failed for a reason other than provider-unavailable",
                 detail=f"rc={r.returncode} out={r.stdout[:200]} err={r.stderr[:200]}")


# ── Live-agent checks (real Claude agent, headless, opt-in — costs $ + time) ─
#
# `jsat claude` and `/jsat <skill>` were previously "untestable without a live
# TTY / a real LLM in the loop." That's not actually true: `claude -p` (print
# mode) runs the exact same agent loop non-interactively — same --mcp-config
# shape jsat claude builds, same tool-calling, same skill-dispatch file — just
# without attaching to a terminal. This drives the REAL claude binary, the
# REAL jsat mcp-server subprocess, and (for the skill check) the REAL
# .claude/commands/jsat.md dispatcher exactly as installed. Nothing here is
# mocked or simulated. It costs real API tokens and wall-clock time per call
# (verified: ~$0.04/~7s for a bare tool call, ~$0.88/~20s for a full skill
# dispatch, since jsat.md itself is large context) — that's why it's opt-in.

def _claude_mcp_config(jsat_bin: str, repo: str) -> dict:
    """Same shape as jsat.tools.shell.launch_ai_with_jsat_tools's own
    --mcp-config (including the JSAT_AI_PROVIDER fix) — kept in sync manually
    since that function builds its file inline rather than exposing a helper.
    If you change one, change the other."""
    return {
        "mcpServers": {
            "jsat": {
                "command": jsat_bin,
                "args": ["mcp-server", "--repo", repo],
                "env": {"JSAT_AI_PROVIDER": "claude_cli"},
            }
        }
    }


def _run_claude_headless(prompt: str, mcp_config: dict, repo: str, allowed_tools: list[str],
                          timeout: int = 90) -> dict | None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(mcp_config, f)
        cfg_path = f.name
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--mcp-config", cfg_path, "--add-dir", repo,
             "--strict-mcp-config", "--allowedTools", *allowed_tools,
             "--output-format", "json"],
            capture_output=True, text=True, timeout=timeout,
        )
    finally:
        os.unlink(cfg_path)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


@timed
def check_live_claude_tool_call(jsat_bin: str, repo: str) -> Check:
    if not shutil.which("claude"):
        return Check("live_claude_tool_call", "live_agent", "unavailable",
                     "claude CLI not on PATH — cannot run a live headless check")
    cfg = _claude_mcp_config(jsat_bin, repo)
    resp = _run_claude_headless(
        "Call the jsat__get_index_status MCP tool exactly once and reply with "
        "ONLY its raw JSON result, nothing else.",
        cfg, repo, allowed_tools=["mcp__jsat__get_index_status"],
    )
    if resp is None:
        return Check("live_claude_tool_call", "live_agent", "fail",
                     "claude -p headless call produced no parseable response")
    if resp.get("is_error"):
        return Check("live_claude_tool_call", "live_agent", "fail",
                     f"claude reported an error: {resp.get('result')}", detail=json.dumps(resp)[:500])
    if resp.get("permission_denials"):
        return Check("live_claude_tool_call", "live_agent", "fail",
                     "MCP tool call was permission-denied (jsat claude's real users hit this "
                     "wall too unless they approve interactively)",
                     detail=json.dumps(resp["permission_denials"]))
    result_text = resp.get("result", "")
    if '"nodes"' not in result_text or '"edges"' not in result_text:
        return Check("live_claude_tool_call", "live_agent", "fail",
                     "response did not contain the expected get_index_status shape",
                     detail=result_text[:300])
    return Check("live_claude_tool_call", "live_agent", "pass",
                 f"real claude agent → real jsat MCP server → real tool call succeeded "
                 f"(${resp.get('total_cost_usd', 0):.4f}, {resp.get('duration_ms', 0)}ms)",
                 detail=result_text[:300])


@dataclass
class SkillSpec:
    id: str
    prompt: str                 # what a real user would type as the slash-command
    allowed_tools: list[str]    # every mcp__jsat__* tool this skill is expected to call
    must_contain: list[str] = field(default_factory=list)      # substrings expected (any case)
    must_not_contain: list[str] = field(default_factory=list)  # e.g. error phrases
    timeout: int = 120


# Curated, cross-category sample — NOT all 46+ skills. Each real invocation costs
# real API tokens (~$0.10-0.90, ~10-20s observed) because the whole jsat.md
# dispatcher is loaded as context every time. Extend this list deliberately;
# don't default to running the full catalog live on every CI run.
SKILL_SUITE: list[SkillSpec] = [
    SkillSpec("skill_list_services", "/jsat list-services",
              ["mcp__jsat__list_services"],
              must_contain=["jsat"], must_not_contain=["unknown command"]),
    SkillSpec("skill_list_endpoints", "/jsat list-endpoints",
              ["mcp__jsat__list_endpoints"],
              must_not_contain=["unknown command"]),
    SkillSpec("skill_find_function", "/jsat find-function main",
              ["mcp__jsat__get_function", "mcp__jsat__query"],
              must_not_contain=["unknown command"]),
    SkillSpec("skill_status", "/jsat status",
              ["mcp__jsat__get_index_status", "mcp__jsat__get_jsat_version", "mcp__jsat__health"],
              must_not_contain=["unknown command"]),
    SkillSpec("skill_short", "/jsat short what does the jsat package do?",
              ["mcp__jsat__short", "mcp__jsat__query"],
              must_not_contain=["unknown command"]),
    SkillSpec("skill_tokens", "/jsat tokens hello world, this is a token count test",
              ["mcp__jsat__token_count"],
              must_not_contain=["unknown command"]),
]


@timed
def check_live_skill(jsat_bin: str, repo: str, spec: SkillSpec) -> Check:
    """Exercises the REAL .claude/commands/jsat.md dispatcher exactly as
    `jsat connect claude` installs it — not a reimplementation of it."""
    if not shutil.which("claude"):
        return Check(spec.id, "live_agent", "unavailable",
                     "claude CLI not on PATH — cannot run a live headless check")
    dispatcher = Path(repo) / ".claude" / "commands" / "jsat.md"
    if not dispatcher.exists():
        return Check(spec.id, "live_agent", "unavailable",
                     f"no /jsat dispatcher installed at {dispatcher} — run `jsat connect claude` first")
    cfg = _claude_mcp_config(jsat_bin, repo)
    resp = _run_claude_headless(spec.prompt, cfg, repo,
                                 allowed_tools=spec.allowed_tools, timeout=spec.timeout)
    if resp is None:
        return Check(spec.id, "live_agent", "fail",
                     f"claude -p headless call for '{spec.prompt}' produced no parseable response")
    result_text = resp.get("result", "")
    lower = result_text.lower()
    for bad in ["unknown command", *spec.must_not_contain]:
        if bad.lower() in lower:
            return Check(spec.id, "live_agent", "fail",
                         f"'{spec.prompt}' response contained forbidden text: '{bad}'",
                         detail=result_text[:400])
    if resp.get("is_error") or resp.get("permission_denials"):
        return Check(spec.id, "live_agent", "fail",
                     f"'{spec.prompt}' errored or was permission-denied",
                     detail=json.dumps(resp)[:500])
    missing = [m for m in spec.must_contain if m.lower() not in lower]
    if missing:
        return Check(spec.id, "live_agent", "fail",
                     f"'{spec.prompt}' response missing expected content: {missing}",
                     detail=result_text[:400])
    return Check(spec.id, "live_agent", "pass",
                 f"'{spec.prompt}' ran end-to-end via the real installed dispatcher "
                 f"(${resp.get('total_cost_usd', 0):.4f}, {resp.get('duration_ms', 0)}ms)",
                 detail=result_text[:400])


# ── Delegate to the existing pytest+lint runner (local_test.sh) ───────────

@timed
def check_pytest_suite(run_all: bool) -> Check:
    script = REPO_ROOT / "local_test.sh"
    if not script.exists():
        return Check("pytest_suite", "test_suite", "unavailable",
                     "local_test.sh not found — cannot run the pytest/lint suite")
    args = [str(script)] + (["--all"] if run_all else [])
    try:
        r = subprocess.run(args, capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=900)
    except subprocess.TimeoutExpired:
        return Check("pytest_suite", "test_suite", "fail", "local_test.sh timed out after 900s")
    status = "pass" if r.returncode == 0 else "fail"
    tail = "\n".join((r.stdout + r.stderr).splitlines()[-40:])
    return Check("pytest_suite", "test_suite", status,
                 f"local_test.sh {'--all ' if run_all else ''}exited {r.returncode}",
                 detail=tail)


# ── Report writers ──────────────────────────────────────────────────────────

def write_reports(report: Report, out_prefix: Path) -> tuple[Path, Path]:
    json_path = out_prefix.with_suffix(".json")
    md_path = out_prefix.with_suffix(".md")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": str(REPO_ROOT),
        "summary": {
            "total": len(report.checks),
            "pass": sum(1 for c in report.checks if c.status == "pass"),
            "fail": sum(1 for c in report.checks if c.status == "fail"),
            "unavailable": sum(1 for c in report.checks if c.status == "unavailable"),
        },
        "checks": [c.__dict__ for c in report.checks],
    }
    json_path.write_text(json.dumps(payload, indent=2))

    lines = [
        "# JSAT Self-Test Report",
        "",
        f"Generated: {payload['generated_at']}",
        f"Repo: {payload['repo']}",
        "",
        f"**{payload['summary']['pass']} passed / "
        f"{payload['summary']['fail']} failed / "
        f"{payload['summary']['unavailable']} unavailable** "
        f"(of {payload['summary']['total']} checks)",
        "",
    ]
    if payload["summary"]["fail"]:
        lines += ["## ❌ Failures (fix these)", ""]
        for c in report.checks:
            if c.status == "fail":
                lines += [f"### {c.id} ({c.category})", f"- {c.summary}"]
                if c.detail:
                    lines += ["```", c.detail[:1000], "```"]
                if c.remediation:
                    lines += [f"- **Fix:** {c.remediation}"]
                lines += [""]
    if payload["summary"]["unavailable"]:
        lines += ["## ⚠️ Unavailable in this environment (not failures)", ""]
        for c in report.checks:
            if c.status == "unavailable":
                lines += [f"- **{c.id}** ({c.category}): {c.summary}"]
        lines += [""]
    lines += ["## ✅ Passed", ""]
    for c in report.checks:
        if c.status == "pass":
            lines += [f"- **{c.id}** ({c.category}): {c.summary} ({c.elapsed_ms}ms)"]

    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


def resolve_jsat_binary() -> str | None:
    """Return the `jsat` console script installed in the SAME interpreter
    running this file, not whatever `jsat` happens to be first on $PATH.

    A bare `shutil.which("jsat")` can silently pick a different environment's
    copy than the one `sys.executable` belongs to (e.g. a stale conda-env
    install shadowing this repo's own .venv) — exactly the class of bug
    check_editable_checkout() exists to catch. Resolving from sys.executable's
    own bin/ directory first keeps "which interpreter" and "which binary" the
    same answer, so this script always tests what it thinks it's testing.
    """
    same_env = Path(sys.executable).parent / "jsat"
    if same_env.exists():
        return str(same_env)
    return shutil.which("jsat")


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true",
                     help="skip local_test.sh --all and keep it to CI-safe pytest")
    ap.add_argument("--full", action="store_true",
                     help="run local_test.sh --all too (needs neo4j/qdrant/redis)")
    ap.add_argument("--out", type=str, default=None,
                     help="output path prefix (default: ./jsat-selftest-report-<ts>)")
    ap.add_argument("--live-agent", action="store_true",
                     help="also drive a REAL headless claude agent through jsat's real "
                          "--mcp-config and the real /jsat dispatcher (jsat claude and "
                          "/jsat <skill> end-to-end). Costs real API tokens (~$0.90 total) "
                          "and ~30s — opt-in, never runs by default.")
    args = ap.parse_args()

    jsat_bin = resolve_jsat_binary()
    report = Report()

    print("== Environment ==")
    report.add(check_jsat_installed(jsat_bin))
    if jsat_bin:
        report.add(check_editable_checkout(jsat_bin))

    print("== External dependencies (real probes, none mocked) ==")
    for cli in ("claude", "codex", "opencode", "bob"):
        report.add(check_binary_on_path(cli))
    report.add(check_ollama())
    report.add(check_tcp_service("neo4j", "localhost", 7687))
    report.add(check_tcp_service("qdrant", "localhost", 6333))
    report.add(check_tcp_service("redis", "localhost", 6379))
    report.add(check_env_key("ANTHROPIC_API_KEY"))
    report.add(check_env_key("OPENAI_API_KEY"))
    report.add(check_internet())

    if not jsat_bin:
        print("\n❌ jsat binary not found — skipping every check that needs it.")
        json_path, md_path = write_reports(report, Path(args.out or f"jsat-selftest-report-{int(time.time())}"))
        print(f"\nReport: {json_path}\n        {md_path}")
        return 1

    with tempfile.TemporaryDirectory(prefix="jsat-selftest-") as tmpdir:
        tmp = Path(tmpdir)
        # Full isolation: never touch the user's real ~/.jsat/improve or
        # ~/.jsat/sessions, same discipline local_test.sh already uses.
        # JSAT_CONFIG is deliberately left unset so this exercises whatever
        # AI provider the user actually has configured — "no mocking".
        env = {
            **os.environ,
            "JSAT_DATA_DIR": str(tmp / "jsat-data"),
            "JSAT_IMPROVE_DIR": str(tmp / "improve"),
            "JSAT_SESSIONS_DIR": str(tmp / "sessions"),
        }

        print("\n== CLI smoke (real subprocess calls) ==")
        report.add(check_cli_version(jsat_bin, env))
        report.add(check_cli_help(jsat_bin, env))
        report.add(check_cli_doctor(jsat_bin, env, str(tmp)))
        report.add(check_cli_ai_status(jsat_bin, env))
        report.add(check_cli_connect_list(jsat_bin, env))

        print("\n== Index lifecycle (real scratch repo, real parse) ==")
        repo = make_scratch_repo(tmp)
        report.add(check_cli_index(jsat_bin, env, repo))
        report.add(check_index_populated(jsat_bin, env, repo))

        print("\n== MCP server (real stdio JSON-RPC, no protocol mocking) ==")
        report.add(check_mcp_handshake(jsat_bin, repo, env))
        report.add(check_mcp_tools_list(jsat_bin, repo, env))
        report.add(check_mcp_tool_call(jsat_bin, repo, env))

        print("\n== AI provider (real completion call) ==")
        report.add(check_ai_test(jsat_bin, env))

    if args.live_agent:
        print(f"\n== Live agent (REAL claude -p calls — 1 raw tool call + "
              f"{len(SKILL_SUITE)} skills, costs real API tokens/time) ==")
        report.add(check_live_claude_tool_call(jsat_bin, str(REPO_ROOT)))
        for spec in SKILL_SUITE:
            report.add(check_live_skill(jsat_bin, str(REPO_ROOT), spec))
    else:
        print("\n(skipping live-agent checks — pass --live-agent to also drive a real "
              "headless claude session through jsat's actual MCP config + /jsat dispatcher "
              f"across {len(SKILL_SUITE)} curated skills; costs real API tokens)")

    print("\n== Test suite (delegates to local_test.sh) ==")
    report.add(check_pytest_suite(run_all=args.full and not args.quick))

    out_prefix = Path(args.out) if args.out else Path(f"jsat-selftest-report-{int(time.time())}")
    json_path, md_path = write_reports(report, out_prefix)

    summary = {
        "pass": sum(1 for c in report.checks if c.status == "pass"),
        "fail": sum(1 for c in report.checks if c.status == "fail"),
        "unavailable": sum(1 for c in report.checks if c.status == "unavailable"),
    }
    print(f"\n{'=' * 60}")
    print(f"✅ {summary['pass']} passed   ❌ {summary['fail']} failed   "
          f"⚠️  {summary['unavailable']} unavailable")
    print(f"Report: {json_path}")
    print(f"        {md_path}")
    print(f"{'=' * 60}")

    return 1 if summary["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
