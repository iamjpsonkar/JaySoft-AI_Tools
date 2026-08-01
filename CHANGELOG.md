# Changelog

All notable changes to JSAT.

## [Unreleased]

## [0.4.6] — 2026-08-01

### Added

- **Single-tab session tree dashboard** — `dashboard=true` now opens ONE persistent
  browser tab per `/jsat` command at `http://localhost:7432/jsat/dashboard/<command>`
  (e.g., `/jsat crack ... dashboard=true` → `localhost:7432/jsat/dashboard/crack`).
  All tool calls in the session stream into the same collapsible tree; sub-calls nest
  under their parent. Previously opened a new tab per tool call.
- **Dashboard landing page** at `http://localhost:7432/jsat/dashboard` — lists all active
  and recently completed sessions with links. Auto-refreshes every 5 s. Bookmark this to
  always find what's running without knowing the session name.
- **Crack agent full text in dashboard** — when `/jsat crack dashboard=true` is used,
  the complete response from every war room agent (architect, security, implementer,
  tester, skeptic, moderator) appears in the dashboard tree in blue, not just a 120-char
  preview. Final synthesis also shown in full.
- **`dashboard_only(label, event_type)`** in `jsat/_call_context.py` — push an event to
  the dashboard only, without adding to the timeout event log. Used for large text that
  would be noisy in timeout messages (agent responses, synthesis outputs).
- **`_dashboard_session` MCP param** — groups all tool calls from one `/jsat` command
  into one tab. Handled automatically by skill files; no manual action needed.
- **Idle watcher** — background thread fires `session_done()` after 30 s of no active
  calls so the session closes cleanly without an explicit signal from skills.
- **`jsat/mcp/dashboard.py`** — complete session tree redesign. `_DashboardSession` /
  `_CallNode` data model; module-level singleton server (stays alive across sessions);
  backward-compat redirects `/events` → `/jsat/events`, `/dashboard/session/<x>` →
  `/jsat/dashboard/<x>`.
- **`jsat/_call_context.py`** — extracted from `server.py` to avoid circular imports.
  Contains `_call_ctx` (thread-local), `checkpoint()`, and the new `dashboard_only()`.
- Dashboard color-coding: 🟡 amber checkpoints, 🟢 green results, 🔵 blue agent
  responses (`agent_response` CSS class, pre-wrap with left-border indent), 🔴 red
  errors, 🟠 orange over-budget warnings.
- **`JSAT_DASHBOARD_PORT`** env var to override the default port `7432`.
- All 40 command skill files updated with `_dashboard_session` carry-through rules and
  correct dashboard URL format.
- **Docs overhaul**: README, `docs/claude-integration.md`, `docs/cli-reference.md`, and
  `docs/tools.md` all updated to reflect the new single-tab URL, session lifecycle, tree
  UI, landing page, and crack agent text.

### Fixed

- Resolved all ruff lint errors (E501, I001, F541, SIM105, SIM102, F401) across 17 files.
- Added `per-file-ignores` for template-string files (`_cli_skills_data.py`) and inline
  HTML/CSS/JS generation (`dashboard.py`, `server.py`) to avoid spurious E501 warnings.
- Added `.git/hooks/pre-push` to run `ruff check jsat/` before every push.

## [0.4.5] — 2026-08-01

### Changed

- **MCP budget = soft notification threshold, not a hard kill** (`jsat/mcp/server.py`):
  Tool time budgets (`_TOOL_BUDGETS`, `_DEPTH_BUDGETS`) now trigger an `⏱` MCP progress
  notification to the AI when exceeded — the tool call **keeps running**. A hard safety-net
  timeout fires at 5× the soft budget and is the only thing that force-kills a call.
  AI receives: which tool is slow, elapsed time, last progress events, and a suggested remedy.
  AI decides: wait / skip / split / optimize — on its next turn.
- `_timeout_response` renamed to `_hard_timeout_response`; result key changed from `_timeout`
  to `_hard_timeout` to distinguish hard kills from soft-budget notifications.
- Added `_monitor_budget` background thread per tool call: polls until budget or call completion,
  then fires `_notify` exactly once with context, then exits.
- Slow-completed calls (finished after soft budget) annotate the result with `_slow=True`,
  `elapsed_s`, `budget_s` so AI can factor in the delay without it being an error.
- Slash command guidance updated in all affected command files (`jsat-magic`, `jsat-query`,
  `jsat-cohesion`, `jsat-incident`, `jsat-test-gaps`, `jsat-coverage`) to explain
  `⏱ notification` vs `⛔ hard timeout` semantics.

## [0.4.4] — 2026-08-01

### Added

- **`/jsat-help` slash command**: lists all 39 commands with one-liners when called with
  no args; `/jsat-help <command>` shows full description, flags, and examples for that command.
  Installed as a standalone `jsat-help.md` file alongside the `/jsat` dispatcher.
- `_write_jsat_dispatcher` now writes `jsat-help.md` as a separate file after building
  `jsat.md`, ensuring `/jsat-help` survives the dispatcher's glob-delete step.
- `jsat connect claude` and `jsat connect bob` automatically set `JSAT_MCP_ALLOW_INSECURE=1`
  in the MCP server environment so local dev works without manual env var setup.

### Changed

- MCP server default reverted to **warn-but-allow** (open access with startup warning) when
  no auth env vars are set. Auth is only enforced when `JSAT_MCP_TOKEN` or
  `JSAT_MCP_TOKEN_ROLES` is explicitly configured. This restores local/single-user dev
  connectivity that the v0.4.3 fail-closed change broke.

