# AGENTS.md — developing JSAT with an AI agent

Everything an AI agent needs to make a correct change to JSAT itself. Read this
before touching the code. It is written for you, not for end users — the README
describes what JSAT *does*; this describes how it is *built*.

**Verify before you trust.** Facts here were reviewed at JSAT 0.4.12
(2026-08-19). Counts drift. Re-derive anything load-bearing with `jsat index .`
and the MCP tools rather than quoting this file back at the user.

---

## 1. What JSAT is, in one paragraph

JSAT parses a codebase with tree-sitter into a persistent graph (functions,
classes, files, services, endpoints, tables, topics, and the edges between them),
then exposes that graph through three surfaces that share one core: a **CLI**
(`jsat …`), a **Python SDK** (`from jsat import JSAT`), and an **MCP server** that
any AI tool can call. Everything else — blast radius, security review, incident
investigation, test gaps — is a query over that graph plus, optionally, an LLM.

| | 0.4.12 |
|---|---|
| Python modules | 85 |
| CLI commands (top level) | 33 |
| MCP tools | 69 (`len(MCPServer._build_registry(...))`) |
| Slash commands (`jsat/commands/*.md`) | 41 |
| CI-safe pytest result | 499 passed / 9 skipped / 32 deselected across 26 files |
| Graph of this repo | Run `jsat index .` and `jsat status` before relying on counts |

---

## 2. Repo map

```
jsat/
  cli.py              entry point; imports every _cli_* module for side effects
  _cli_common.py      the Typer `app`, sub-apps, shared helpers (_jsat, console, err)
  _cli_ai.py          jsat ai status|use|test|models
  _cli_connect.py     jsat connect <tool> — writes MCP configs + guidance files
  _cli_improve.py     jsat improve — self-improvement
  _cli_index.py       jsat index|status|doctor|export|import
  _cli_launchers.py   jsat claude|codex|cursor|… (open a tool with JSAT loaded)
  _cli_session.py     jsat session … and jsat note …
  _cli_setup.py       jsat init|disconnect|ci-setup|mcp-server|version
  _cli_skills_data.py _JSAT_SKILLS registry + slash-command writers  (~1,500 lines)
  _cli_tools.py       jsat query|short|crack|prompt|knowledge-ingest|…

  _core.py            the JSAT class — the SDK. Everything heavy is lazily imported.
  _models.py          ALL pydantic config + result models
  _config.py          config discovery/merge, jsat_data_dir(), setup_logging()
  _exceptions.py      JSATError + ~28 subclasses
  _sessions.py        resumable skill sessions (markdown format)
  _secrets.py         secret patterns + entropy (shared by security and improve)
  _call_context.py    thread-local checkpoint() for MCP progress events

  _ai/                provider adapters: claude_cli, bob_cli, codex_cli, anthropic,
                      openai, openai_compat, ollama, none + aliases.py (THE alias table)
  _graph/             sqlite.py (default), neo4j.py, lightgraph.py
  _parsers/           tree-sitter per language + manifest.py
  _cache/, _embed/    cache and embedding backends
  _improve/           self-improvement: _capture, _sanitize, _store
  mcp/                server.py (the real tool registry), dashboard.py, prometheus.py
  skills/             YAML skill manifests (largely dormant — see §9)
  tools/              the actual features: indexer, query, blast_radius, security,
                      incident, migration, contract, review, crack, knowledge,
                      improve, test_helper, token_optimizer, prompt_optimizer, …
  commands/           41 jsat-*.md slash commands shipped inside the package
```

**Where things really live:** `tools/` holds logic, `_cli_*` holds argument parsing
and presentation, `mcp/server.py` holds the MCP surface. A feature usually needs
all three plus tests.

---

## 3. The three surfaces, and how a call flows

