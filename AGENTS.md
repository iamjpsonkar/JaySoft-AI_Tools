# AGENTS.md — developing JSAT with an AI agent

Everything an AI agent needs to make a correct change to JSAT itself. Read this
before touching the code. It is written for you, not for end users — the README
describes what JSAT *does*; this describes how it is *built*.

**Verify before you trust.** Facts here were reviewed at JSAT 0.4.17
(2026-09-02). Counts drift. Re-derive anything load-bearing with `jsat index .`
and the MCP tools rather than quoting this file back at the user.

---

## 1. What JSAT is, in one paragraph

JSAT parses a codebase with tree-sitter into a persistent graph (functions,
classes, files, services, endpoints, tables, topics, and the edges between them),
then exposes that graph through three surfaces that share one core: a **CLI**
(`jsat …`), a **Python SDK** (`from jsat import JSAT`), and an **MCP server** that
any AI tool can call. Everything else — blast radius, security review, incident
investigation, test gaps — is a query over that graph plus, optionally, an LLM.

| | 0.4.17 |
|---|---|
| Python modules | 90 |
| CLI commands (top level) | 38 |
| MCP tools | 69 (`len(MCPServer(js)._registry)`) |
| Slash commands (`jsat/commands/jsat-*.md`) | 51 (50 + help) |
| CI-safe pytest result | 735 passed / 11 skipped / 34 deselected |
| Self-test result | `./scripts/jsat-selftest.sh` — ~230 checks across 12 suites |
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
  commands/           50 jsat-*.md slash commands shipped inside the package
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

**No-mocking black-box check**: `./scripts/jsat-selftest.sh` exercises the real
installed artifact — real CLI subprocesses, a real multi-language scratch repo with
real git history, the real MCP server over real stdio JSON-RPC, real connector files
on disk, and the built wheel installed into a clean virtualenv. Suites live in
`scripts/selftest/suites/`; `--list-suites` shows them, `--suite mcp,cli` runs a
subset, `--ci-safe` restricts to what needs no docker/LLM/services.

```bash
./scripts/jsat-selftest.sh                 # everything available here, no LLM cost
./scripts/jsat-selftest.sh --ci-safe       # no docker, no LLM, no external services
./scripts/jsat-selftest.sh --llm           # also make real AI provider calls
./scripts/jsat-selftest.sh --live-agent    # also drive a real headless claude agent
./scripts/jsat-selftest.sh --jobs 8        # up to 8 suites concurrently (default 4)
./scripts/jsat-selftest.sh --sequential    # one suite at a time, in-process
```

**Suites run in parallel by default.** Each suite executes in its own
subprocess with a private workspace (`tmp/ws-<suite>`, hence its own
`JSAT_DATA_DIR` / `JSAT_SESSIONS_DIR` / `JSAT_IMPROVE_DIR` / `JSAT_RUNTIME_DIR`)
under the shared tempdir, and `__main__._run_jobs_parallel` merges the per-suite
reports in `SUITES` order so the report is deterministic. This is what makes
concurrency safe: suites share only the read-only fixture repo and the parent's
base environment, so the suites that mutate global `os.environ` for in-process
SDK calls (sdk, improve, index) and the dashboard's fixed port 7432 are all
isolated. The `environment` suite, the fixture-repo build and the final
`check_no_state_leak` always run on the parent. `--sequential` restores the old
in-process one-suite-at-a-time run and is the mode to debug a suite in.
When you add a suite, wire it into `_run_suite_inline`'s dispatch table (one
entry covers both modes) and add it to `NEEDS_FIXTURE` if it indexes the repo.

Three things about it matter when you extend JSAT:

- **Coverage gates.** A new MCP tool, a new CLI command, or a new public SDK
  method makes the suite RED until it is actually exercised
  (`mcp_coverage_complete`, `cli_coverage_complete`, `sdk_coverage_complete`).
  That is deliberate — add the case in the same change.
- **Only third-party binaries are ever substituted.** Launcher and lifecycle
  checks put a recorder stub on `PATH` in place of `claude`/`codex`/… and then
  assert against the real argv and the real generated `--mcp-config`, because
  "did we invoke claude correctly" cannot be observed without a TTY otherwise.
  No JSAT code is stubbed anywhere.
- **`unavailable` is not `fail`.** A missing dependency (Ollama, docker, an API
  key, a CLI) is reported as `unavailable` with a remediation, never as a
  failure and never silently skipped. Assertions must be tight enough that a
  broken tool cannot pass as an empty result — several real bugs hid behind
  `predicate=lambda p: p is not None`.

