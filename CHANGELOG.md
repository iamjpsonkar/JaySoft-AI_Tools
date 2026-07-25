# Changelog

All notable changes to JSAT.

## [Unreleased]

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