### Fixed

- CI ruff I001 (import sort) and F821 (undefined names) in all 7 new `_cli_*` modules
  introduced by the cli.py split.

## [0.4.3] — 2026-08-01

### Security

- **MCP server RBAC fail-closed** (`jsat/mcp/server.py`): The server previously allowed all
  tool calls to proceed unauthenticated when neither `JSAT_MCP_TOKEN` nor
  `JSAT_MCP_TOKEN_ROLES` was set. This exposed `list_secrets`, `validate_migration`,
  `knowledge_add`, `index_repo`, and all other tools to unauthenticated callers by default.
  The server now fails closed: all tool calls (except `initialize`/`notifications/initialized`)
  are rejected with HTTP-equivalent 401 when no auth is configured.
  **Migration**: set `JSAT_MCP_ALLOW_INSECURE=1` to restore the previous open behaviour
  (local/single-user dev only), or configure `JSAT_MCP_TOKEN` or `JSAT_MCP_TOKEN_ROLES`.
- Moved `_auth_token` initialization from `run()` into `__init__()` for consistency with
  `_token_roles`; both auth mechanisms now initialized at server construction time.
- Startup log clearly reports auth mode: `mcp_auth_enabled`, `mcp_rbac_enabled`,
  `mcp_auth_insecure` (with warning), or `mcp_auth_unconfigured` (error).

### Changed

- **Split `jsat/cli.py` (4,416 lines) into 8 focused modules** for maintainability:
  `_cli_common.py` (app objects + shared utils), `_cli_skills_data.py` (skill definitions),
  `_cli_launchers.py` (AI launcher commands), `_cli_connect.py` (connect subcommands),
  `_cli_ai.py` (AI provider management), `_cli_tools.py` (tool commands),
  `_cli_index.py` (graph/index commands), `_cli_setup.py` (setup/config/package).
  `jsat/cli.py` is now a 22-line entrypoint. Pure refactoring — no behaviour change.

### Added

- **`tests/test_mcp_server.py`**: 17 new tests covering `_allowed()` role/permission matrix,
  fail-closed default rejection, `JSAT_MCP_ALLOW_INSECURE=1` opt-in, legacy single-token
  auth (correct/wrong/empty token), RBAC token-roles (known/unknown token, viewer blocked
  from `list_secrets`), and malformed JSON in `JSAT_MCP_TOKEN_ROLES` (graceful degradation).

## [0.4.2] — 2026-07-31

### Added

- **Session + actions files for big skills** (`magic`, `crack`, `sprint`, `prompt`):
  Every major skill now writes a session checkpoint file (`~/.jsat/sessions/<skill>-<slug>.md`)
  for `--continue` resume, and an actions file (`~/.jsat/sessions/<skill>-actions-<slug>.md`)
  at synthesis time. The actions file is immediately executed in sequence — the skill
  recommends and acts, not just recommends.
- **`jsat-magic`** session + actions files: `--continue` resumes interrupted runs;
  actions file auto-executes synthesis recommendations.
- **`/jsat` single dispatcher**: All 39 skill files consolidated from individual
  `~/.claude/commands/jsat-*.md` into one `~/.claude/commands/jsat.md` with `## <command>`
  sections. Eliminates command palette pollution.

### Fixed

- **False-positive secret detection** (`jsat/tools/security.py`): Entropy threshold raised
  from 4.5 → 4.8, minimum token length raised from 20 → 24 characters. Eliminates
  false-positive alerts on CLI skill instruction text, test fixtures, and rich markup.
- **`.claude` worktrees polluting graph index** (`jsat/_models.py`): Added `".claude"` to
  the default `exclude_patterns` in `IndexerConfig`. Agent worktrees created by Claude Code
  during parallel tasks no longer appear in test-gaps, security scan, or cohesion reports.
- **Lint (ruff I001)**: Added missing blank line between `import shutil` and
  `from jsat._config import jsat_data_dir` at two locations in `cli.py`.

### Changed

- **`jsat-crack`** default phases: N=6 (one agent per phase for maximum granularity).
  Phase 5 (Skeptic) now explicitly challenges Phase 1 (Architect) and Phase 3 (Implementer)
  by name rather than giving generic concerns.
- **`jsat-prompt`** default phases: N=6. Phase 1 Discuss step now classifies query type
  (structural/lookup/security/incident/coverage/general) and selects primary tool before
  optimizing.

## [0.4.1] — 2026-07-31

### Added

- **`jsat-magic`** — AI-orchestrated skill composer. Analyzes any task, composes a
  minimal-but-sufficient skill sequence from all 39 skills using a 6-layer dependency
  model (context → discover → analyze → plan → execute → verify → record), executes
  adaptively, and converges when the task is answerable. Flags: `--depth quick/standard/deep`,
  `--preview`, `--budget N`, `--service <name>`.
- **`jsat-plan`** — Pre-implementation planning gate. Six forcing questions + three
  review perspectives (scope, architecture, security) before any code is written.
  Backed by `jsat__ithinking_audit_assumptions`, `jsat__blast_radius`, `jsat__get_auth_coverage`.
- **`jsat-decide`** — Architectural decision journal. `log`, `list`, `search`, and
  `context` subcommands backed by the JSAT knowledge base (category="decision").
  `context <file>` surfaces relevant decisions via blast-radius cross-reference.
- **`jsat-sprint`** — Seven-stage delivery workflow: Think → Plan → Build → Review →
  Test → Ship → Reflect. `--stage N` resumes mid-sprint. `--dry` previews the plan.
  Final output includes ship readiness and decisions worth logging.