```
jsat <cmd>  ─┐
             ├─►  jsat/_cli_*.py  ──►  JSAT (_core.py)  ──►  tools/<feature>.py
SDK JSAT()  ─┤                              │                      │
             │                              ├──► _graph/ (SQLite)  │
MCP client  ─┘                              └──► _ai/ (provider)   │
   └── mcp/server.py  ──────────────────────────────────────────────┘
```

- `JSAT.__init__` (`_core.py`) loads config, detects the system, pins paths, sets up
  logging, and primes the improve gates. It does **not** open the graph or the AI —
  those are lazy (`_get_graph()`, `_get_ai()`).
- `_get_ai()` never raises for a missing key: it substitutes `NoOpProvider`. But
  **`NoOpProvider.complete()` DOES raise `AIError`** (`_ai/none.py`). Always call
  `ai.is_available()` first, or wrap in try/except and degrade.
- MCP: `MCPServer._build_registry()` (`mcp/server.py`) returns one big dict
  `name -> {description, schema, handler}`. `_handle()` wraps every call with a soft
  budget, a hard kill at 5×, dashboard events, and metrics.

---

## 4. Extension cookbook

### Add a CLI command
```python
# in the matching jsat/_cli_*.py
from ._cli_common import _jsat, app, console, err

@app.command("mycmd", rich_help_panel="⚡  Tools")
def cmd_mycmd(arg: str = typer.Argument(...), repo: str = typer.Option(".", "--repo", "-r")):
    """One-line help.

    \b
    jsat mycmd example
    """
    from jsat.tools.mything import MyTool   # heavy imports go INSIDE the function
    js = _jsat(repo=repo)
```
Panels in use: `⚡  Tools`, `🔍  Graph & Index`, `🔧  Setup & Config`,
`🤖  AI Launchers`, `📦  Package` (note the two spaces). A **new** `_cli_*.py`
module must be imported in `jsat/cli.py`.

### Add an MCP tool
One entry in the dict returned by `_build_registry()` in `mcp/server.py`:
```python
"my_tool": {
    "description": "What it does and when to call it.",
    "schema": {"type": "object", "properties": {...}},
    "handler": lambda a: _ser(_my_tool_impl(js, a)),
},
```
Put real logic in a module-level `_my_tool_impl(js, args)` below the registry.
Optionally set `_TOOL_BUDGETS["my_tool"]`. **Add the name to `_ROLE_PERMISSIONS`**
(`viewer` / `developer`) or only `admin` can call it. Do not touch `mcp/tools.py` —
it is dead code. `_dashboard`/`_budget`/`_dashboard_session` are injected into every
schema and stripped before handlers see them; ignore them.

### Add a slash command
Drop `jsat/commands/jsat-<name>.md` (frontmatter with `description:`, then
instructions). It is auto-globbed into the `/jsat` dispatcher. Then **also**:
- add a `### <name>` block **and** a Full Command List row in `jsat/commands/jsat-help.md` (hand-maintained), and
- add a `_JSAT_SKILLS` entry in `_cli_skills_data.py` — `tests/test_bob_cli.py` asserts one Bob file per key.

### Add a config section
`_models.py`: a `BaseModel` with **every field defaulted** (mutable defaults via
`Field(default_factory=...)`, constrained strings via `Literal[...]`), then a field on
`JSATConfig`. Existing config files stay valid because everything defaults.

### Add an AI provider
Implement `AIProvider` (`_ai/__init__.py`), allow it in `_models.AIConfig.provider`,
register it in `get_ai_provider()`, add it to `detect_ai_providers()`, and add aliases
to `_ai/aliases.py` — that table is the single source of truth for the SDK, the
shell, and `jsat ai use`.

---

## 5. Conventions that are enforced

- **Lazy imports.** Module-level imports stay light; heavy ones go inside functions.
  This is why `jsat --help` is fast, and why a stale package breaks only at call time.
- **Errors degrade, they do not crash.** Tools catch per-model/per-agent failures and
  return partial results (see `tools/review.py:_call_model`, `tools/crack.py:_agent_turn`).
