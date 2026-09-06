"""
jsat._cli_skills_data — Static skill definitions and command writers.
"""
from __future__ import annotations

import re
from pathlib import Path

import structlog

_log = structlog.get_logger(__name__)

# ── Shared skill definitions (reused by Claude, Continue, and docs) ────────────

# Each entry: skill-name → (description, instruction)
# $ARGUMENTS is replaced by {input} for Continue's customCommands format.
# ── Shared skill definitions ──────────────────────────────────────────────────
#
# One source of truth: the shipped `jsat/commands/jsat-*.md` files. Each is
# `---\ndescription: <one-liner>\n---\n\n<instruction body>`, which is exactly
# the (description, instruction) pair the Claude, Continue and Bob writers
# need.
#
# This used to be a ~1,400-line hand-maintained dict duplicating those files
# verbatim, and the two drifted: ten command files had no entry here (so
# Continue and Bob users silently got a smaller command set than Claude
# users), while four stale entries wrote command files for commands that no
# longer existed. Deriving it removes that whole failure mode.
#
# $ARGUMENTS is replaced by {input} for Continue's customCommands format by
# the caller, not here.

_COMMANDS_DIR = Path(__file__).resolve().parent / "commands"

# The dispatcher itself, not a subcommand: `jsat.md` is generated, and
# `jsat-help.md` is a rendered index of everything else.
_NOT_SUBCOMMANDS = frozenset({"jsat", "jsat-help"})