- **`jsat-cohesion`** — Code health analysis. Flags files > 800 lines, functions with
  cyclomatic complexity > 10, and classes with > 15 methods. Cross-references with
  blast-radius to surface the highest-impact refactoring targets first.

### Fixed

- **Shell injection** (`cli.py`, `jsat index --watch`): `shell=True` with unquoted `target`
  path replaced with two `subprocess.Popen` calls connected by pipe. `find`'s `-o` is a
  find operator, not a shell operator — no shell needed. Injection surface eliminated.
- **Timing oracle** (`mcp/server.py`): MCP auth token comparison replaced with
  `hmac.compare_digest` (constant-time). Previously `!=` leaked timing information
  proportional to the matching prefix length.
- **`SQLiteGraph.nodes_by_label` missing**: `jsat__list_services` failed with
  `AttributeError: 'SQLiteGraph' object has no attribute 'nodes_by_label'`. Added the
  method via `execute_sql("SELECT ... WHERE label=?", [label])`.

## [0.4.0] — 2026-07-31

### Added

- **`jsat-aw` — Workflow advisor**: classifies tasks (feature/bugfix/security/understand/incident/refactor/review) and runs the optimal JSAT tool sequence end-to-end. `--dry` shows the plan without running. `--type` forces a specific workflow.
- **`jsat-lazy` — Reuse-first planning**: 5-rung ladder checks the indexed graph for existing implementations before suggesting new code. `--audit` scans diffs for over-engineering. `--review` checks proposals for duplication.
- **`jsat-smart` — Terse mode**: fragment-based answers with filler stripped. Three levels: `--lite` (~30%), `--full` default (~55%), `--ultra` (~70%).
- **`jsat-crack` phased mode**: N=6 default (one agent per phase). Artifact carry-forward — each agent receives all prior findings as context. Phase 0 loads codebase context. Mid-sprint brief after Phase 3. Skeptic (Phase 5) specifically challenges architect + implementer conclusions.
- **`jsat-prompt` Discuss→Verify pipeline**: Phase 1 classifies query type and selects the right primary tool (trace/lookup/security/incident/coverage/general). Phase 5 spot-checks concrete claims against the graph (✅ verified / ⚠️ unverified).
- **`/jsat` single dispatcher**: `jsat connect claude` now installs one `jsat.md` dispatcher instead of 34 individual `jsat-*.md` files. All skills accessible via `/jsat <subcommand>`. Skill files bundled in `jsat/commands/` and sourced at connect time.

### Improved

- **Indexer performance**: SQLite PRAGMAs (`synchronous=NORMAL`, 64 MB page cache, 256 MB mmap); incremental deletion batched to 3 queries regardless of N changed files; edge resolution reduced from 2N queries to 3 (in-memory name→id map + bulk `executemany`); batch size 500→2000.
- **`jsat --help`**: 5 labeled command panels (Setup & Config, Package, Graph & Index, AI Launchers, Tools); rich markup; quick-start block with `/jsat` examples; expanded docstrings for `doctor`, `export`, `import`, `update`, `version`.
- **31 skill instructions improved**: `--service`, `--since`, `--depth`, `--limit`, `--model`, `--severity`, `--category` flags added across all skills; timeout recovery guidance; large-repo chunking strategies; better output format instructions.
- **`jsat-crack` role prompts enriched**: each agent grounded in codebase context with instructions on what to look for; history truncation 400→1200 chars; ContextAgent tokens 1500→3000.
- **10 Python tool quality improvements**: enriched role prompts (`crack.py`), richer context with function parameters and docstrings (`query.py`), CVE lookup via osv.dev + regex secret detection with file/line (`security.py`), function-level coverage (`test_helper.py`), real author-file frequency scoring (`incident.py`), ORM issue detection for Django migrations (`migration.py`), structural breaking-change detection (`contract.py`), SQLite query syntax fix + grounded prompts (`feature.py`), better extraction and synthesis prompts (`knowledge.py`), checklist-based review prompt (`review.py`).
- **`prompt_optimizer.py`**: LLM rewrite agents now receive `context_nodes` (was computed but never sent to AI); offline-optimized → "offline-optimized" spelling.
- **Sub-app help**: `connect`, `ai`, and `skills` Typer apps have expanded descriptions with quick-setup examples.

### Fixed

- `feature.py`: replaced Neo4j `MATCH (n:Service) RETURN n` syntax with SQLite-compatible `SELECT ... WHERE label = 'Service'`.
- `test_helper.py`: fixed Neo4j `MATCH (n:Endpoint) RETURN n` in `_untested_endpoints`; improved `_has_test` to match `test_foo.py`, `foo_test.py`, and `foo.py` patterns.
- `blast_radius.py`: `visited` set was created but its value discarded (`set(start_ids)` result not assigned), causing BFS to potentially visit the same node multiple times.
- `GraphClient.query()` type signature: now accepts `list[Any] | dict[str, Any] | None`; implementation already handled list params but the annotation said `dict | None`.
- `knowledge.py` re-ranking: "Favour" → "Favor", "Penalise" → "Penalize" (American English consistency).
- `crack.py`: "synthesises" → "synthesizes", "Analyse" → "Analyze".
- `prompt_optimizer.py`: "behaviour" → "behavior", "optimised" → "optimized", duplicate "analyse" removed from keyword list.

## [0.3.10] — 2026-07-29

### Fixed

