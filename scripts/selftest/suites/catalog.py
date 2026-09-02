"""
Phase K — catalog consistency.

JSAT keeps the same information in several places by hand: the MCP registry,
the RBAC table, the slash-command markdown files, the `_JSAT_SKILLS` dict,
`jsat-help.md`, the CLI command table, and the docs. Every one of those pairs
has drifted at least once, and the failure mode is silent: a slash command
that names a tool which no longer exists just quietly does nothing at
runtime.

These checks are static, but they are checks against the *real* installed
registry and the *real* shipped files, and they are cheap enough to run every
time — which is what stops the drift coming back.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..core import FAIL, PASS, REPO_ROOT, UNAVAILABLE, Check, Report, timed

COMMANDS_DIR = REPO_ROOT / "jsat" / "commands"


def _registry_tool_names() -> set[str]:
    """The real registry, built exactly the way the server builds it.

    MCPServer.__init__ builds `self._registry` from `_build_registry()`, whose
    handlers close over the JSAT instance. A MagicMock JSAT is enough to
    enumerate names — this is the same pattern tests/test_mcp_server.py uses.
    """
    from unittest.mock import MagicMock

    from jsat.mcp.server import MCPServer
    server = MCPServer(MagicMock())
    return set(server._registry)


def _cli_command_names(jsat_bin: str, env: dict[str, str]) -> set[str]:
    r = subprocess.run([jsat_bin, "--help"], capture_output=True, text=True,
                       timeout=60, env=env)
    # Typer renders each command as the first token of a panel row.
    names = set()
    for line in r.stdout.splitlines():
        m = re.match(r"^\s*│\s+([a-z][a-z0-9-]*)\s{2,}", line)
        if m:
            names.add(m.group(1))
    return names


@timed
def check_slash_commands_have_help_entries() -> Check:
    """Every shipped jsat-<name>.md needs a section AND a row in jsat-help.md."""
    help_md = COMMANDS_DIR / "jsat-help.md"
    if not help_md.exists():
        return Check("catalog_help_entries", "catalog", FAIL,
                     "jsat/commands/jsat-help.md is missing")
    help_text = help_md.read_text()
    names = sorted(p.stem.removeprefix("jsat-") for p in COMMANDS_DIR.glob("jsat-*.md")
                   if p.stem != "jsat-help")
    missing_section = [n for n in names if f"### {n}" not in help_text]
    missing_row = [n for n in names if f"| `{n}` |" not in help_text]
    problems = []
    if missing_section:
        problems.append(f"no '### <name>' block: {missing_section}")
    if missing_row:
        problems.append(f"no command-list row: {missing_row}")
    if problems:
        return Check("catalog_help_entries", "catalog", FAIL,
                     f"{len(set(missing_section) | set(missing_row))} of {len(names)} "
                     "slash commands are not documented in jsat-help.md",
                     detail="; ".join(problems),
                     remediation="add the missing block/row in jsat/commands/jsat-help.md")
    return Check("catalog_help_entries", "catalog", PASS,
                 f"all {len(names)} slash commands documented in jsat-help.md")


@timed
def check_slash_commands_match_skills_registry() -> Check:
    """`commands/*.md` and `_JSAT_SKILLS` are two registries of one catalog."""
    try:
        from jsat._cli_skills_data import _JSAT_SKILLS
    except Exception as e:
        return Check("catalog_skills_bijection", "catalog", FAIL,
                     f"could not import _JSAT_SKILLS: {e}")
    files = {p.stem.removeprefix("jsat-") for p in COMMANDS_DIR.glob("jsat-*.md")}
    files.discard("jsat-help")
    files.discard("help")
    keys = {k.removeprefix("jsat-") for k in _JSAT_SKILLS}
    keys.discard("help")
    only_files = sorted(files - keys)
    only_keys = sorted(keys - files)
    if only_files or only_keys:
        return Check("catalog_skills_bijection", "catalog", FAIL,
                     f"registries out of sync: {len(only_files)} command file(s) with "
                     f"no _JSAT_SKILLS entry, {len(only_keys)} entry(s) with no file",
                     detail=f"only_in_commands_dir={only_files} "
                            f"only_in_JSAT_SKILLS={only_keys}",
                     remediation="derive one from the other, or add the missing entries")
    return Check("catalog_skills_bijection", "catalog", PASS,
                 f"commands/*.md and _JSAT_SKILLS agree on all {len(files)} commands")


@timed
def check_slash_commands_reference_real_tools() -> Check:
    """A slash command that names a nonexistent jsat__ tool fails silently."""
    try:
        real = _registry_tool_names()
    except Exception as e:
        return Check("catalog_slash_tool_refs", "catalog", FAIL,
                     f"could not build the MCP registry: {e}")
    # Several command files deliberately name a tool in order to say it does
    # NOT exist ("there is no `jsat__run_app` MCP tool — use Bash"). That is
    # good documentation, not drift, so a reference inside a negation is not
    # a reference to call it.
    negation = re.compile(
        r"(there is no|does not exist|is not an? (?:mcp )?tool|not a tool|"
        r"no such tool|do not (?:literally )?call)", re.I)
    referenced: dict[str, set[str]] = {}
    for p in sorted(COMMANDS_DIR.glob("*.md")):
        text = p.read_text()
        for m in re.finditer(r"jsat__([a-z_][a-z0-9_]*)", text):
            window = text[max(0, m.start() - 160):m.end() + 160]
            if negation.search(window):
                continue
            referenced.setdefault(m.group(1), set()).add(p.name)
    bogus = {t: sorted(files) for t, files in referenced.items() if t not in real}
    if bogus:
        lines = [f"{t} (in {', '.join(f)})" for t, f in sorted(bogus.items())]
        return Check("catalog_slash_tool_refs", "catalog", FAIL,
                     f"{len(bogus)} jsat__* tool name(s) referenced by slash commands "
                     "do not exist in the MCP registry",
                     detail="\n".join(lines),
                     remediation="fix the tool name in the command file, or register "
                                 "the tool in mcp/server.py::_build_registry")
    return Check("catalog_slash_tool_refs", "catalog", PASS,
                 f"all {len(referenced)} distinct jsat__* references across the "
                 "slash commands resolve to real registered tools")


@timed
def check_every_tool_has_a_role() -> Check:
    """A tool absent from _ROLE_PERMISSIONS is admin-only by accident."""
    try:
        from jsat.mcp.server import _ROLE_PERMISSIONS
        real = _registry_tool_names()
    except Exception as e:
        return Check("catalog_rbac_coverage", "mcp_security", FAIL,
                     f"could not load the registry or role table: {e}")
    # `admin` is deliberately an empty frozenset meaning "unrestricted"
    # (resolved in _allowed), so it grants nothing explicitly and must be
    # excluded — the question is which tools NO named role can reach.
    granted: set[str] = set()
    for role, tools in _ROLE_PERMISSIONS.items():
        if role == "admin":
            continue
        granted |= set(tools)
    # Deliberately admin-only: import_index replaces the entire graph
    # database, so it is destructive in a way no other tool is. Anything
    # else missing from a named role is an oversight, not a policy.
    intentional_admin_only = {"import_index"}
    admin_only = sorted(real - granted - intentional_admin_only)
    if admin_only:
        return Check("catalog_rbac_coverage", "mcp_security", FAIL,
                     f"{len(admin_only)} tool(s) are in no role but admin, so a "
                     "viewer/developer token cannot call them",
                     detail=", ".join(admin_only),
                     remediation="add each to viewer or developer in _ROLE_PERMISSIONS")
    return Check("catalog_rbac_coverage", "mcp_security", PASS,
                 f"all {len(real)} registered tools are reachable by a named "
                 f"role, except {sorted(intentional_admin_only)} which are "
                 "admin-only by design")


@timed
def check_ci_setup_template_commands(jsat_bin: str, env: dict[str, str],
                                     tmp: Path | None = None) -> Check:
    """`jsat ci-setup` must not generate a workflow calling commands that
    do not exist — anyone who follows it gets broken CI."""
    import tempfile
    work = Path(tempfile.mkdtemp(prefix="jsat-cisetup-"))
    try:
        r = subprocess.run([jsat_bin, "ci-setup"], capture_output=True, text=True,
                           timeout=90, cwd=str(work), env={**env, "HOME": str(work)})
        generated = list(work.rglob("*.yml")) + list(work.rglob("*.yaml"))
        text = "\n".join(p.read_text() for p in generated) or r.stdout
        if not text.strip():
            return Check("ci_setup_commands_exist", "cli", UNAVAILABLE,
                         "jsat ci-setup produced no workflow to inspect",
                         detail=f"rc={r.returncode} stderr={r.stderr[:300]}")
        real = _cli_command_names(jsat_bin, env)
        called = set(re.findall(r"^\s*(?:-\s*)?jsat\s+([a-z][a-z0-9-]*)", text, re.M))
        called |= set(re.findall(r"run:\s*jsat\s+([a-z][a-z0-9-]*)", text))
        called.discard("")
        bogus = sorted(c for c in called if c not in real)
        if bogus:
            return Check("ci_setup_commands_exist", "cli", FAIL,
                         f"the generated CI workflow calls {len(bogus)} jsat command(s) "
                         "that do not exist",
                         detail=f"missing={bogus} generated_files="
                                f"{[p.name for p in generated]}",
                         remediation="add the commands, or fix the template in "
                                     "jsat/_cli_setup.py::cmd_ci_setup")
        return Check("ci_setup_commands_exist", "cli", PASS,
                     f"every jsat command in the generated CI workflow exists "
                     f"({len(called)} referenced)")
    finally:
        import shutil as _sh
        _sh.rmtree(work, ignore_errors=True)


@timed
def check_documented_cli_commands_exist(jsat_bin: str, env: dict[str, str]) -> Check:
    """Commands named in README/docs must exist in `jsat --help`."""
    real = _cli_command_names(jsat_bin, env)
    if not real:
        return Check("docs_cli_commands_exist", "docs", FAIL,
                     "could not parse any command names out of `jsat --help`")
    sources = [REPO_ROOT / "README.md", REPO_ROOT / "docs" / "cli-reference.md"]
    claimed: dict[str, set[str]] = {}
    for src in sources:
        if not src.exists():
            continue
        for m in re.finditer(r"^[ \t]*(?:\$ )?jsat +([a-z][a-z0-9-]*)",
                             src.read_text(), re.M):
            claimed.setdefault(m.group(1), set()).add(src.name)
    # Words that follow `jsat` in prose but are not commands.
    ignore = {"is", "and", "the", "with", "in", "to", "from", "on", "as", "for",
              "a", "an", "it", "you", "your", "will", "can", "or", "if", "at",
              "by", "of", "that", "this", "has", "have", "into", "when", "then",
              "not", "no", "all", "any", "so", "just", "only", "also", "does"}
    bogus = sorted(c for c in claimed if c not in real and c not in ignore)
    if bogus:
        lines = [f"{c} (in {', '.join(sorted(claimed[c]))})" for c in bogus]
        return Check("docs_cli_commands_exist", "docs", FAIL,
                     f"{len(bogus)} command(s) documented in README/docs do not exist",
                     detail="\n".join(lines),
                     remediation="add the command or correct the documentation")
    return Check("docs_cli_commands_exist", "docs", PASS,
                 f"every documented jsat command exists ({len(claimed)} checked)")


@timed
def check_changelog_has_current_version() -> Check:
    import re as _re
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    m = _re.search(r'^version\s*=\s*"([^"]+)"', pyproject, _re.M)
    if not m:
        return Check("changelog_current_version", "release", FAIL,
                     "could not read the version from pyproject.toml")
    ver = m.group(1)
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text()
    if f"[{ver}]" not in changelog:
        return Check("changelog_current_version", "release", FAIL,
                     f"CHANGELOG.md has no entry for the current version {ver}",
                     remediation=f"add a `## [{ver}]` section to CHANGELOG.md")
    return Check("changelog_current_version", "release", PASS,
                 f"CHANGELOG.md documents the current version {ver}")


@timed
def check_dead_module_not_shipped() -> Check:
    """mcp/tools.py is a second, drifted tool catalog that nothing imports.

    Shipping it is a trap: it reads like ground truth and is not.
    """
    tools_py = REPO_ROOT / "jsat" / "mcp" / "tools.py"
    if not tools_py.exists():
        return Check("dead_mcp_tools_module", "catalog", PASS,
                     "jsat/mcp/tools.py has been removed")
    importers = subprocess.run(
        ["grep", "-rln", "--include=*.py", "-e", "mcp.tools", "-e", "from .tools",
         "-e", "from jsat.mcp import tools", str(REPO_ROOT / "jsat")],
        capture_output=True, text=True)
    users = [ln for ln in importers.stdout.splitlines()
             if ln.strip() and not ln.strip().endswith("jsat/mcp/tools.py")]
    try:
        real = _registry_tool_names()
        from jsat.mcp.tools import MCP_TOOLS
        listed = {t.get("name") for t in MCP_TOOLS if isinstance(t, dict)}
        drift = len(real - listed)
    except Exception:
        drift = -1
    if not users:
        return Check("dead_mcp_tools_module", "catalog", FAIL,
                     "jsat/mcp/tools.py is imported by nothing but still ships "
                     f"(it lists {len(listed) if drift >= 0 else '?'} tools vs "
                     f"{len(real) if drift >= 0 else '?'} really registered)",
                     detail=f"tools missing from the dead catalog: {drift}",
                     remediation="delete jsat/mcp/tools.py")
    return Check("dead_mcp_tools_module", "catalog", PASS,
                 f"jsat/mcp/tools.py is imported by {len(users)} module(s)")


@timed
def check_skill_clusters_resolve() -> Check:
    """clusters.py must not reference skills that do not exist."""
    try:
        from jsat.skills.clusters import BUILT_IN_CLUSTERS
    except Exception as e:
        return Check("skill_clusters_resolve", "catalog", UNAVAILABLE,
                     f"could not import BUILT_IN_CLUSTERS: {e}")
    known = {p.stem.removeprefix("jsat-") for p in COMMANDS_DIR.glob("jsat-*.md")}
    try:
        from jsat._cli_skills_data import _JSAT_SKILLS
        known |= {k.removeprefix("jsat-") for k in _JSAT_SKILLS}
    except Exception:
        pass
    dangling: dict[str, list[str]] = {}
    for cluster, skills in BUILT_IN_CLUSTERS.items():
        missing = [s for s in skills if s not in known]
        if missing:
            dangling[cluster] = missing
    if dangling:
        return Check("skill_clusters_resolve", "catalog", FAIL,
                     f"{len(dangling)} skill cluster(s) reference skills that do "
                     "not exist, so running them is a no-op",
                     detail="; ".join(f"{c}: {m}" for c, m in dangling.items()),
                     remediation="fix the names in jsat/skills/clusters.py, or "
                                 "remove the clusters feature")
    return Check("skill_clusters_resolve", "catalog", PASS,
                 f"all {len(BUILT_IN_CLUSTERS)} skill clusters reference real skills")


@timed
def check_wheel_includes_commands() -> Check:
    """`jsat connect claude` installs slash commands from inside the package,
    so they must actually be in the built artifact."""
    import tomllib
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    include = (data.get("tool", {}).get("hatch", {}).get("build", {})
               .get("targets", {}).get("wheel", {}).get("include", []))
    if not any("commands" in str(i) for i in include):
        return Check("wheel_includes_commands", "release", FAIL,
                     "pyproject.toml does not include jsat/commands/*.md in the wheel",
                     remediation='add "jsat/commands/*.md" to '
                                 "[tool.hatch.build.targets.wheel].include")
    return Check("wheel_includes_commands", "release", PASS,
                 f"wheel build includes the slash commands ({include})")


def run(report: Report, jsat_bin: str, env: dict[str, str]) -> None:
    report.add(check_slash_commands_have_help_entries())
    report.add(check_slash_commands_match_skills_registry())
    report.add(check_slash_commands_reference_real_tools())
    report.add(check_every_tool_has_a_role())
    report.add(check_ci_setup_template_commands(jsat_bin, env))
    report.add(check_documented_cli_commands_exist(jsat_bin, env))
    report.add(check_changelog_has_current_version())
    report.add(check_dead_module_not_shipped())
    report.add(check_skill_clusters_resolve())
    report.add(check_wheel_includes_commands())
