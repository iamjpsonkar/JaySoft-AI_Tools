"""
Phase F — connector round-trips.

`jsat connect <tool>` edits configuration files that belong to other
programs. Two things can go wrong and both are silent: JSAT can fail to
write a usable entry, or it can clobber settings the user already had. So
every target is tested the same way — seed the file with an unrelated key,
connect, assert JSAT's entry landed AND the foreign key survived,
disconnect, assert JSAT's entry is gone AND the foreign key still survives.

HOME is redirected into the temp dir, so these are real writes to real
paths that simply are not the user's.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core import FAIL, PASS, Check, Report, run_cli, timed

# tool -> (config path relative to HOME, format, connect flags, disconnect flags)
#
# Paths come from jsat/_cli_connect.py's _CONNECT_LOCATIONS. The flags differ
# per target and that is not incidental: only claude/codex/bob expose
# --global/--scope, because only those have a meaningful project-vs-user
# split. The rest always write the user-level config for their tool, so
# passing --global to them is a usage error, not a bug.
CONNECT_TARGETS: dict[str, tuple[str, str, list[str], list[str]]] = {
    "claude": (".claude/settings.json", "json",
               ["--global"], ["--scope", "global"]),
    "codex": (".codex/config.toml", "toml",
              ["--global"], ["--scope", "global"]),
    "cursor": (".cursor/mcp.json", "json", [], []),
    "windsurf": (".codeium/windsurf/mcp_config.json", "json", [], []),
    "zed": (".config/zed/settings.json", "json", [], []),
    "gemini": (".gemini/settings.json", "json", [], []),
    "continue": (".continue/config.json", "json", [], []),
}

FOREIGN_KEY = "selftest_foreign_setting"
FOREIGN_VALUE = "must-survive-connect-and-disconnect"


def _seed(path: Path, kind: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "toml":
        path.write_text(f'{FOREIGN_KEY} = "{FOREIGN_VALUE}"\n')
    else:
        path.write_text(json.dumps({FOREIGN_KEY: FOREIGN_VALUE}, indent=2))


@timed
def check_connect_roundtrip(jsat_bin: str, tool: str, rel: str, kind: str,
                            conn_flags: list[str], disc_flags: list[str],
                            tmp: Path, env: dict[str, str]) -> Check:
    home = tmp / f"connect-home-{tool}"
    project = tmp / f"connect-proj-{tool}"
    project.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    cfg = home / rel
    _seed(cfg, kind)
    scoped = {**env, "HOME": str(home)}

    conn = run_cli(jsat_bin, ["connect", tool, *conn_flags], scoped,
                   cwd=str(project), timeout=180)
    if not cfg.exists():
        return Check(f"connect_{tool}", "connect", FAIL,
                     f"jsat connect {tool} did not write {rel}",
                     detail=f"rc={conn.returncode} out={conn.stdout[-300:]} "
                            f"err={conn.stderr[-300:]}")
    after_connect = cfg.read_text()

    if kind == "json":
        try:
            json.loads(after_connect)
        except json.JSONDecodeError as e:
            return Check(f"connect_{tool}", "connect", FAIL,
                         f"jsat connect {tool} left {rel} as invalid JSON: {e}",
                         detail=after_connect[:400])
    if "jsat" not in after_connect:
        return Check(f"connect_{tool}", "connect", FAIL,
                     f"{rel} has no jsat server entry after connect",
                     detail=after_connect[:400])
    if FOREIGN_VALUE not in after_connect:
        return Check(f"connect_{tool}", "connect", FAIL,
                     f"jsat connect {tool} CLOBBERED a pre-existing setting in {rel}",
                     detail=after_connect[:400],
                     remediation="merge into the existing config instead of "
                                 "overwriting it")

    disc = run_cli(jsat_bin, ["disconnect", tool, *disc_flags], scoped,
                   cwd=str(project), timeout=180)
    after_disc = cfg.read_text() if cfg.exists() else ""
    problems = []
    if re.search(r'"?jsat"?\s*[:=]', after_disc):
        problems.append("jsat entry survived disconnect")
    if FOREIGN_VALUE not in after_disc:
        problems.append("disconnect removed the unrelated setting")
    if problems:
        return Check(f"connect_{tool}", "connect", FAIL,
                     f"disconnect {tool}: " + "; ".join(problems),
                     detail=f"rc={disc.returncode} content={after_disc[:400]}")
    return Check(f"connect_{tool}", "connect", PASS,
                 f"connect→disconnect round-tripped cleanly and preserved "
                 f"unrelated settings in {rel}")


@timed
def check_malformed_config_not_clobbered(jsat_bin: str, tmp: Path,
                                         env: dict[str, str]) -> Check:
    """A pre-existing broken config must abort, not be silently replaced."""
    home = tmp / "connect-home-malformed"
    cfg = home / ".claude" / "settings.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    broken = '{ "mcpServers": { "other": { "command": "x" }  <<< not json'
    cfg.write_text(broken)
    r = run_cli(jsat_bin, ["connect", "claude", "--global"],
                {**env, "HOME": str(home)}, cwd=str(tmp), timeout=90)
    still_there = cfg.read_text()
    if still_there != broken:
        return Check("connect_malformed_guard", "connect", FAIL,
                     "jsat connect overwrote a malformed config instead of "
                     "refusing to touch it",
                     detail=f"rc={r.returncode} now={still_there[:300]}",
                     remediation="see _read_json_or_abort in jsat/_cli_common.py")
    if r.returncode == 0:
        return Check("connect_malformed_guard", "connect", FAIL,
                     "jsat connect exited 0 despite an unparseable target config",
                     detail=r.stdout[-300:])
    return Check("connect_malformed_guard", "connect", PASS,
                 "a malformed target config caused a clean refusal with the "
                 "file left byte-identical")


@timed
def check_connect_list(jsat_bin: str, env: dict[str, str]) -> Check:
    r = run_cli(jsat_bin, ["connect", "list"], env, timeout=60)
    if r.returncode != 0:
        return Check("connect_list", "connect", FAIL, "jsat connect list failed",
                     detail=f"rc={r.returncode} {r.stderr[:300]}")
    return Check("connect_list", "connect", PASS,
                 "jsat connect list enumerated the known config locations",
                 detail=r.stdout[:300])


@timed
def check_connect_claude_installs_skills(jsat_bin: str, tmp: Path,
                                         env: dict[str, str]) -> Check:
    """The /jsat dispatcher and slash commands must land, and be removed again."""
    home = tmp / "connect-home-skills"
    home.mkdir(parents=True, exist_ok=True)
    project = tmp / "skills-project"
    project.mkdir(parents=True, exist_ok=True)
    scoped = {**env, "HOME": str(home)}
    r = run_cli(jsat_bin, ["connect", "claude"], scoped,
                cwd=str(project), timeout=180)
    cmd_dir = project / ".claude" / "commands"
    dispatcher = cmd_dir / "jsat.md"
    if not dispatcher.exists():
        return Check("connect_claude_skills", "connect", FAIL,
                     "connect claude did not install the /jsat dispatcher",
                     detail=f"rc={r.returncode} out={r.stdout[-400:]}")
    installed = sorted(p.name for p in cmd_dir.glob("*.md"))
    text = dispatcher.read_text()
    if "## help" not in text:
        return Check("connect_claude_skills", "connect", FAIL,
                     "the installed dispatcher has no help section",
                     detail=text[:300])
    d = run_cli(jsat_bin, ["disconnect", "claude", "--scope", "project"],
                scoped, cwd=str(project), timeout=120)
    leftover = sorted(p.name for p in cmd_dir.glob("*.md")) \
        if cmd_dir.exists() else []
    if leftover:
        return Check("connect_claude_skills", "connect", FAIL,
                     f"disconnect left {len(leftover)} command file(s) behind",
                     detail=f"rc={d.returncode} leftover={leftover[:10]}")
    return Check("connect_claude_skills", "connect", PASS,
                 f"installed {len(installed)} command file(s) incl. the /jsat "
                 f"dispatcher, and disconnect removed all of them")


@timed
def check_connect_opencode_roundtrip(jsat_bin: str, tmp: Path,
                                     env: dict[str, str]) -> Check:
    """OpenCode is project-scoped by default: `.opencode/opencode.json`,
    `/jsat` + `/jsat-help` commands, and AGENTS.md guidance — and all of it
    must be removable again by `jsat disconnect opencode`."""
    home = tmp / "connect-home-opencode"
    home.mkdir(parents=True, exist_ok=True)
    project = tmp / "connect-proj-opencode"
    project.mkdir(parents=True, exist_ok=True)
    cfg = project / ".opencode" / "opencode.json"
    _seed(cfg, "json")
    scoped = {**env, "HOME": str(home)}

    conn = run_cli(jsat_bin, ["connect", "opencode"], scoped,
                   cwd=str(project), timeout=180)
    problems: list[str] = []
    if not cfg.exists():
        return Check("connect_opencode", "connect", FAIL,
                     "jsat connect opencode did not write .opencode/opencode.json",
                     detail=f"rc={conn.returncode} out={conn.stdout[-300:]}")
    try:
        data = json.loads(cfg.read_text())
    except json.JSONDecodeError as e:
        return Check("connect_opencode", "connect", FAIL,
                     "jsat connect opencode left invalid JSON", detail=str(e))
    if "jsat" not in data.get("mcp", {}):
        problems.append("no jsat entry under the opencode `mcp` key")
    if FOREIGN_VALUE not in cfg.read_text():
        problems.append("connect clobbered a pre-existing opencode setting")
    commands = project / ".opencode" / "commands"
    for name in ("jsat.md", "jsat-help.md"):
        if not (commands / name).exists():
            problems.append(f"{name} was not installed")
    if not (project / "AGENTS.md").exists():
        problems.append("AGENTS.md guidance was not written at project scope")
    if problems:
        return Check("connect_opencode", "connect", FAIL, "; ".join(problems),
                     detail=cfg.read_text()[:400])

    disc = run_cli(jsat_bin, ["disconnect", "opencode"], scoped,
                   cwd=str(project), timeout=120)
    if not cfg.exists():
        return Check("connect_opencode", "connect", FAIL,
                     "disconnect deleted the user's opencode config outright")
    after = cfg.read_text()
    after_data = json.loads(after)
    leftovers = [p.name for p in commands.glob("jsat*.md")] \
        if commands.exists() else []
    problems = []
    if "jsat" in after_data.get("mcp", {}):
        problems.append("jsat entry survived disconnect")
    if FOREIGN_VALUE not in after:
        problems.append("disconnect removed the unrelated opencode setting")
    if leftovers:
        problems.append(f"disconnect left command file(s): {leftovers[:5]}")
    if problems:
        return Check("connect_opencode", "connect", FAIL,
                     "disconnect opencode: " + "; ".join(problems),
                     detail=after[:400])
    return Check("connect_opencode", "connect", PASS,
                 "opencode connect→disconnect round-tripped cleanly: jsat mcp "
                 "entry, /jsat+/-help commands and an unrelated setting all "
                 "survived as expected")


@timed
def check_connect_bob_roundtrip(jsat_bin: str, tmp: Path,
                                env: dict[str, str]) -> Check:
    """Bob Shell is project-scoped by default: `.bob/settings.json` MCP entry,
    `/jsat-*` slash commands, and BOB.md guidance."""
    home = tmp / "connect-home-bob"
    home.mkdir(parents=True, exist_ok=True)
    project = tmp / "connect-proj-bob"
    project.mkdir(parents=True, exist_ok=True)
    cfg = project / ".bob" / "settings.json"
    _seed(cfg, "json")
    scoped = {**env, "HOME": str(home)}

    conn = run_cli(jsat_bin, ["connect", "bob"], scoped,
                   cwd=str(project), timeout=180)
    problems: list[str] = []
    if not cfg.exists():
        return Check("connect_bob", "connect", FAIL,
                     "jsat connect bob did not write .bob/settings.json",
                     detail=f"rc={conn.returncode} out={conn.stdout[-300:]}")
    try:
        data = json.loads(cfg.read_text())
    except json.JSONDecodeError as e:
        return Check("connect_bob", "connect", FAIL,
                     "jsat connect bob left invalid JSON", detail=str(e))
    if "jsat" not in data.get("mcpServers", {}):
        problems.append("no jsat entry under the bob mcpServers key")
    if FOREIGN_VALUE not in cfg.read_text():
        problems.append("connect clobbered a pre-existing bob setting")
    commands = project / ".bob" / "commands"
    if not list(commands.glob("jsat-*.md")):
        problems.append("no /jsat-* slash commands installed")
    if not (project / "BOB.md").exists():
        problems.append("BOB.md guidance was not written")
    if problems:
        return Check("connect_bob", "connect", FAIL, "; ".join(problems),
                     detail=cfg.read_text()[:400])

    disc = run_cli(jsat_bin, ["disconnect", "bob"], scoped,
                   cwd=str(project), timeout=120)
    if not cfg.exists():
        return Check("connect_bob", "connect", FAIL,
                     "disconnect deleted the user's bob config outright")
    after = cfg.read_text()
    after_data = json.loads(after)
    leftovers = [p.name for p in commands.glob("jsat-*.md")] \
        if commands.exists() else []
    problems = []
    if "jsat" in after_data.get("mcpServers", {}):
        problems.append("jsat entry survived disconnect")
    if FOREIGN_VALUE not in after:
        problems.append("disconnect removed the unrelated bob setting")
    if leftovers:
        problems.append(f"disconnect left command file(s): {leftovers[:5]}")
    if problems:
        return Check("connect_bob", "connect", FAIL,
                     "disconnect bob: " + "; ".join(problems),
                     detail=after[:400])
    return Check("connect_bob", "connect", PASS,
                 "bob connect→disconnect round-tripped cleanly: jsat mcp "
                 "entry, /jsat-* commands and an unrelated setting all "
                 "survived as expected")


@timed
def check_github_token_env_injection_guard(jsat_bin: str, tmp: Path,
                                            env: dict[str, str]) -> Check:
    """`connect github --token-env` is interpolated into a shell string, so a
    hostile env-var NAME must be rejected rather than executed."""
    home = tmp / "connect-home-gh"
    home.mkdir(parents=True, exist_ok=True)
    canary = tmp / "injection-canary.txt"
    hostile = f'X"; touch {canary}; echo "'
    r = run_cli(jsat_bin,
                ["connect", "github", "codex", "--token-env", hostile],
                {**env, "HOME": str(home)}, cwd=str(tmp), timeout=90)
    if canary.exists():
        return Check("connect_github_injection", "security", FAIL,
                     "a hostile --token-env value executed a shell command",
                     detail=f"canary created; rc={r.returncode}",
                     remediation="tighten the identifier validation in "
                                 "jsat/_cli_connect.py::cmd_connect_github")
    written = "\n".join(p.read_text() for p in home.rglob("*")
                        if p.is_file() and p.stat().st_size < 200_000)
    if canary.name in written or "touch " in written:
        return Check("connect_github_injection", "security", FAIL,
                     "the hostile value was written verbatim into a config that "
                     "is later evaluated by a shell",
                     detail=written[:400])
    if r.returncode == 0:
        return Check("connect_github_injection", "security", FAIL,
                     "a clearly invalid env-var name was accepted",
                     detail=r.stdout[-300:],
                     remediation="reject names failing [A-Za-z_][A-Za-z0-9_]*")
    return Check("connect_github_injection", "security", PASS,
                 "a shell-injection attempt via --token-env was refused")


def run(report: Report, jsat_bin: str, tmp: Path, env: dict[str, str]) -> None:
    report.add(check_connect_list(jsat_bin, env))
    for tool, (rel, kind, cflags, dflags) in CONNECT_TARGETS.items():
        report.add(check_connect_roundtrip(jsat_bin, tool, rel, kind,
                                           cflags, dflags, tmp, env))
    report.add(check_malformed_config_not_clobbered(jsat_bin, tmp, env))
    report.add(check_connect_claude_installs_skills(jsat_bin, tmp, env))
    report.add(check_connect_opencode_roundtrip(jsat_bin, tmp, env))
    report.add(check_connect_bob_roundtrip(jsat_bin, tmp, env))
    report.add(check_github_token_env_injection_guard(jsat_bin, tmp, env))