- **`jsat index` now stores `index-manifest.json` and `INDEX.md` in the global
  data directory** (`~/.jsat/<hash12>/`) instead of `{repo}/.jsat/`. Previously
  the indexer hardcoded `Path(path) / ".jsat"`, creating a local `.jsat/`
  directory even on new setups, which then triggered the backward-compat check
  in `jsat_data_dir()` and permanently locked the repo to the local dir.
- **`jsat_data_dir()` backward-compat tightened** — only falls back to
  `{repo}/.jsat/` if a graph database, vector store, or config file exists
  there. A lone `index-manifest.json` or `INDEX.md` is no longer enough to
  override the global dir.

## [0.3.9] — 2026-07-29

### Changed

- Documentation fully updated for v0.3.8 global data dir and `--global` flag:
  README, `docs/configuration.md`, `docs/getting-started.md`,
  `docs/cli-reference.md` (new `jsat connect bob` section),
  `docs/ai-integrations.md`, `docs/ai-providers.md`.

## [0.3.8] — 2026-07-29

### Added

- **Global data directory** — JSAT runtime state (graph, cache, vectors, prompt history,
  system profile) now lives in `~/.jsat/<hash12>/` by default instead of `{repo}/.jsat/`.
  This keeps every project's git tree clean. Existing setups with a local `.jsat/` directory
  are auto-detected and kept working (backward-compatible).
  Override with the `JSAT_DATA_DIR` env var for custom paths or CI environments.
- **`--global` flag** on `jsat init`, `jsat ai use`, `jsat connect claude`,
  `jsat connect codex`, and `jsat connect bob`. A single flag installs to the
  global config path and global AI tool config (e.g. `~/.claude/settings.json`,
  `~/.codex/`, `~/.bob/`) so JSAT works across all projects without any per-repo setup.
- **Global JSAT config** at `~/.jsat/config.yaml` — `load_config` now checks this path as
  a fallback, so `jsat init --global` + `jsat ai use --global` configure JSAT once for all
  projects on the machine.

## [0.3.7] — 2026-07-29

### Fixed

- **Bob `stream()` no longer silently yields nothing.** The previous implementation
  assumed Anthropic's `content_block_delta` event format for `--output-format stream-json`.
  Bob Shell uses IBM's own NDJSON format — different field names, different event types.
  Replaced with a generic content extractor that checks `content`, `result`, `text`, and
  `delta.text` in order, falling back to raw lines for unrecognised formats.
- **Bob `complete()` JSON response handling is now explicit.** If Bob returns a JSON
  envelope without a `result` key, the original text is preserved (not silently dropped).
  Session ID extraction and result unwrapping are now logged at DEBUG level.
- **`jsat bob --continue` prints a clear error** if Bob Shell rejects `--resume latest`
  (which may not be a valid session ID in all Bob versions) instead of silently exiting.

## [0.3.6] — 2026-07-26

### Fixed

- **Bob Shell: JSAT MCP tools that need an LLM (`jsat__query`, `prompt_rewrite`, …)
  no longer fail with "No AI provider configured".** The MCP server's provider
  fallback now includes `bob_cli`, and `jsat connect bob` pins
  `JSAT_AI_PROVIDER=bob_cli` in `.bob/settings.json` — so under `jsat bob` the
  tools use Bob itself (no API key needed) instead of the no-op provider.
- F541 in `jsat/mcp/server.py` (extraneous f-string prefix) and 4 findings in
  `jsat/_ai/bob_cli.py` (import, line length, exception chaining).

### Changed

- **Ruff-clean the whole codebase**: all 312 findings under the project config
  (E, F, I, UP, B, SIM; line-length 100) resolved — behavior-preserving line
  wraps, import cleanups, `raise ... from e` chaining, `contextlib.suppress`,
  and public re-exports moved into `__all__`. No `ruff format` (column alignment
  preserved).

## [0.3.5] — 2026-07-26

### Added — Bob Shell integration

- **Bob Shell (`@ibm/bob-shell`) as a first-class AI provider** (`bob_cli`), joining
  the auto-detect priority right after Claude Code CLI (no API key needed).
- `jsat bob` launcher — opens a clean **interactive** Bob session with JSAT wired in
  (`--mode`, `--resume`, `--continue`).
- `jsat connect bob` / `jsat disconnect bob` — registers the JSAT MCP server in
  `.bob/settings.json`, writes `BOB.md` guidance, and installs **31 `/jsat-*` slash
  commands** in `.bob/commands/` (`--no-commands` to skip).
- `switch bob` inside the JSAT shell.

### Fixed

- `bob_cli` was missing from the `AIConfig.provider` allowed values, so every attempt
  to select it failed pydantic validation.
- **MCP server logging went to stdout**, corrupting the stdio JSON-RPC stream — strict
  clients (Bob Shell) reported "MCP ERROR". Logs now go to stderr; stdout is JSON-RPC only.
- `auto_configure` treated a `bob_cli` config as unreachable and silently swapped it out
  (`_provider_reachable` / `detect_ai_providers` now know about Bob).
- `jsat bob` ran Bob one-shot (it exited after a single turn) instead of interactively.
- Bob slash-command YAML frontmatter is now quoted, fixing parse failures on
  descriptions containing `:` (e.g. `jsat-crack`).

### Changed

- `/jsat-prompt` now **optimizes the query and then answers it** by default
  (`--optimize-only` to just show the rewrite).
- Every generated `/jsat-*` command carries a directive to deliver a real, synthesized
  answer from the tool result instead of echoing raw output.
- Slash-command count reported dynamically (now 31, was a hardcoded 28).

## [0.2.0] — 2026-07-25

### Added — Indexer overhaul (Tool 1)