Writes a JSON + Markdown report for an AI agent to triage.

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
   The same cwd-shadowing that hides this bug from a naive check ALSO means
   `local_test.sh`/`pytest -m` (always run `cd`'d to `$REPO_ROOT` first) resolve
   `import jsat` to the checkout regardless of which interpreter's site-packages
   is stale — so a green pytest run is still trustworthy even when `--doctor`
   (which deliberately checks from a neutral `/tmp` dir, unshadowed, to surface
   the true installed state) reports a stale non-editable copy for that same
   interpreter. The console script (`jsat` on PATH) has no such protection,
   though: invoking it does *not* put your repo's cwd on its `sys.path`, so it
   can genuinely run stale code even when both `--doctor` and pytest look
   fine, if `jsat` on PATH shebangs to a *different* interpreter than the one
   `--doctor` happened to check. `scripts/jsat-selftest.sh` checks the console
   script specifically (resolved from `sys.executable`'s own `bin/`, not a
   bare `shutil.which("jsat")`, which can silently pick a different
   environment's copy) for exactly this reason.

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

## 9. Known debt (reviewed at 0.4.17)

Everything in the 0.4.12 list has been resolved — see CHANGELOG 0.4.17. What
remains:

- **`mypy` is declared strict and is not enforced.** `pyproject.toml` sets
  `[tool.mypy] strict = true`, but `jsat/` has ~377 errors across 58 files and
  `ci.yml` runs only `ruff`. The self-test ratchets the count so it cannot
  grow (`MYPY_BASELINE` in `scripts/selftest/suites/packaging.py`) and reports
  the declaration/reality gap as a separate finding. Decide one way or the
  other: add mypy to CI and pay it down, or scope the config to what actually
  holds.
- **`_MinimalJSAT` (`_cli_setup.py`) is a second JSAT-shaped object.** The MCP
  server deliberately avoids a full `JSAT()` init for startup latency, so this
  shim re-implements a subset of the surface by hand. Every method added to
  `JSAT` that an MCP tool calls must be mirrored here — `import_archive` was
  missed exactly this way. A shared mixin would remove the class of bug.
- **`Service` / `Endpoint` / `Table` / `Topic` nodes are still not persisted.**
  The indexer never creates them; `mcp/server.py` infers services and
  endpoints heuristically at request time
  (`_infer_services_from_files`, `_infer_endpoints_from_functions`). So the MCP
  surface reports services while the SDK and `jsat query` see none on the same
  repo. Moving the inference into the indexer would make all three surfaces
  agree.
- **`skills/` (the YAML manifest registry) is still dormant.** `registry.run()`
  executes only `source.type == "script"` and JSAT ships no manifests, so
  `run_cluster` reports "not installed" for every step. The clusters are now
  correct as documented *orderings* (they name real commands); they are not an
  execution engine.
- **Embeddings and vector stores are implemented but unwired**, and now say so
  at the schema and in the docs. All retrieval is keyword/substring/Jaccard
  based. Wiring them is a feature, not a bug fix.
- **`graph.backend: neo4j` is partial by design.** Indexing, traversal, `edges()`
  and blast radius work; anything going through `query()` needs SQLite,
  because every tool call site emits SQLite SQL. It warns at construction.
- `mcp/server.py` remains the biggest cohesion problem (`_handle` is ~450
  lines juggling auth, RBAC, budgets, dashboards, metrics and error shaping).
  Run `/jsat cohesion`.

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

<!-- jsat-start -->
## JSAT — Codebase Intelligence Tools

JSAT is connected as an MCP server. The following tools are available for you to call automatically:

### Graph exploration
- `jsat__query` — answer any codebase question using the indexed graph
- `jsat__get_function` — look up a function by name (returns params, return type, complexity)
- `jsat__get_class` — look up a class (bases, method count, file)
- `jsat__list_services` — list all indexed services
- `jsat__list_endpoints` — list all API endpoints
- `jsat__trace_call_chain` — trace a call chain from a symbol
- `jsat__get_index_status` — graph node/edge counts

### Impact & safety
- `jsat__blast_radius` — trace downstream impact of a change (breaking/degraded/warning/safe)
- `jsat__security_review` — OWASP scan with severity grouping
- `jsat__validate_migration` — DB migration lock type + zero-downtime advice
- `jsat__get_api_diff` — API contract breaking-change detection

### Code quality
- `jsat__submit_for_review` — multi-model parallel code review
- `jsat__get_test_gaps` — find untested code paths
- `jsat__generate_unit_test` — generate a unit test for a function

### Knowledge & investigation
- `jsat__knowledge_query` — search the knowledge base (ADRs, runbooks)
- `jsat__investigate_incident` — root-cause hypotheses ranked by confidence
- `jsat__generate_runbook` — incident runbook for a service

### Prompt & token tools
- `jsat__prompt_optimize` — offline 6-agent prompt pipeline (zero LLM cost)
- `jsat__prompt_multi_agent` — 3 parallel LLM rewrite agents, picks best
- `jsat__token_count` — token count estimation
- `jsat__token_compress` — offline compression (whitespace, dedup, import collapse)
- `jsat__token_budget` — check budget against a model's context window

### Self-improvement
- `jsat__improve_status` — friction JSAT has recorded in itself (read-only)

## Reach for JSAT FIRST — this is not optional

This repository is indexed in a JSAT graph. The graph knows things grep and file
reading cannot: who calls what, what breaks downstream, which paths are untested,
which endpoints lack auth. **Use it before falling back to generic tools.**

Apply this rule on every turn, without being asked:

| The user asks… | Call this FIRST | Not this |
|---|---|---|
| "what does X do?" / "where is X?" | `jsat__query`, `jsat__get_function` | random grep |
| "what calls X?" / "what breaks if I change it?" | `jsat__trace_call_chain` | guessing |
| anything before an edit to shared code | `jsat__blast_radius` | editing and hoping |
| "is this secure?" / auth questions | `jsat__security_review` | eyeballing the code |
| "what should I test?" | `jsat__get_test_gaps` | writing tests blind |
| a DB migration | `jsat__validate_migration` | reading the SQL |
| "why did this break?" | `jsat__investigate_incident` | scanning git log |
| a big or risky design decision | `jsat__crack`, `jsat__ithinking_plan` | answering off the cuff |
| context is getting long | `jsat__token_compress` | truncating arbitrarily |

**Suggest JSAT proactively.** When a user is about to do something JSAT covers,
say so before they ask — e.g. "before that refactor, let me check the blast radius"
or "there's a `/jsat security` scan that would catch this class of bug".

Useful shell commands to recommend (they are not MCP tools):
- `jsat session list` / `jsat session resume` — resume an interrupted skill run
- `jsat note add "…"` / `jsat note search …` — capture and recall project knowledge
- `jsat improve` — let JSAT diagnose a problem it hit in itself and draft a fix
- `jsat index .` — refresh the graph after significant code changes

## After using a JSAT tool, say what it bought you

Every time you call a `jsat__*` tool, close the loop with ONE short line telling
the user what the graph gave you that they would otherwise have had to dig for.
Be concrete and honest — cite the actual numbers or names returned.

Good:
- "`jsat__blast_radius` found 12 downstream callers, 3 breaking — that's why I'm
  changing the signature additively instead."
- "`jsat__get_test_gaps` showed `refund()` has no test covering the timeout path,
  so I wrote that one first."
- "`jsat__query` answered this from the index in one call — no file hunting needed."

Avoid:
- Praising the tool for its own sake, or repeating this line when the tool
  returned nothing useful. If a tool added no value, say that plainly instead.

If the graph is empty or stale, tell the user to run `jsat index .` rather than
silently falling back to grep.

## When something breaks: pair JSAT with GitHub MCP

If a `github` MCP server is also connected (`jsat connect github`), use the two
together. JSAT knows what broke *in this codebase*; GitHub knows whether anyone
has hit it before. Neither is much use alone.

On any error, stack trace, or failing test the user shares:

1. **Locate it locally first** — `jsat__query` / `jsat__get_function` to find the
   code, `jsat__blast_radius` to see what else the fix would touch. Never open a
   GitHub issue about code you have not read.
2. **Check whether it is known** — search the GitHub MCP server for issues and PRs
   matching the exception type and the JSAT-internal frame (e.g.
   `IndexNotFound jsat/_core.py`). Report the issue number and status if you find
   one, and stop: the answer may already be there.
3. **Find what changed** — if it is a regression, use `jsat__get_recent_changes`
   for local commits and GitHub MCP to read the PR that introduced the change.
4. **Report only if genuinely new.** Run `jsat improve` to produce a bundle
   (diagnosis + patch + privacy-filtered issue body), then file the issue through
   GitHub MCP using `issue.md` from that bundle as the body.

Rules that are not optional:
- **Never paste raw errors, paths, or code from the user's project into GitHub.**
  A `jsat improve` bundle is already privacy-filtered; a raw traceback is not.
- **Search before filing.** Duplicate issues cost maintainers more than silence.
- **Ask before writing anything public** — creating an issue, comment, or PR is
  outward-facing and hard to undo. Reading is fine unprompted; writing is not.
<!-- jsat-end -->
