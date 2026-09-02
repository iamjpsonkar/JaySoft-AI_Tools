"""
Phase M — the live agent.

`jsat claude` and `/jsat <skill>` were long treated as untestable without a
TTY and a human. They are not: `claude -p` runs the same agent loop
non-interactively, with the same --mcp-config shape `jsat claude` builds, the
same tool-calling, and the same dispatcher file on disk. So this drives the
REAL claude binary against the REAL jsat mcp-server against the REAL
.claude/commands/jsat.md that `jsat connect claude` installed.

Nothing here is simulated. It costs real API tokens and real wall-clock time,
which is the only reason it is opt-in.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..core import FAIL, PASS, REPO_ROOT, UNAVAILABLE, Check, Report, timed

COMMANDS_DIR = REPO_ROOT / "jsat" / "commands"

_NEGATION = re.compile(
    r"(there is no|does not exist|is not an? (?:mcp )?tool|not a tool|"
    r"no such tool|do not (?:literally )?call)", re.I)


def tools_named_by_command(name: str) -> list[str]:
    """Every mcp__jsat__* tool the command file for `name` tells the agent to
    call, derived from the file rather than hand-listed.

    Hand-maintained allow-lists were consistently too narrow — `/jsat
    list-services` also calls `list_endpoints` — and a denied tool makes the
    skill look broken when the only thing wrong was the test's permission
    grant. Deriving keeps the grant in step with the instructions the agent
    is actually given. References inside a negation ("there is no
    jsat__run_app tool") are skipped, since those tell the agent NOT to call.
    """
    path = COMMANDS_DIR / f"jsat-{name}.md"
    if not path.exists():
        return []
    text = path.read_text()
    found: list[str] = []
    for m in re.finditer(r"jsat__([a-z_][a-z0-9_]*)", text):
        window = text[max(0, m.start() - 160):m.end() + 160]
        if _NEGATION.search(window):
            continue
        tool = f"mcp__jsat__{m.group(1)}"
        if tool not in found:
            found.append(tool)
    return found


def _developer_tools() -> list[str]:
    """The jsat toolset a real developer has, from the server's own RBAC table.

    Taken from `_ROLE_PERMISSIONS["developer"]` rather than hand-listed so it
    cannot drift from what JSAT itself considers appropriate for a developer.
    `import_index` is excluded because it is admin-only by design — it
    replaces the whole graph, and no skill should be doing that.
    """
    try:
        from jsat.mcp.server import _ROLE_PERMISSIONS
    except Exception:
        return []
    return [f"mcp__jsat__{name}"
            for name in sorted(_ROLE_PERMISSIONS["developer"])
            if name != "import_index"]


def _claude_mcp_config(jsat_bin: str, repo: str) -> dict:
    """The same shape jsat.tools.shell.launch_ai_with_jsat_tools builds.

    Kept in sync by hand because that function writes its config inline
    rather than exposing a helper. If you change one, change the other —
    check_launcher in the cli suite asserts the real one is valid JSON
    naming the jsat server, which is the guard against them diverging
    silently.
    """
    return {
        "mcpServers": {
            "jsat": {
                "command": jsat_bin,
                "args": ["mcp-server", "--repo", repo],
                "env": {"JSAT_AI_PROVIDER": "claude_cli"},
            }
        }
    }


def _run_claude_headless(prompt: str, mcp_config: dict, repo: str,
                         allowed_tools: list[str],
                         timeout: int = 120) -> dict | None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                    delete=False) as f:
        json.dump(mcp_config, f)
        cfg_path = f.name
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--mcp-config", cfg_path,
             "--add-dir", repo, "--strict-mcp-config",
             "--allowedTools", *allowed_tools, "--output-format", "json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    finally:
        os.unlink(cfg_path)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


@dataclass
class SkillSpec:
    id: str
    prompt: str                 # exactly what a user would type
    command: str                # the /jsat subcommand, used to derive the grant
    extra_tools: list[str] = field(default_factory=list)
    must_contain: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)
    timeout: int = 240

    def allowed(self) -> list[str]:
        """The grant a real user effectively gives an approved skill.

        Three parts, and the reasoning matters because getting this wrong
        makes a working skill look broken:

        1. Every tool the command file names — the instructions the agent is
           actually following.
        2. The whole jsat `developer` toolset. A capable agent enriches an
           answer with calls nobody wrote down — asked to list services it
           also lists endpoints; finishing a skill it offers to record what it
           learned with `knowledge_add`. Denying those is a permission
           artifact of the test, not a JSAT defect, and it degrades the answer
           silently. The `developer` role is the principled line: it is what a
           real user of JSAT has, and it excludes only `import_index`.
        3. Anything the spec adds explicitly.

        A denial after all three is therefore a real finding: the skill needs
        something write-shaped or expensive that it never declared.
        """
        tools = tools_named_by_command(self.command)
        for extra in _developer_tools() + self.extra_tools:
            if extra not in tools:
                tools.append(extra)
        return tools or ["mcp__jsat__query"]


# Twelve skills spanning every theme in the catalogue. Not all 47: each real
# invocation costs tokens and ~10-20s because the whole dispatcher loads as
# context every time. Extend deliberately.
SKILL_SUITE: list[SkillSpec] = [
    # exploration
    SkillSpec("skill_list_services", "/jsat list-services", "list-services",
              must_not_contain=["unknown command"]),
    SkillSpec("skill_find_function", "/jsat find-function process_payment",
              "find-function", must_not_contain=["unknown command"]),
    SkillSpec("skill_find_class", "/jsat find-class MCPServer", "find-class",
              must_not_contain=["unknown command"]),
    SkillSpec("skill_status", "/jsat status", "status",
              must_not_contain=["unknown command"]),
    # impact
    SkillSpec("skill_blast_radius", "/jsat blast-radius jsat/tools/indexer.py",
              "blast-radius", must_not_contain=["unknown command"]),
    SkillSpec("skill_trace", "/jsat trace from cmd_index to IndexerTool.run",
              "trace", must_not_contain=["unknown command"]),
    # quality
    SkillSpec("skill_test_gaps", "/jsat test-gaps", "test-gaps",
              must_not_contain=["unknown command"], timeout=420),
    SkillSpec("skill_security", "/jsat security", "security",
              must_not_contain=["unknown command"], timeout=600),
    # knowledge / ops
    SkillSpec("skill_recent", "/jsat recent", "recent",
              must_not_contain=["unknown command"]),
    SkillSpec("skill_knowledge", "/jsat knowledge how is money represented?",
              "knowledge", must_not_contain=["unknown command"]),
    # prompt / token
    SkillSpec("skill_tokens",
              "/jsat tokens hello world, this is a token count test", "tokens",
              must_not_contain=["unknown command"]),
    SkillSpec("skill_short", "/jsat short what does the jsat package do?",
              "short", must_not_contain=["unknown command"]),
]


@timed
def check_live_tool_call(jsat_bin: str, repo: Path) -> Check:
    """A real agent calling a real MCP tool through a real config."""
    if not shutil.which("claude"):
        return Check("live_claude_tool_call", "live_agent", UNAVAILABLE,
                     "the claude CLI is not on PATH")
    cfg = _claude_mcp_config(jsat_bin, str(repo))
    resp = _run_claude_headless(
        "Call the jsat__get_index_status MCP tool exactly once and reply with "
        "ONLY its raw JSON result, nothing else.",
        cfg, str(repo), allowed_tools=["mcp__jsat__get_index_status"])
    if resp is None:
        return Check("live_claude_tool_call", "live_agent", FAIL,
                     "claude -p produced no parseable response",
                     remediation="is the claude CLI logged in? try "
                                 "`claude -p hello`")
    if resp.get("is_error"):
        return Check("live_claude_tool_call", "live_agent", FAIL,
                     f"claude reported an error: {resp.get('result')}",
                     detail=json.dumps(resp)[:500])
    if resp.get("permission_denials"):
        return Check("live_claude_tool_call", "live_agent", FAIL,
                     "the MCP tool call was permission-denied",
                     detail=json.dumps(resp["permission_denials"])[:400])
    text = resp.get("result", "")
    if '"nodes"' not in text or '"edges"' not in text:
        return Check("live_claude_tool_call", "live_agent", FAIL,
                     "the response did not contain the get_index_status shape",
                     detail=text[:300])
    return Check("live_claude_tool_call", "live_agent", PASS,
                 f"real agent → real jsat MCP server → real tool call "
                 f"(${resp.get('total_cost_usd', 0):.4f}, "
                 f"{resp.get('duration_ms', 0)}ms)",
                 detail=text[:250])


@timed
def check_live_skill(jsat_bin: str, repo: Path, spec: SkillSpec) -> Check:
    """Exercise the dispatcher exactly as `jsat connect claude` installed it."""
    if not shutil.which("claude"):
        return Check(spec.id, "live_agent", UNAVAILABLE,
                     "the claude CLI is not on PATH")
    dispatcher = repo / ".claude" / "commands" / "jsat.md"
    if not dispatcher.exists():
        return Check(spec.id, "live_agent", UNAVAILABLE,
                     f"no /jsat dispatcher at {dispatcher}",
                     remediation="run `jsat connect claude` first")
    cfg = _claude_mcp_config(jsat_bin, str(repo))
    allowed = spec.allowed()
    resp = _run_claude_headless(spec.prompt, cfg, str(repo),
                                allowed_tools=allowed, timeout=spec.timeout)
    if resp is None:
        return Check(spec.id, "live_agent", FAIL,
                     f"'{spec.prompt}' produced no parseable response "
                     f"(timeout {spec.timeout}s?)")
    text = resp.get("result", "")
    low = text.lower()
    for bad in spec.must_not_contain:
        if bad.lower() in low:
            return Check(spec.id, "live_agent", FAIL,
                         f"'{spec.prompt}' response contained forbidden text "
                         f"'{bad}'", detail=text[:400])
    denied = sorted({d.get("tool_name", "?")
                     for d in resp.get("permission_denials") or []})
    # A denied NON-jsat tool is the dispatcher's own rule working as intended:
    # it tells the agent to use jsat__* tools and never Bash/Read/WebSearch as
    # substitutes, so an attempt that gets refused is enforcement, not a
    # defect. Only a denied jsat tool means this test under-granted.
    denied_jsat = [d for d in denied if d.startswith("mcp__jsat__")]
    if denied_jsat:
        return Check(spec.id, "live_agent", FAIL,
                     f"'{spec.prompt}' was denied jsat tool(s) {denied_jsat} — "
                     "the grant is narrower than the skill needs",
                     detail=f"granted {len(allowed)} tool(s)",
                     remediation="add it to that spec's extra_tools, or widen "
                                 "_developer_tools()")
    if resp.get("is_error"):
        return Check(spec.id, "live_agent", FAIL,
                     f"'{spec.prompt}' returned an agent error",
                     detail=json.dumps(resp)[:500])
    missing = [m for m in spec.must_contain if m.lower() not in low]
    if missing:
        return Check(spec.id, "live_agent", FAIL,
                     f"'{spec.prompt}' response missing {missing}",
                     detail=text[:400])
    note = ""
    if denied:
        note = (f"; correctly refused {denied} — the dispatcher forbids "
                "native tools as substitutes")
    return Check(spec.id, "live_agent", PASS,
                 f"'{spec.prompt}' ran end-to-end through the real installed "
                 f"dispatcher with {len(allowed)} tool(s) granted{note} "
                 f"(${resp.get('total_cost_usd', 0):.4f}, "
                 f"{resp.get('duration_api_ms', resp.get('duration_ms', 0))}ms)",
                 detail=text[:300])


@timed
def check_universal_flags(jsat_bin: str, repo: Path) -> Check:
    """`timeout=` and `dashboard=` are dispatcher-level contracts.

    They are documented in every command's help, so an agent must translate
    them into _budget / _dashboard on the tool call rather than treating them
    as part of the user's question.
    """
    if not shutil.which("claude"):
        return Check("live_universal_flags", "live_agent", UNAVAILABLE,
                     "the claude CLI is not on PATH")
    dispatcher = repo / ".claude" / "commands" / "jsat.md"
    if not dispatcher.exists():
        return Check("live_universal_flags", "live_agent", UNAVAILABLE,
                     "no /jsat dispatcher installed")
    cfg = _claude_mcp_config(jsat_bin, str(repo))
    resp = _run_claude_headless(
        "/jsat status timeout=90",
        cfg, str(repo),
        allowed_tools=["mcp__jsat__get_index_status",
                       "mcp__jsat__get_jsat_version", "mcp__jsat__health"],
        timeout=240)
    if resp is None:
        return Check("live_universal_flags", "live_agent", FAIL,
                     "'/jsat status timeout=90' produced no parseable response")
    text = (resp.get("result") or "")
    low = text.lower()
    if "unknown command" in low or "timeout=90" in low.replace(" ", ""):
        return Check("live_universal_flags", "live_agent", FAIL,
                     "the dispatcher did not absorb the universal `timeout=` "
                     "flag — it leaked into the answer or broke routing",
                     detail=text[:400])
    if resp.get("is_error"):
        return Check("live_universal_flags", "live_agent", FAIL,
                     "'/jsat status timeout=90' errored",
                     detail=json.dumps(resp)[:400])
    return Check("live_universal_flags", "live_agent", PASS,
                 "the dispatcher absorbed the universal `timeout=` flag and "
                 "still routed the command",
                 detail=text[:250])


def run(report: Report, jsat_bin: str, repo: Path) -> None:
    report.add(check_live_tool_call(jsat_bin, repo))
    for spec in SKILL_SUITE:
        report.add(check_live_skill(jsat_bin, repo, spec))
    report.add(check_universal_flags(jsat_bin, repo))