**Parallel parsing** (`indexer.py`)
- `ThreadPoolExecutor(max_workers=min(cpu_count,8))` — each file parsed in its own thread
- Each worker creates its own parser instance (tree-sitter is not thread-safe)
- Expected speedup: 4–8× on multi-core machines for large repos
- `IndexResult.parallel_workers` — reports thread count used

**True incremental indexing** (`_parsers/manifest.py` — new)
- `IndexManifest` class: load/save/delta logic using mtime + sha256
- Manifest stored at `.jsat/index-manifest.json`
- Delta algorithm: mtime as fast pre-filter, sha256 only when mtime changed
- Deleted/modified files: stale nodes+edges removed before re-parsing
- On unchanged repo: only changed files re-parsed (e.g. 3s → 100ms for 500-file repo)
- `IndexResult.incremental` — True when delta mode was active
- `IndexResult.files_skipped` — count of unchanged files bypassed

**Rich metadata extraction** — all 6 parsers (Python, JS/TS, Java, Go, Ruby, Rust)

Every **Function** node now includes:
- `parameters` — `[{name, type?, default?}]` for all languages
- `return_type` — explicit return type annotation (where available)
- `decorators` — `["property","staticmethod","login_required"]` etc.
- `docstring` — first line of docstring/JSDoc/`///` comment (max 200 chars)
- `complexity` — cyclomatic complexity (1 + branch count: if/for/while/match/except)
- `loc` — lines of code (`line_end - line_start + 1`)
- `line` — alias for `line_start` (fixes MCP handler compat bug)

Every **Class** node now includes:
- `bases` — `["BaseModel","Serializable"]` parent class names
- `decorators` — class-level decorators/annotations
- `docstring` — first line of class docstring
- `method_count` — number of methods defined in the class body
- `line` — alias for `line_start`

**New edge types:**
- `INHERITS` — class → parent class (Python, JS, Java, Ruby, Rust)
- `IMPLEMENTS` — class → interface/trait (Java, Go, Rust)
- `RAISES` — function → exception type (Python `raise` statements)

**Symbol resolution pass** (`indexer.py._resolve_edges()`)
- After all files are parsed, resolves CALLS/IMPORTS string-name targets to actual node IDs
- Uses name matching: `id LIKE '%::name'` or `properties.name = name`
- Resolves only unambiguous matches (exactly 1 candidate)
- `IndexResult.resolved_edges` — count of edges successfully resolved

**Richer INDEX.md artifact**
- Overview table: files, nodes, edges, resolved edges, git commit
- Language breakdown: Files | Functions | Classes per language
- Complexity hotspots: top-10 functions by cyclomatic complexity
- Largest files: top-10 by LOC
- Inheritance map: Child → Parent chains (max 30)
- Most called functions: top-10 by incoming CALLS count
- Dead code candidates: public functions with 0 incoming CALLS (max 20, informational)
- Services/Endpoints/Tables/Topics: preserved if created by other tools
- Incremental run tag and file count in header

**`IndexResult` model enrichment** (`_models.py`)
- `files_indexed: int` — files actually parsed this run
- `files_skipped: int` — unchanged files skipped in incremental mode
- `incremental: bool` — whether delta mode was used
- `resolved_edges: int` — CALLS/IMPORTS edges resolved to actual node IDs
- `parallel_workers: int` — thread count used
- `complexity_hotspots: list[dict]` — top-5 `{name, file, complexity}`

### Tests
- `tests/test_indexer.py` — 37 new CI-safe tests: end-to-end indexer, incremental mode, manifest helpers, rich metadata on nodes, edge types
- Suite: **280 passing, 9 skipped**

## [0.1.9] — 2026-07-25

### Added

**Token Optimizer** (`jsat/tools/token_optimizer.py` — new Tool 15)
- `estimate_tokens(text)` — character-based token estimator, ±12% vs BPE tokenization, no tiktoken dependency; adapts chars-per-token ratio based on code punctuation density (3.2 for code, 3.8 mixed, 4.2 prose)
- `MODEL_LIMITS` — context window table for 35+ models: Claude (200K), GPT-4o (128K), Gemini 1.5 (1M), Ollama/llama3.2 (131K), and more
- 6 offline compression strategies (all zero LLM, deterministic):
  - `whitespace` — normalize blank lines, strip trailing spaces
  - `stopphrase` — remove AI filler: "Certainly!", "As an AI...", "I hope this helps"
  - `import_collapse` — merge consecutive `from X import A/B` → `from X import A, B`
  - `dedup` — Jaccard-similarity sentence dedup (threshold 0.82) — removes near-duplicate context
  - `comment_strip` — optional; strips Python `#`, JS/Go `//`, and `/* */` blocks
  - `recency_pin` — last-resort: keep first 70% + last 30%, drop middle with marker
- `TokenReport` dataclass: `original_tokens`, `compressed_tokens`, `savings_tokens`, `savings_pct`, `strategies_applied`, `model_limit`, `budget_used_pct`, `section_breakdown`, `elapsed_ms`
- `section_breakdown(text)` — token count per XML tag, Markdown header, or paragraph
- `TokenOptimizer.budget(text, model)` — returns `{tokens, limit, budget_pct, headroom_tokens, status: ok/warn/critical}`

**`jsat tokens` CLI command**
- `jsat tokens "text"` — count tokens in inline text
- `jsat tokens --file PATH` — count tokens in a file
- `jsat tokens --model gpt-4o` — show budget bar and percentage
- `jsat tokens --compress` — apply compression pipeline and print compressed output
- `jsat tokens --strip-comments` — also strip code comments
- `jsat tokens --no-dedup` — skip semantic dedup (faster, less aggressive)
- `jsat tokens --target N` — compress to explicit token ceiling
- `jsat tokens --verbose` — show per-section token breakdown table
- Reads from stdin when piped: `cat context.py | jsat tokens --model claude-cli`