def _parse_command_file(path: Path) -> tuple[str, str] | None:
    """Split a command file into (description, instruction).

    Returns None when the frontmatter is missing or has no description, so a
    malformed file is skipped rather than installed as an empty command.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    frontmatter, body = parts[1], parts[2]
    description = ""
    for line in frontmatter.splitlines():
        if line.strip().startswith("description:"):
            description = line.split(":", 1)[1].strip().strip('"').strip("'")
            break
    if not description:
        return None
    return description, body.lstrip("\n")


def _load_jsat_skills() -> dict[str, tuple[str, str]]:
    """Build the skill registry from the shipped command files."""
    skills: dict[str, tuple[str, str]] = {}
    if not _COMMANDS_DIR.is_dir():
        _log.warning("jsat_skills_commands_dir_missing", path=str(_COMMANDS_DIR))
        return skills
    for path in sorted(_COMMANDS_DIR.glob("jsat-*.md")):
        if path.stem in _NOT_SUBCOMMANDS:
            continue
        parsed = _parse_command_file(path)
        if parsed is None:
            _log.warning("jsat_skill_unparseable", file=path.name)
            continue
        skills[path.stem] = parsed
    return skills


_JSAT_SKILLS: dict[str, tuple[str, str]] = _load_jsat_skills()

# Appended to every generated command so the assistant delivers a real answer
# instead of stopping at raw tool output. Without this, some tools (especially
# ones that return an intermediate artifact like an optimized prompt or a JSON
# blob) get echoed verbatim, which reads as "just showing what the tool does".
_JSAT_CMD_DIRECTIVE = (
    "\n\nHOW TO RESPOND: Actually invoke the tool(s) described above, then reply "
    "with a direct, useful answer built from the result — interpret it for the "
    "user in plain language. Do not merely describe what the tool does, and do "
    "not echo raw JSON. If a tool returns an intermediate artifact (e.g. an "
    "optimized prompt), use it to finish the task rather than presenting it as "
    "the final answer."
)


def _write_jsat_skills(scope: str, commands_dir: Path | None = None) -> Path:
    """Write /jsat-* skill files so Claude Code can call JSAT tools via slash commands."""
    if commands_dir is None:
        if scope == "global":
            commands_dir = Path.home() / ".claude" / "commands"
        else:
            commands_dir = Path.cwd() / ".claude" / "commands"

    commands_dir.mkdir(parents=True, exist_ok=True)

    for name, (description, instruction) in _JSAT_SKILLS.items():
        skill_file = commands_dir / f"{name}.md"
        content = f"---\ndescription: {description}\n---\n\n{instruction}{_JSAT_CMD_DIRECTIVE}\n"
        skill_file.write_text(content, encoding="utf-8")

    return commands_dir


def _extract_flags_examples(body: str) -> tuple[str, str]:
    """Best-effort extraction of a command's flag list and Examples block from
    its own body text, so jsat-help.md's per-command cheat-sheet can be
    generated from the same source of truth every other artifact uses instead
    of being hand-duplicated (and silently drifting — see jsat-help.md's
    history: it once listed commands that no longer existed and omitted 9
    real ones, because it was a second, manually-maintained copy of content
    that already lived in each jsat-command.md file).

    This is heuristic, not a strict parser — command files are prose, not a
    fixed schema — so on ambiguous input it prefers omitting a flag/example
    over fabricating one. Getting the COMMAND LIST right (never stale, never
    a ghost entry) is the primary fix this enables; flag/example fidelity is
    a secondary best-effort nicety on top of that.
    """
    lines = body.splitlines()
    flag_lines: list[str] = []
    flag_line_re = re.compile(r"^--[A-Za-z]")
    for line in lines:
        stripped = line.strip()
        # A flag definition line is near-universally "  --name ... " or
        # "  --name <arg>   → description" across the whole catalog. Require a
        # letter immediately after "--" so this doesn't also match markdown
        # "---" dividers or prose that happens to use "--" as a dash (both
        # confirmed polluting the generated Flags block before this fix).
        if flag_line_re.match(stripped) and len(flag_lines) < 8:
            flag_lines.append("  " + stripped)
    flags_block = "\n".join(flag_lines) if flag_lines else "  (no flags — see /jsat <command> for full behavior)"

    examples_block = "(see /jsat <command> for usage)"
    # Find the LAST "Examples:" header (files sometimes have one earlier in a
    # flag's own description text) and take indented/arrow lines after it.
    last_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "examples:":
            last_idx = i
    if last_idx is not None:
        collected: list[str] = []
        for line in lines[last_idx + 1:]:
            if len(collected) >= 10:
                break
            if not line.strip():
                if collected:
                    break
                continue
            if line.startswith("#"):
                break
            if line.strip().startswith("/jsat") or line.strip().startswith("→") or line.startswith("  "):
                collected.append(line.rstrip())
                continue
            break
        if collected:
            examples_block = "\n".join(collected)
    return flags_block, examples_block


def _generate_help_body(skill_files: list, frontmatter_desc, strip_frontmatter) -> str:
    """Generate jsat-help.md's full content from the live skill_files list —
    this is now the single build artifact both jsat-help.md (standalone) and
    jsat.md's own "## help" section derive from, so the two can never disagree
    and neither can go stale relative to what commands actually exist.
    """
    lines: list[str] = [
        "---",
        "description: Show flags, params, and examples for any /jsat command. Usage: /jsat-help <command>",
        "---",
        "",
        "Parse $ARGUMENTS:",
        "- First word = COMMAND (e.g. `magic`, `crack`, `blast-radius`)",
        "- Everything after = ignored",
        "",
        "If $ARGUMENTS is empty: print the **Full Command List** table at the bottom of this file and stop.",
        "",
        "Otherwise find the matching `### <COMMAND>` section below and print its help block verbatim.",
        "Format the output as:",
        "",
        "```",
        "/jsat <COMMAND> [flags] <args>",
        "",
        "<one-line description>",
        "",
        "Flags:",
        "  <flag>  —  <what it does>",
        "  ...",
        "",
        "Examples:",
        "  <example>",
        "  ...",
        "```",
        "",
        "If COMMAND is not an exact match against a `### <COMMAND>` section, do NOT jump",
        "straight to \"Unknown command\" — a bare miss-list dump is only correct feedback",
        "when the user's input has nothing in common with any real command, and that is",
        "rarely why someone typed the wrong name. Two more likely cases first:",
        "",
        "1. RENAMED/MERGED COMMAND: commands get merged or renamed as JSAT evolves. Muscle",
        "   memory for an old name is common and deserves a redirect, not a dead end.",
        "   Maintain this alias table BEFORE falling back to fuzzy match — whenever a",
        "   command is folded into another, add its old name here (this table is",
        "   necessarily hand-maintained since a removed name has no live section to",
        "   introspect; unlike the command list below, it does NOT self-update — review",
        "   it whenever commands are merged):",
        "     think, reflect, audit, estimate  → folded into `ithinking` subcommands",
        "     token-budget                     → folded into `tokens --model`",
        "     knowledge-add                    → folded into `knowledge add`",
        "   If COMMAND matches one of these AND it is not ALSO a `### <COMMAND>` section",
        "   of its own below (check the live list first — this table can lag a moment",
        "   behind an intentional un-merge), print:",
        "   \"`/jsat <COMMAND>` was folded into `/jsat <successor>`. Showing that:\"",
        "   then print the successor's help block.",
        "",
        "2. TYPO / CLOSE MATCH: if COMMAND is not an exact section match and not a known",
        "   alias above, compare it against every command name in the Full Command List",
        "   table using a simple closeness heuristic (shares a long common substring,",
        "   edit distance of 1-2 characters, or a transposition). If exactly one close",
        "   match stands out, respond: \"Unknown command: <COMMAND> — did you mean",
        "   `/jsat <closest-match>`?\" and print that command's help block underneath, so",
        "   the user isn't forced into a second round trip.",
        "   If nothing is close enough to name with confidence, THEN fall back to plain",
        "   `Unknown command: <COMMAND>` plus the Full Command List — do not guess a match",
        "   you are not reasonably confident in, a wrong suggestion is worse than none.",
        "",
        "---",
        "",
        "### universal-flags",
        "Two flags work on EVERY /jsat command. Extract them from ARGS before routing to the subcommand,",
        "then pass as tool call arguments (_budget=N, _dashboard=True).",
        "```",
        "Universal flags (any command):",
        "  timeout=<N>     → soft time budget in seconds (notification-only; hard kill at 5×N)",
        "  dashboard=true  → open a real-time browser dashboard for this call",
        "  raw=true        → skip the default input-correction rewrite; use ARGS exactly as typed",
        "```",
        "",
        "---",
        "",
    ]
    for fpath in skill_files:
        short = fpath.stem.removeprefix("jsat-")
        if short == "help":
            continue  # this file itself — no self-referential detail section
        content = fpath.read_text(encoding="utf-8")
        desc = frontmatter_desc(content)
        body = strip_frontmatter(content)
        flags_block, examples_block = _extract_flags_examples(body)
        lines += [
            f"### {short}",
            desc,
            "```",
            f"/jsat {short} [flags] <args>",
            "",
            "Flags:",
            flags_block,
            "",
            "Examples:",
            examples_block,
            "```",
            "",
        ]

    lines += [
        "---",
        "",
        "## Full Command List",
        "",
        "| Command | One-line description |",
        "|---------|---------------------|",
    ]
    for fpath in skill_files:
        short = fpath.stem.removeprefix("jsat-")
        desc = frontmatter_desc(fpath.read_text(encoding="utf-8"))
        lines.append(f"| `{short}` | {desc} |")

    lines += [
        "",
        "Run `/jsat-help <command>` for flags and examples on any specific command.",
        "",
        "BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):",
        "  timeout=<N>     → override soft budget to N seconds (default varies per tool)",
        "  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)",
        "  raw=true        → skip the default AI input-correction rewrite for this call",
        "  ⏱ progress notification = still running (wait, skip, or split — AI decides)",
        "  ⏱ _slow in response = completed after budget (result is valid)",
        "  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)",
        "",
    ]
    return "\n".join(lines)


def _write_jsat_dispatcher(
    scope: str,
    commands_dir: Path | None = None,
    source_dir: Path | None = None,
) -> Path:
    """Write a single /jsat dispatcher sourced from the bundled jsat/commands/*.md files.

    Reads the actual skill files from jsat/commands/ so updates to those files are
    automatically reflected when 'jsat connect claude' is re-run.

    ``source_dir`` overrides where the bundled skill files are read from.
    ``jsat refresh`` passes a throwaway copy so rendering expected content never
    touches the installed package; the default is the shipped command files.
    """
    if source_dir is None:
        source_dir = Path(__file__).parent / "commands"
    if commands_dir is None:
        if scope == "global":
            commands_dir = Path.home() / ".claude" / "commands"
        else:
            commands_dir = Path.cwd() / ".claude" / "commands"

    commands_dir.mkdir(parents=True, exist_ok=True)

    # Remove any existing individual jsat-*.md files
    for old in commands_dir.glob("jsat-*.md"):
        old.unlink()

    # Locate the bundled skill files: jsat/commands/jsat-*.md
    skill_files = sorted(source_dir.glob("jsat-*.md"))

    def _frontmatter_desc(text: str) -> str:
        """Extract description: value from YAML frontmatter."""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("description:"):
                return line.removeprefix("description:").strip().strip('"')
        return ""

    def _strip_frontmatter(text: str) -> str:
        """Remove the leading ---...--- frontmatter block."""
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return text
        try:
            end = lines.index("---", 1)
            return "\n".join(lines[end + 1:]).lstrip("\n")
        except ValueError:
            return text

    # Regenerate jsat-help.md's SOURCE file from the live skill_files list before
    # anything else reads it. jsat-help.md used to be hand-maintained prose that
    # silently drifted from reality (it once documented deleted commands and
    # omitted new ones) — it is now a build artifact like jsat.md itself, so it
    # cannot go stale independently of the commands it describes.
    (source_dir / "jsat-help.md").write_text(
        _generate_help_body(skill_files, _frontmatter_desc, _strip_frontmatter),
        encoding="utf-8",
    )

    # Build help table
    lines: list[str] = [
        "---",
        "description: \"JSAT — /jsat <command> [flags] [args]. Type '/jsat help' for all commands.\"",
        "---",
        "",
        "Parse the first word of $ARGUMENTS as COMMAND; everything after is ARGS.",
        "Find the matching section below and execute its instructions, treating ARGS as $ARGUMENTS.",
        "If COMMAND is \"help\" or $ARGUMENTS is empty: print the command list and stop.",
        "",
        "## Universal input correction (apply BEFORE routing, on by default)",
        "",
        "Typed input is often rushed — typos, run-on phrasing, ambiguous pronouns. By",
        "default, clean up ARGS before routing to the subcommand:",
        "",
        "1. Skip this step entirely if ARGS contains `raw=true` (strip the flag, use the",
        "   rest of ARGS verbatim), OR if ARGS is / contains a LITERAL PAYLOAD that must",
        "   never be rewritten: a diff/patch block, a file path, a code block or inline",
        "   code, a git ref/SHA, a URL, or anything already inside a here-doc/quoted",
        "   block. Rewriting these silently corrupts the command — e.g. in",
        "   \"fix src/paymnet/service.py\" the misspelled PATH must stay intact; only",
        "   prose around a literal payload is fair game for correction.",
        "2. Otherwise, if the remaining ARGS look like free-form prose (not just a bare",
        "   flag+path invocation), call jsat__prompt_rewrite(prompt=ARGS) — this",
        "   corrects spelling/grammar and tightens phrasing without changing intent.",
        "   If it returns a string starting with \"[AI unavailable\", the AI backend is",
        "   down: silently proceed with the ORIGINAL ARGS un-rewritten. Do not surface",
        "   the raw error to the user for this step — a best-effort cleanup skipping",
        "   itself is not a failure worth interrupting the command for.",
        "3. If the rewrite succeeds and materially changes ARGS (not just whitespace),",
        "   route using the REWRITTEN text but tell the user what changed in one line:",
        "   \"📝 Interpreted as: <rewritten>\" — so a rewrite that guesses wrong intent is",
        "   immediately visible and correctable, not silently substituted.",
        "4. Never apply this to COMMAND itself (the first word) — that is matched",
        "   against the alias/fuzzy-match logic in the `help` section below, not rewritten.",
        "",
        "## Universal flags (apply to every command before routing)",
        "",
        "Before routing to any subcommand, scan ARGS for these flags and extract them.",
        "Set the following variables — they MUST be passed in EVERY jsat MCP tool call:",
        "",
        "  timeout=<N>   → _BUDGET = N (integer seconds).",
        "                  The tool fires an ⏱ progress notification when it exceeds N seconds",
        "                  (still running — decide to wait/skip/split). Force-killed at 5×N.",
        "                  Pass as _budget=_BUDGET in EVERY jsat MCP tool call.",
        "                  Example: /jsat crack timeout=300 redesign the auth flow",
        "                           → _BUDGET=300",
        "                           → jsat__crack(task='redesign the auth flow', _budget=300)",
        "                  If timeout= is absent, do NOT pass _budget at all.",
        "",
        "  dashboard=true  → _DASHBOARD = True, _DASHBOARD_SESSION = <COMMAND>.",
        "                    Opens ONE persistent tab (all tool calls share it) at",
        "                    http://localhost:7432/jsat/dashboard/<COMMAND>",
        "                    e.g. /jsat magic dashboard=true → …/dashboard/magic",
        "                    The tab stays open until the /jsat session finishes.",
        "                    Pass _dashboard=True AND _dashboard_session=<COMMAND>",
        "                    in EVERY jsat MCP tool call for this session.",
        "                    Example: /jsat blast-radius dashboard=true src/payment/",
        "                             → _DASHBOARD=True, _DASHBOARD_SESSION='blast-radius'",
        "                             → jsat__blast_radius(target='src/payment/',",
        "                                                  _dashboard=True,",
        "                                                  _dashboard_session='blast-radius')",
        "                    If dashboard=true is absent, do NOT pass _dashboard at all.",
        "",
        "  raw=true        → disables the Universal input correction step above for this",
        "                    call only. Use ARGS exactly as typed, no rewrite attempted.",
        "",
        "CRITICAL — tool call rule: ALWAYS use jsat__* MCP tools for every step.",
        "  NEVER use Bash, Read, Explore, WebSearch, or other native tools as substitutes.",
        "  jsat tools have graph access; native tools do not. This rule has no exceptions.",
        "",
        "After extracting universal flags, remove them from ARGS before passing to the subcommand.",
        "",
        "## Universal learning module (apply AFTER every command completes)",
        "",
        "Once the routed subcommand's own \"HOW TO RESPOND\" reply has been given, before",
        "ending the turn, spend one short pass asking: did this command surface anything",
        "worth remembering past this conversation? Most invocations will not — routine",
        "queries and clean results produce nothing new. Only act when something concrete",
        "was actually learned; do not fabricate a lesson to fill this section.",
        "",
        "1. Classify each candidate learning as one of:",
        "   PROJECT-SPECIFIC — a fact about THIS codebase/repo that would help a future",
        "     call in this project: a gotcha, a non-obvious dependency, a fix that",
        "     worked, a false-positive pattern to exclude next time, a convention",
        "     discovered by exploration. Examples: 'blast_radius flags all uses of",
        "     LegacyLogger as breaking — verified safe, exclude from future reports',",
        "     'PaymentService.retry has a 3-attempt cap enforced only in prod config'.",
        "   JSAT-SPECIFIC — a fact about JSAT'S OWN tools/skills misbehaving,",
        "     returning wrong data, using a stale parameter, or missing a capability",
        "     that this command needed. Examples: 'jsat__foo requires param X not Y',",
        "     'jsat__bar returns [AI unavailable] with no documented fallback for this",
        "     command'. This is feedback about JSAT itself, not about the user's repo.",
        "   NONE — nothing durable surfaced (the common case). Skip silently, do not",
        "     mention this module ran at all.",
        "",
        "2. For PROJECT-SPECIFIC learnings: call",
        "   jsat__knowledge_add(text=\"<the specific fact>\", category=\"project-learning\")",
        "   Keep `text` concrete and self-contained (a future reader has no access to",
        "   this conversation) — name the file/symbol/behavior, not \"this was tricky\".",
        "",
        "3. For JSAT-SPECIFIC learnings: call",
        "   jsat__knowledge_add(text=\"<the specific tool/skill gap>\", category=\"jsat-improvement\")",
        "   This is a durable backlog `/jsat improve` reads from later — it is NOT a bug",
        "   report filed anywhere public, just a local note. Do not attempt to patch",
        "   JSAT's own source from inside a routed command; that is `/jsat improve`'s job.",
        "",
        "4. If either call is made, add one line to the reply: \"🧠 Learned: <one-line",
        "   summary> (saved to <project knowledge base|jsat improve backlog>)\". If",
        "   knowledge_add itself returns an AI-unavailable error, note it was NOT saved",
        "   rather than silently dropping it — a failed save is worth one honest line.",
        "",
        "---",
        "## help",
        "",
        "| Command | Description |",
        "|---------|-------------|",
    ]
    for fpath in skill_files:
        short = fpath.stem.removeprefix("jsat-")
        desc = _frontmatter_desc(fpath.read_text(encoding="utf-8"))
        lines.append(f"| `/jsat {short}` | {desc} |")

    lines += ["", "---", ""]

    # Embed each skill file's body as a named section. Skip "help" — its
    # generated content (built above via _generate_help_body) is already
    # ~800 lines and has its own "## help" table section earlier in this
    # preamble; embedding it again here duplicated the whole file into
    # jsat.md a second time until this fix.
    for fpath in skill_files:
        short = fpath.stem.removeprefix("jsat-")
        if short == "help":
            continue
        content = fpath.read_text(encoding="utf-8")
        desc = _frontmatter_desc(content)
        body = _strip_frontmatter(content)
        lines += [
            f"## {short}",
            "",
            f"*{desc}*" if desc else "",
            "",
            body.rstrip(),
            "",
            "---",
            "",
        ]

    (commands_dir / "jsat.md").write_text("\n".join(lines), encoding="utf-8")

    # Also install jsat-help.md as a standalone command so /jsat-help <command>
    # works as a direct slash command (separate from the /jsat dispatcher).
    help_src = source_dir / "jsat-help.md"
    if help_src.exists():
        (commands_dir / "jsat-help.md").write_text(
            help_src.read_text(encoding="utf-8"), encoding="utf-8"
        )

    return commands_dir


def _write_codex_skill(
    skill_dir: Path | None = None,
    source_dir: Path | None = None,
) -> Path:
    """Write one global Codex skill that dispatches JSAT's bundled commands.

    Codex does not use Claude's `.claude/commands/` slash-command directory. Keep
    the Codex integration project-clean by installing a single user-level skill
    under `~/.codex/skills/jsat/SKILL.md`.

    ``source_dir`` overrides where the bundled skill files are read from; the
    default is the shipped command files. ``jsat refresh`` passes a throwaway
    copy so render-only inspection never touches the installed package.
    """
    if source_dir is None:
        source_dir = Path(__file__).parent / "commands"
    if skill_dir is None:
        skill_dir = Path.home() / ".codex" / "skills" / "jsat"

    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_files = sorted(source_dir.glob("jsat-*.md"))

    def _frontmatter_desc(text: str) -> str:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("description:"):
                return line.removeprefix("description:").strip().strip('"')
        return ""

    def _strip_frontmatter(text: str) -> str:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return text
        try:
            end = lines.index("---", 1)
            return "\n".join(lines[end + 1:]).lstrip("\n")
        except ValueError:
            return text

    def _codex_text(text: str) -> str:
        import re
        text = text.replace("by you, Claude", "by you, Codex")
        text = text.replace("Claude Code slash commands", "JSAT Codex commands")
        text = text.replace("Claude Code slash command", "JSAT Codex command")
        text = text.replace("Claude Code skill", "Codex skill")
        text = text.replace("Claude session", "Codex session")
        text = text.replace("`claude mcp list`", "your MCP client's server-list command")
        text = text.replace("Read tool", "a file read")
        text = text.replace("`jsat connect claude`", "`jsat connect codex`")
        text = text.replace("jsat connect claude", "jsat connect codex")
        # CLAUDE.md is Claude Code's per-project instructions file; AGENTS.md is
        # the equivalent convention for Codex-style agents (this repo's own
        # root file is AGENTS.md) — confirmed leaking untranslated into the
        # generated Codex skill before this fix (jsat-service-health-check.md).
        text = text.replace("CLAUDE.md", "AGENTS.md")
        text = re.sub(r"/jsat-([A-Za-z0-9_-]+)", r"$jsat \1", text)
        text = text.replace("/jsat ", "$jsat ")
        return text

    lines: list[str] = [
        "---",
        "name: jsat",
        "description: >-",
        "  JSAT command dispatcher for Codex. Use when the user writes `$jsat <command>`",
        "  or `@jsat <command>`, including `$jsat magic <task>`, `$jsat query`,",
        "  `$jsat blast-radius`, `$jsat security`, and other JSAT workflows.",
        "---",
        "",
        "# JSAT Codex Dispatcher",
        "",
        "This is the Codex-native JSAT dispatcher.",
        "",
        "When the user writes `$jsat <command> [flags] [args]`, parse the first word",
        "after `jsat` as COMMAND and everything after it as ARGS. If the user writes",
        "`@jsat <command> [flags] [args]`, treat it as the same command form.",
        "",
        "Do not delegate this request to another AI command or imported wrapper skill.",
        "Execute the routed command below using JSAT MCP tools and Codex's own normal",
        "capabilities.",
        "",
        "If COMMAND is `help` or no command was provided, print the command list and stop.",
        "If COMMAND is unknown, suggest the closest command from the list.",
        "",
        "CRITICAL: for every JSAT command step, call `jsat__*` MCP tools. Do not replace",
        "a JSAT graph query with shell search, file reads, web search, or generic reasoning.",
        "If no `jsat__*` tools are available, tell the user to run `jsat connect codex`",
        "and restart Codex.",
        "",
        "## Input correction (on by default)",
        "",
        "Before routing, if ARGS is free-form prose (not `raw=true`, and not a literal",
        "payload — a diff, file path, code block, git ref, or URL that must not be",
        "touched), call `jsat__prompt_rewrite(prompt=ARGS)` to fix spelling/grammar and",
        "tighten phrasing. If the result starts with `[AI unavailable`, proceed with the",
        "original ARGS silently — this is best-effort, not a blocking step. If the",
        "rewrite materially changes ARGS, route with the rewritten text and say",
        "`Interpreted as: <rewritten>` in one line so a bad guess is visible. `raw=true`",
        "skips this step for one call.",
        "",
        "Before routing, extract universal flags from ARGS and pass them to every JSAT",
        "MCP tool call:",
        "",
        "- `timeout=<N>`: pass `_budget=<N>`.",
        "- `dashboard=true`: pass `_dashboard=True` and `_dashboard_session=<COMMAND>`.",
        "- `raw=true`: skip the input-correction rewrite above for this call.",
        "",
        "## Learning module (after every command completes)",
        "",
        "After giving the routed command's reply, decide if anything durable was",
        "learned — most calls yield nothing new, so skip silently unless something",
        "concrete surfaced:",
        "",
        "- PROJECT-SPECIFIC (a fact about this repo worth keeping): call",
        "  `jsat__knowledge_add(text=\"<concrete fact>\", category=\"project-learning\")`.",
        "- JSAT-SPECIFIC (JSAT's own tool/skill misbehaved or was missing something):",
        "  call `jsat__knowledge_add(text=\"<concrete gap>\", category=\"jsat-improvement\")`",
        "  — this feeds `$jsat improve`'s backlog later; do not patch JSAT source here.",
        "",
        "If either call is made, add one line: `Learned: <summary> (saved to <project",
        "knowledge base|jsat improve backlog>)`.",
        "",
        "## Command List",
        "",
        "| Command | Description |",
        "|---------|-------------|",
    ]
    for fpath in skill_files:
        short = fpath.stem.removeprefix("jsat-")
        desc = _codex_text(_frontmatter_desc(fpath.read_text(encoding="utf-8")))
        lines.append(f"| `$jsat {short}` | {desc} |")

    lines += ["", "---", ""]

    for fpath in skill_files:
        short = fpath.stem.removeprefix("jsat-")
        if short == "help":
            continue  # same duplication as jsat.md — see the parallel fix there
        content = fpath.read_text(encoding="utf-8")
        desc = _codex_text(_frontmatter_desc(content))
        body = _codex_text(_strip_frontmatter(content))
        lines += [
            f"## {short}",
            "",
            f"*{desc}*" if desc else "",
            "",
            body.rstrip(),
            "",
            "---",
            "",
        ]

    (skill_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")
    return skill_dir


def _write_bob_commands(scope: str, commands_dir: Path | None = None) -> Path:
    """Write /jsat-* slash commands so Bob Shell can call JSAT tools.

    Bob reads markdown commands from .bob/commands/ (project) or ~/.bob/commands/
    (global); the filename becomes the command name. Bob uses shell-style
    argument placeholders, so the $ARGUMENTS used by the Claude skills is
    rewritten to $@ ("all arguments"), and an argument-hint is added when the
    command takes input.
    """
    if commands_dir is None:
        if scope == "global":
            commands_dir = Path.home() / ".bob" / "commands"
        else:
            commands_dir = Path.cwd() / ".bob" / "commands"

    commands_dir.mkdir(parents=True, exist_ok=True)

    def _yaml_dq(s: str) -> str:
        """Double-quote a value for YAML frontmatter. Bob parses frontmatter as
        strict YAML, so descriptions containing ':' etc. must be quoted."""
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    for name, (description, instruction) in _JSAT_SKILLS.items():
        body = instruction.replace("$ARGUMENTS", "$@") + _JSAT_CMD_DIRECTIVE
        # Menu descriptions read better with a plain word than the raw token.
        desc = description.replace("$ARGUMENTS", "arguments")
        hint = f"\nargument-hint: {_yaml_dq('<arguments>')}" if "$@" in body else ""
        content = f"---\ndescription: {_yaml_dq(desc)}{hint}\n---\n\n{body}\n"
        (commands_dir / f"{name}.md").write_text(content, encoding="utf-8")

    return commands_dir