- **Never let telemetry break the caller.** `record_signal()` is wrapped in
  `except BaseException: pass` and returns `None`.
- **Line length 100.** Ruff config lives in `pyproject.toml`; CI runs the identical
  command (`ruff check jsat/ tests/`). Do not add inline `--select`/`--ignore`.
- **Type hints everywhere**; `from __future__ import annotations` at the top.
- Private modules are `_`-prefixed. Public API is what `jsat/__init__.py` exports.

---

## 6. Testing

```bash
./local_test.sh --install    # editable install + dev deps in every venv found
./local_test.sh --doctor     # environment check — RUN THIS FIRST
./local_test.sh              # lint + CI-safe tests (what CI runs)
./local_test.sh --all        # everything (needs Neo4j, Qdrant, Redis)
./local_test.sh --both       # run in every venv that has jsat
```

- Mark tests `@pytest.mark.ci` or CI will not run them (`-m ci`).
- Isolate state with `JSAT_IMPROVE_DIR`, `JSAT_SESSIONS_DIR`, `JSAT_DATA_DIR`
  (tmp_path fixtures). Never let a test touch `~/.jsat/`.
- Follow `tests/test_mcp_server.py` for style: small builders, `MagicMock` for JSAT.

---

## 7. Environment traps — every one of these cost real time

1. **A copied install shadowing your checkout.** `pip install -e .` can leave a real
   `site-packages/jsat/` directory. Your edits then do nothing, and it is invisible
   from the repo root because `python -c` puts **cwd on `sys.path[0]`** while console
   scripts do not. **Always verify from a neutral directory:**
   ```bash
   cd /tmp && python -c "import jsat; print(jsat.__file__)"
   ```
   If that is not your checkout, `pip uninstall -y jsat && pip install -e .`.
2. **Two venvs on different dependency versions.** typer ≥0.27 vendors click as
   `typer._click`, whose `UsageError` is a **different class** from `click.UsageError`.
   Catch both (`_cli_common._usage_errors()`). A test suite on typer 0.23 stays green
   while the installed CLI is broken. `pyproject.toml` caps `typer<0.28`, `click<9`.
3. **The MCP server is a long-lived process.** Reinstalling JSAT under it deletes the
   package it already imported; because imports are lazy it fails later with
   `No module named 'jsat.tools'`. **Restart the AI tool after any install.**
4. **The graph goes stale.** After adding files, `jsat index .` — otherwise every MCP
   answer is confidently out of date.
5. `.git/hooks/post-commit` currently has a bashism and prints a syntax error on every
   commit. Harmless; not yours to worry about unless you are fixing it.

---

## 8. Invariants you must not break

**Self-improvement privacy** (`_improve/_sanitize.py`) — JSAT records friction in
*itself* on users' private codebases:
- Only JSAT-internal data: package-relative frames, exception *type* names, tool
  names, versions, config *keys*. Never `str(exc)` — messages interpolate user paths.
- Anything not provably internal is **dropped, never redacted**. A second adversarial
  pass (`verify_clean`) re-checks every record *and every bundle file including AI
  output* for home dirs, usernames, secrets, and env-var values.
- **JSAT never patches its own installed source.** Patches are validated in a temp
  copy; all writes go through `_store._safe_write`, which refuses targets outside the
  improve store. Writing LLM output into the live package would execute unreviewed
  code with the user's privileges.

**Outward-facing actions need consent.** Opening issues/PRs, pushing, publishing —
ask first. `jsat improve --report` deliberately only *pre-fills* an issue; the human
presses Submit.

**Release** (`RELEASING.md`): bump `pyproject.toml` **and** `jsat/__init__.py`
together — `publish.yml` validates the tag against pyproject and pushing `v*`
publishes to PyPI, which is effectively permanent.

---

## 9. Known debt (reviewed at 0.4.12)