**SDK methods on `JSAT` class**
- `JSAT.token_count(text)` → int
- `JSAT.token_compress(text, target_tokens, model, strip_comments, dedup)` → TokenReport
- `JSAT.token_budget(text, model)` → dict

**MCP tools** (3 new, total now 55)
- `jsat__token_count` — estimate token count with optional model budget context
- `jsat__token_compress` — compress text and return savings stats + compressed result
- `jsat__token_budget` — show budget status (ok/warn/critical) for a given model

### Tests
- 56 new CI-safe tests for `TokenOptimizer` — covers all 6 strategies, model limits, budget, analyze, compress, and section breakdown

## [0.1.8] — 2026-07-25

### Added

**Multi-agent parallel Prompt Optimizer** (complete rewrite, zero LLM calls)
- 6 offline agents run in `ThreadPoolExecutor(max_workers=3)`: `ClassifyAgent`, `ContextAgent`, `ConstraintAgent`, `FewShotAgent`, `FormatAgent`, `CompressAgent`
- `ClassifyAgent`: keyword-matching task classification in <1ms, returns `task_type` + `matched_keyword` + `confidence`
- `ContextAgent`: BFS graph traversal with 30% token budget cap — no LLM, returns `ContextResult`
- `ConstraintAgent`: KB top-3 query, no LLM, returns `ConstraintResult`
- `FewShotAgent`: kNN word-overlap history ranking, filters by `task_type`, returns `FewShotResult`
- `FormatAgent`: provider-aware formatting — XML (Claude), Markdown (GPT), plain (Ollama) — returns `FormatResult`
- `CompressAgent`: regex-based compression at 4000-token threshold, multi-pass, returns `CompressResult`
- `PromptResult.agent_timings` dict: per-agent wall-clock milliseconds for performance profiling
- `self_critique()` is the ONLY LLM call — explicit, optional, separate from the pipeline

**CLI additions**
- `jsat clean [--cache|--graph|--vectors|--history|--all]` — prune `.jsat/` subdirectories
- `jsat update [--pre]` — self-upgrade via `pip install --upgrade jsat`
- `jsat knowledge-ingest <path> [--pattern|--category|--dry-run]` — bulk markdown ingestion
- `jsat index --watch` (`-w`) — re-index on file change via `entr` (install: `brew install entr`)
- `jsat prompt --verbose` — shows per-agent timing breakdown in ms

**JSAT Shell improvements**
- `_jsat_version()` helper: banner reads version from installed package instead of `"v0.1.0"` hardcode
- Piped stdin support: `echo "explain this" | jsat shell` dispatches without TTY prompts
- `noopt` alias for `opt off`

### Fixed
- Token default mismatch: CLI and optimizer both now default to `max_context_tokens=4096` (was 8192 in CLI)
- Shell crash on piped input: `input()` hangs when stdin is not TTY — fixed with `sys.stdin.isatty()` check

### Tests
- 43 new CI-safe tests for `PromptOptimizer` — covers all 6 agents individually plus integration scenarios

## [0.1.3] — 2026-07-26

### Added

**Multi-model code review** (`jsat/tools/review.py` — complete rewrite)
- True parallel dispatch via `ThreadPoolExecutor` — all configured models run simultaneously
- Provider factory resolves `claude_cli`, `anthropic`, `openai`, `openai_compat`, `ollama` from config
- Per-model 90-second timeout (configurable via `review.parallel_timeout_seconds`) — individual failures skip, review continues
- Deduplication by title similarity: findings from multiple models merged and ranked HIGH/MEDIUM/LOW by agreement count
- Falls back to single configured provider when `review.models` is empty (backward compatible)

**Section K — Agent Prompt Library** (full specification from plan.md)
- All 7 orchestrator agents upgraded from 1-line stubs to complete system prompts (29× more detailed)
- Conflict Resolver agent (K7) added — was missing entirely; includes 7-step resolution with confidence scoring
- Agents: Understanding, Generation, Review, Test, Security, Documentation, Conflict Resolver

**IThinking Phase 5 gate** — hard-stop for destructive operations
- Blocks: `drop table`, `drop database`, `delete from`, `truncate`, `rm -rf`, `wipe`, `destroy`, `purge`
- Returns clear escalation message instead of executing

**MCP server — 17 tools** (was 8)
- New: `get_test_gaps`, `list_secrets`, `validate_migration`, `knowledge_query`, `knowledge_add`
- New: `ithinking_plan`, `ithinking_reflect`, `ithinking_audit_assumptions`, `health`

**`jsat ci-setup` command**
- `jsat ci-setup --provider github` → writes `.github/workflows/jsat.yml`
- `jsat ci-setup --provider gitlab` → appends to `.gitlab-ci.yml`
- CI runs: blast-radius, contract-check, security-review on every PR

**Claude Code — 2 new skills**
- `/jsat-ithinking <task>` — plan before acting (phases 0-4), then execute
- `/jsat-think <task>` — shortcut for think-carefully-first workflow

**Privacy and security config** (`PrivacyConfig`, `SecurityConfig`, `ReviewConfig` in `_models.py`)
- `privacy.hash_pii`, `privacy.audit_log`, `privacy.audit_log_path`
- `security.cvss_threshold`, `security.secret_entropy_threshold`, `security.block_on_critical`
- `review.models`, `review.parallel_timeout_seconds`, `review.min_confidence`

