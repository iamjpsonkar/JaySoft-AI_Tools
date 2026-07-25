# Changelog

All notable changes to JSAT.

## [Unreleased]

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