- `mcp/tools.py` — a 47-entry `MCP_TOOLS` list nothing imports. Dead.
- `skills/` — YAML skill registry; only `source.type == "script"` actually executes,
  and `clusters.py` references skills that do not exist.
- `_cli_skills_data.py` (~1,500 lines) and `mcp/server.py` (`_handle` complexity 52,
  `cmd_disconnect` 49) are the biggest cohesion problems. Run `/jsat cohesion`.
- `jsat ci-setup` generates a workflow calling `jsat blast-radius`,
  `jsat contract-check`, `jsat security-review` — **none of which exist as CLI
  commands**. Fix the template or add the commands.
- Two parallel skill registries (`jsat/commands/*.md` and `_JSAT_SKILLS`) that must be
  kept in sync by hand.

---

## 10. Working on JSAT with JSAT

JSAT indexes itself. Use it:

```bash
jsat index .                      # refresh first — always
```
| Question | Tool |
|---|---|
| Where is X? | `jsat__get_function`, `jsat__get_class`, `jsat__query` |
| What breaks if I change it? | `jsat__blast_radius`, `jsat__trace_call_chain` |
| What is untested? | `jsat__get_test_gaps` |
| Why did this break? | `jsat__investigate_incident`, `jsat__get_recent_changes` |
| Big design decision | `jsat__crack`, `jsat__ithinking_plan` |
| What has JSAT hit in itself? | `jsat__improve_status`, then `jsat improve` |

Resume interrupted work with `jsat session list` / `jsat session resume`, and record
what you learn with `jsat note add "…"` so the next agent inherits it.

---

## 11. Resolving errors with the GitHub MCP server

`jsat connect github [tool]` wires GitHub's MCP server in beside JSAT, so an agent
can turn a local failure into a resolved issue. JSAT knows what broke *here*; GitHub
knows whether anyone has hit it before.

```bash
jsat connect github                  # Docker image, Claude Code, this repo
jsat connect github cursor --global  # Cursor, all projects
jsat connect github --remote         # GitHub's hosted endpoint, no Docker
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...   # `repo` scope; `read:org` to search orgs
```
Only the **variable name** is written into the config (`${GITHUB_PERSONAL_ACCESS_TOKEN}`);
the token itself is expanded by the MCP client at run time and never touches disk.

**The loop, in order:**
1. **Locate it locally** — `jsat__query` / `jsat__get_function`, then `jsat__blast_radius`.
   Never file an issue about code you have not read.
2. **Check whether it is known** — search GitHub issues/PRs for the exception type plus
   the JSAT-internal frame (`IndexNotFound jsat/_core.py`). If it exists, report the
   number and stop.
3. **Find what changed** — `jsat__get_recent_changes` locally; read the offending PR
   through GitHub MCP.
4. **Report only if new** — `jsat improve` produces a privacy-filtered bundle
   (`analysis.md`, `patch.diff`, `issue.md`); file the issue using `issue.md` as the body.

**Rules:** never paste raw tracebacks, paths, or user code into GitHub — a bundle is
filtered, a traceback is not. Search before filing. Reading is fine unprompted;
**creating an issue, comment, or PR is outward-facing — ask the human first.**

---

## 12. Checklist before you say you are done

- [ ] `cd /tmp && python -c "import jsat; print(jsat.__file__)"` → your checkout
- [ ] `./local_test.sh` green (lint + tests, same as CI)
- [ ] New tests marked `@pytest.mark.ci`, state isolated to tmp dirs
- [ ] All surfaces updated: CLI + MCP registry + RBAC + slash command + `_JSAT_SKILLS` + `jsat-help.md`
- [ ] `README.md`, `docs/`, and `CHANGELOG.md` (`[Unreleased]`) updated
- [ ] Counts in docs still correct if you added a command or tool
- [ ] Restarted the AI tool if you reinstalled (the MCP server holds a stale import)
- [ ] Nothing outward-facing (push, tag, issue, PR) without asking