**MCP auth enforcement** (Section L)
- `JSAT_MCP_TOKEN` env var now enforced when set
- Unauthorized requests return `{"code": -32600, "message": "Unauthorized"}`

### Fixed

- `jsat mcp-server` starts in <1s (was 30+ seconds due to auto-indexing + service pings before serving)
- `jsat__query` returning "Invalid session ID" — claude CLI no longer uses `--session-id`/`--resume`
- `jsat__query` returning "claude exited 1" — `--model llama3.2` no longer passed to claude CLI
- `ALTER TABLE orders ALTER COLUMN` correctly classified as `dangerous` (table name in SQL broke pattern matching)
- `is_async` detection works across all tree-sitter-python versions
- Migration lock type detection handles table names between keywords

## [0.1.2] — 2026-07-26

### Added
- Updated PyPI metadata: description, author, classifiers, URLs, keywords
- GitHub Pages documentation site (`mkdocs-material`, 9 pages)
- `local_test.sh` — local test runner with lint, watch, and auto-fix modes
- `jsat disconnect claude` accepts tool name as argument

### Fixed
- GitHub Actions CI: removed `uv`/`semgrep` from test install (exit 127); ruff lint errors fixed

## [0.1.1] — 2026-07-25

### Fixed
- PyPI `400 File already exists` — version was already uploaded; bumped to 0.1.1
- Added `skip-existing: true` to publish workflow

## [0.1.0] — 2026-07-25

### Added

**Core infrastructure**
- 27-class exception hierarchy (`JSATError` → `ConfigError`, `IndexError`, `AIError`, `GraphError`, `ProfileError`, `ExportError`, `SkillError`) — all with structured context kwargs
- All Pydantic v2 models: `JSATConfig`, `SystemProfile`, `IndexResult`, `BlastRadiusReport`, `SecurityReport`, `IncidentReport`, `QueryResult`, `ExportManifest`, and supporting sub-models
- Config loader with 5-path search order + `CI=true` auto-overrides
- System auto-detection: RAM, CPU arch (arm64/x86_64), GPU (CUDA/Metal/none), service reachability (Ollama, Neo4j, Qdrant, Redis)
- Profile presets: `solo`, `team`, `ci`, `raspberry-pi`

**JSAT class and CLI**
- `JSAT` class with fully lazy backend wiring — heavy imports only on first call
- Typer CLI: `jsat index`, `jsat shell`, `jsat doctor`, `jsat init`, `jsat export`, `jsat import`, `jsat skills list/run`, `jsat version`

**Tools (0–14)**
- Tool 0 — JSAT Shell: interactive REPL with 14 commands, tab completion, session history, Rich output
- Tool 1 — Directory Indexer: tree-sitter AST parsing (Python, JS/TS, Go), BFS graph population, `INDEX.md` output
- Tool 2 — Test Intelligence Helper: source-to-test file matching, over-mock detection, behavioral coverage estimate
- Tool 3 — Feature Helper: graph-context-aware implementation plan generation
- Tool 4 — Blast Radius Analyzer: BFS traversal with severity classification (breaking/degraded/warning/safe) and Mermaid diagram output
- Tool 5 — API Contract Validator: OpenAPI/AsyncAPI diff between git branches with compatibility score
- Tool 6 — Security Review Agent: Semgrep integration (graceful fallback), Shannon entropy secret detection, OWASP severity filtering
- Tool 7 — Incident Investigation Helper: git history scoring with recency × blast-radius × pattern-match formula
- Tool 8 — Migration Safety Validator: SQL parsing, lock-type classification, zero-downtime guide generation
- Tool 9 — Multi-Model Code Review: parallel dispatch, embedding-based deduplication, confidence ranking
- Tool 10 — Knowledge Base Builder: graph-stored knowledge entries, AI synthesis, stale-flag decay
- Tool 11 — Multi-Agent Orchestrator: heuristic task decomposition, sequential agent execution, conflict detection
- Tool 12 — Export / Import System: atomic ZIP export with manifest, graph + artifact restore
- Tool 13 — Python SDK: `JSAT` class; full sync + async API for all tools
- Tool 14 — IThinking: 7-phase meta-cognitive wrapper (intent → plan → verify → execute → reflect)

**Backends**
- Graph: SQLite (core, always available), LightGraph (stdlib-only fallback), Neo4j (team extra)
- Embeddings: NoOp/zero-vector (CI), local Ollama nomic-embed-code, OpenAI text-embedding-3-*
- Cache: memory LRU, atomic disk JSON, Redis (team extra)
- AI: NoOp (CI), Ollama (local), Anthropic/Claude, OpenAI, any OpenAI-compatible endpoint

**MCP server**
- JSON-RPC 2.0 stdin/stdout server with 47-tool catalog (JSON Schema per tool)
- 12 tool categories: Index, Blast Radius, Tests, Security, API Contract, Knowledge, Incident, Migration, Review, Export, Meta, IThinking

**Skills system**
- `SkillsRegistry`: YAML manifest auto-discovery and dispatch
- `SkillManifest` Pydantic model with `from_yaml()` and `to_mcp_tool()` converters
- 7 built-in skill clusters: `start-session`, `new-feature`, `pre-merge`, `incident`, `security-release`, `db-schema-change`, `knowledge-maintenance`

**Tests**
- 43+ CI-safe tests (`@pytest.mark.ci`) covering: exceptions, models, caches, SQLite graph, parsers (Python/JS/Go), blast radius, incident scoring, migration analysis, security detection, skills registry

**Packaging**
- `pyproject.toml` with 6 pip extras: `core` (~80MB), `local`, `standard`, `team`, `ci`, `all`
- GitHub Actions CI: matrix (Python 3.10/3.11/3.12), ruff lint, coverage gate at 55%

## [0.1.4] — 2026-07-26

### Added

**Language parsers — Java, Ruby, Rust** (`jsat[standard]`)
- `jsat/_parsers/java.py`: method_declaration, class_declaration, import_declaration → IMPORTS, method_invocation → CALLS
- `jsat/_parsers/ruby.py`: method/singleton_method, class/module, require/require_relative → IMPORTS
- `jsat/_parsers/rust.py`: function_item, struct_item, enum_item, use_declaration → IMPORTS, call_expression → CALLS
- `get_parser()` and `detect_language()` updated for `.java`, `.rb`, `.rs`
- 15 new CI-safe parser tests (skip when grammar not installed)

**MCP server — 38 tools wired** (was 17)
- Graph exploration: `list_services`, `list_endpoints`, `get_function`, `get_class`, `list_tables`, `trace_call_chain`, `get_data_flow`
- Blast radius: `blast_radius_diff`, `blast_radius_symbol`, `get_consumers`
- Tests: `get_behavioral_coverage`, `list_untested_paths`
- API contract: `get_api_diff`, `check_breaking_changes`, `get_compat_score`
- Migration: `suggest_zero_downtime`
- Review: `submit_for_review`, `get_review_findings`, `get_high_confidence_bugs`
- Import: `import_index`
- Observability: `get_metrics` (in-memory call counts + durations per tool)

**RBAC — role-based access control** (Section L)
- `JSAT_MCP_TOKEN_ROLES` env var: JSON mapping `{"token": "role"}`
- Three roles: `viewer` (read-only), `developer` (+blast_radius/security/review), `admin` (all)
- Fully backward-compatible — skipped when env var not set

**Prometheus metrics** (Section M, optional)
- `jsat/mcp/prometheus.py`: activates when `prometheus_client` installed + `JSAT_METRICS_PORT` set
- Metrics: `jsat_tool_calls_total`, `jsat_tool_duration_seconds`, `jsat_graph_nodes_total`, `jsat_cache_hits_total`
- Serves `/metrics` on a daemon thread
- Zero-dep fallback: in-memory metrics always available via `jsat__get_metrics` MCP tool

**Knowledge Base — improved** (Tool 10)
- `knowledge.py`: two-tier entity extraction: regex (zero-cost) + AI (structured JSON)
- Knowledge graph construction: entity nodes + relationship edges stored in graph
- Decay detection: auto-flags stale entries when referenced code nodes disappear
- AI re-ranking of search results when >3 candidates
- `ingest_file(path)` + `ingest_directory(path, pattern)` ingestion API
- Graphiti integration: activates when `graphiti-core` installed + Neo4j URI set
- `knowledge_ingest.py`: standalone CLAUDE.md, ADR, runbook scanner for bulk ingestion

## [0.1.5] — 2026-07-26

### Added

**INDEX.md artifact** — indexer now writes `.jsat/INDEX.md` after every run
- Human + AI readable codebase map: services, endpoints, tables, Kafka topics
- Auto-updated on `jsat index .`

**MCP server — 52 tools fully wired** (was 38, target was 42+)
- All 52 catalog tools have handlers in `_build_registry()`
- New handlers: `blast_radius_file/topic`, `security_scan_file`, `get_auth_coverage`,
  `get_dependency_cves`, `trace_data_flow`, `knowledge_search/list/flag_stale`,
  `get_hypotheses`, `get_recent_changes`, `generate_runbook`, `estimate_lock_duration`,
  `generate_unit/integration/contract_test`, `get_consumers_of_endpoint`,
  `ithinking_execute`, `ithinking_token_estimate`

**Orchestrator — full 7-agent dispatch** (plan.md Section K)
- `_decompose()` now routes tasks to all 7 agents: understanding, generation, test,
  documentation, review, security, conflict_resolver
- All agents callable via `_run_agent()` using full K1-K7 system prompts

## [0.1.7] — 2026-07-26

### Added

**Prompt diff — see exactly what you sent vs what AI received**
- `opt show` in shell now displays both panels side by side:
  `YOU SENT (raw)` vs `AI RECEIVED (optimized with context + constraints + formatting)`
- Token breakdown: raw → optimized, context added, compression savings
- One-liner after every optimized message: `✦ Optimized refactor | 6→847 tokens (35% saved) | 3 ctx nodes | opt show to see diff`
- `jsat__prompt_diff` MCP tool — callable by Claude Code
- `/jsat-prompt-diff <query>` Claude skill installed by `jsat connect claude`

**Prompt Optimizer completions** (all feature.md items now implemented: 45/45)
- `--self-critique` flag: runs a validation AI pass after response; shows violations or "✓ clean"
- `JSAT.prompt_stream()`: generator that yields response chunks + auto-saves history
- `noopt` shell command: alias for `opt off` (disable optimizer in one word)
- `self_critique()` method on `PromptOptimizer`: validates AI response against task constraints

### Documentation
- README: Prompt Optimizer section, `/jsat-prompt-diff` slash command, updated MCP tool list
- docs/cli-reference.md: full `jsat prompt` section with all flags
- docs/claude-integration.md: `/jsat-prompt-diff` skill, Prompt Optimizer subsection
- docs/tools.md: Prompt Optimizer tool entry (pipeline, CLI, SDK, MCP, config)
- docs/configuration.md: `prompt:` config block with all 9 keys
