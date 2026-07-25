# Configuration

JSAT configuration lives in `.jsat/config.yaml` inside your project root (the canonical location). All JSAT state is co-located under `.jsat/` to keep your repo root clean.

## Config File Locations

JSAT searches for a config file in this order (first found wins):

1. Explicit `--config` CLI flag or `config=` SDK argument
2. `$JSAT_CONFIG` environment variable
3. `{repo}/.jsat/config.yaml` — **canonical (recommended)**
4. `{repo}/.jsat.yaml` — legacy fallback
5. `./.jsat/config.yaml` — CWD canonical
6. `./.jsat.yaml` — CWD legacy
7. `~/.config/jsat/config.yaml` — user global
8. `/etc/jsat/config.yaml` — system global

If no config file is found, JSAT uses built-in defaults and auto-detects everything.

## Generate a Starter Config

```bash
jsat init --profile solo           # recommended for individual devs
jsat init --profile team           # for teams with Neo4j + Redis
jsat init --profile ci             # for CI pipelines
jsat init --profile raspberry-pi   # for low-RAM ARM devices
```

---

## Full Config Reference

```yaml
version: "1"
project_name: my-project
project_root: "."

# ── Graph backend ──────────────────────────────────────────────────────────────
graph:
  backend: sqlite               # "sqlite" | "neo4j" | "lightgraph"
  path: .jsat/graph/graph.db    # SQLite database path (relative to repo root)
  remote_uri: null              # Neo4j: "bolt://localhost:7687"
  username: neo4j               # Neo4j username
  password_env: NEO4J_PASSWORD  # env var holding the Neo4j password
  max_nodes: 5000000
  max_edges: 20000000

# ── Embeddings ─────────────────────────────────────────────────────────────────
embeddings:
  provider: local               # "local" | "openai" | "huggingface" | "none"
  model: nomic-embed-code       # local model name or OpenAI model
  api_key_env: OPENAI_API_KEY   # env var for embedding API key
  dimensions: 768
  batch_size: 64

  vector_store:
    backend: sqlite-vss         # "sqlite-vss" | "qdrant" | "pgvector"
    path: .jsat/vectors/        # local vector store directory
    remote_uri: null            # Qdrant: "http://localhost:6333"
    collection: jsat_code
    api_key_env: QDRANT_API_KEY

# ── AI provider ────────────────────────────────────────────────────────────────
ai:
  provider: ollama              # "ollama" | "anthropic" | "openai" | "openai_compat" | "none"
  model: llama3.2
  api_key_env: null             # env var name, e.g. ANTHROPIC_API_KEY (read automatically)
  base_url: null                # for openai_compat (LM Studio, Gemini, custom)
  max_tokens: 8192
  temperature: 0.1
  timeout_seconds: 120
  retry_attempts: 3

# ── Cache ──────────────────────────────────────────────────────────────────────
cache:
  enabled: true
  backend: memory               # "memory" | "disk" | "redis"
  redis_uri: null               # "redis://localhost:6379"
  similarity_threshold: 0.95   # semantic dedup threshold
  ttl_seconds: 3600
  max_memory_mb: 512
  disk_path: .jsat/cache/

# ── Indexer ────────────────────────────────────────────────────────────────────
indexer:
  languages:
    - python
    - javascript
    - go
  exclude_patterns:
    - .git
    - node_modules
    - __pycache__
    - .venv
    - vendor
    - dist
    - build
  incremental: true             # only re-index changed files
  git_hooks: true               # auto-index on git commit
  max_file_size_kb: 500
  follow_symlinks: false
  embedding_batch_size: 64

# ── MCP server ─────────────────────────────────────────────────────────────────
mcp:
  mode: embedded                # "embedded" | "server"
  port: 8765
  auth: false                   # require JSAT_MCP_TOKEN header
  auth_token_env: JSAT_MCP_TOKEN

# ── IThinking ─────────────────────────────────────────────────────────────────
ithinking:
  enabled: true
  mode: interactive             # "interactive" | "silent" | "report-only"
  prompt_review: true           # pause for human review of the plan
  decomposition_review: true    # pause at decomposition step
  assumption_audit: true        # run assumption audit before execution
  local_first: true             # prefer local computation over LLM when possible
  gate_level: medium            # "low" | "medium" | "high"
  reflection: true              # generate phase 6 reflection
  knowledge_update: true        # update knowledge base after tasks

# ── Logging ────────────────────────────────────────────────────────────────────
log:
  level: INFO                   # "DEBUG" | "INFO" | "WARNING" | "ERROR"
  format: text                  # "text" | "json"
  file: null                    # optional log file path

# ── Skills ─────────────────────────────────────────────────────────────────────
skills:
  dir: skills/
  auto_discover: true
  override_builtins: true
  clusters: {}

# ── Review ─────────────────────────────────────────────────────────────────────
review:
  models:
    - {provider: claude_cli, model: claude-sonnet-4-6}
    - {provider: ollama, model: qwen2.5-coder:7b}
  parallel_timeout_seconds: 90   # wall-clock deadline per model; exceeded models are skipped
  min_confidence: medium          # "low" | "medium" | "high"

# ── Prompt Optimizer ───────────────────────────────────────────────────────────
prompt:
  enabled: true                    # auto-optimize all shell messages
  mode: auto                       # "auto" | "always" | "never"
  max_context_tokens: 8192         # max tokens allocated to injected graph context
  few_shot_k: 3                    # number of few-shot examples to inject
  compress_threshold: 6000         # enable token compression above this count
  context_depth: 2                 # BFS depth for graph context injection
  cot_tasks: [debug, plan, security]  # task types that get chain-of-thought appended
  history_path: .jsat/prompt-history.jsonl
  history_max_entries: 10000

# ── Security ───────────────────────────────────────────────────────────────────
security:
  cvss_threshold: medium          # "low" | "medium" | "high" | "critical"
  secret_entropy_threshold: 3.5   # Shannon entropy threshold for secret detection

# ── Privacy ────────────────────────────────────────────────────────────────────
privacy:
  hash_pii: false                 # hash PII values before storing in the graph
  audit_log: false                # write an audit log of all JSAT operations
  audit_log_path: .jsat/audit.log
```

---

## Profiles

### `solo` — Individual Developer

Good default for a single developer on a laptop. Uses SQLite (no services required) and Ollama for local AI. Embeddings with `nomic-embed-code`.

```yaml
version: "1"
project_name: my-project

graph:
  backend: sqlite

embeddings:
  provider: local
  model: nomic-embed-code
  vector_store:
    backend: sqlite-vss

ai:
  provider: ollama
  model: llama3.2

cache:
  backend: memory

ithinking:
  mode: interactive
  gate_level: medium
```

Run:

```bash
jsat init --profile solo
```

---

### `team` — Engineering Team

For teams with shared infrastructure. Uses Neo4j for the graph, Qdrant for vector search, Redis for caching, and the Anthropic API for AI.

```yaml
version: "1"
project_name: my-project

graph:
  backend: neo4j
  remote_uri: bolt://localhost:7687
  password_env: NEO4J_PASSWORD

embeddings:
  provider: openai
  model: text-embedding-3-small
  vector_store:
    backend: qdrant
    remote_uri: http://localhost:6333

ai:
  provider: anthropic
  model: claude-sonnet-4-6

cache:
  backend: redis
  redis_uri: redis://localhost:6379

ithinking:
  mode: interactive
  gate_level: high
```

Run:

```bash
jsat init --profile team
```

Requires `pip install jsat[team]` and Neo4j, Qdrant, and Redis running locally or in your infrastructure.

---

### `ci` — Continuous Integration

For CI pipelines. No AI calls, memory-only cache, JSON log format for structured log ingestion, IThinking disabled.

```yaml
version: "1"
project_name: my-project

graph:
  backend: sqlite

embeddings:
  provider: none

ai:
  provider: none

cache:
  backend: memory

ithinking:
  enabled: false
  mode: silent

log:
  level: WARNING
  format: json
```

Run:

```bash
jsat init --profile ci
```

When `CI=true` is set in the environment, JSAT automatically applies these overrides even without a config file.

---

### `raspberry-pi` — Low-RAM ARM

For ARM devices with limited RAM (Raspberry Pi, older Apple M-series, similar). Uses phi3:mini (2 GB), smaller batch sizes, and disk cache.

```yaml
version: "1"
project_name: my-project

graph:
  backend: sqlite

embeddings:
  provider: local
  model: nomic-embed-code
  dimensions: 384
  batch_size: 8
  vector_store:
    backend: sqlite-vss

ai:
  provider: ollama
  model: phi3:mini

cache:
  backend: disk

indexer:
  embedding_batch_size: 8
  max_file_size_kb: 100

ithinking:
  mode: silent
  gate_level: low
```

Run:

```bash
jsat init --profile raspberry-pi
```

---

## Key Sections Explained

### `graph`

Controls where the codebase graph is stored.

- `sqlite` — default, zero setup, all data in `.jsat/graph/graph.db`
- `neo4j` — for teams; supports shared access, complex graph queries
- `lightgraph` — in-memory, for testing only

For Neo4j:

```yaml
graph:
  backend: neo4j
  remote_uri: bolt://localhost:7687
  username: neo4j
  password_env: NEO4J_PASSWORD   # read from env at runtime
```

Never put the Neo4j password directly in the config file.

---

### `embeddings`

Controls how code is embedded for semantic search.

- `local` — uses Ollama to embed locally with `nomic-embed-code`
- `openai` — uses `text-embedding-3-small` via the OpenAI API
- `none` — skips embedding (no semantic search, graph queries only)

For CI or low-resource environments, set `provider: none` to skip embedding entirely.

---

### `ai`

Controls which AI model answers natural language queries.

Do not put API keys here. Use environment variables:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GEMINI_API_KEY=...
```

For LM Studio or a custom OpenAI-compatible server:

```yaml
ai:
  provider: openai_compat
  model: local-model
  base_url: http://localhost:1234/v1
```

---

### `cache`

Semantic caching: identical or near-identical queries are served from cache without an LLM call.

- `memory` — fast, lost on restart
- `disk` — persists across restarts, stored in `.jsat/cache/`
- `redis` — shared cache for teams

`similarity_threshold: 0.95` means queries with cosine similarity >= 0.95 are considered equivalent and served from cache.

---

### `mcp`

Controls the MCP server used by Claude Code and Cursor.

- `mode: embedded` — default; the MCP server runs as a subprocess started by the IDE
- `mode: server` — run JSAT as a long-running HTTP MCP server (not yet fully implemented)
- `auth: true` — require `JSAT_MCP_TOKEN` in the request header

---

### `ithinking`

Controls structured planning behavior.

- `mode: interactive` — pauses for human review before executing complex tasks
- `mode: silent` — never pauses; plans are generated internally but not shown
- `mode: report-only` — always shows the plan but never pauses

`gate_level` controls how aggressively the framework triggers:

- `low` — triggers on all tasks
- `medium` — triggers on medium+ complexity tasks
- `high` — triggers only on high-complexity tasks

---

### `log`

Controls structlog output.

- `level: DEBUG` — verbose, useful for development
- `format: json` — structured JSON logs, useful in CI and for log aggregation tools
- `file: /var/log/jsat.log` — additionally write logs to a file

---

### `review`

Controls multi-model parallel code review (Tool 9 — MultiModelReview).

- `models` — list of provider/model pairs to dispatch the diff to simultaneously. Each entry must specify a `provider` (`claude_cli`, `ollama`, `anthropic`, `openai`, `openai_compat`) and a `model` name.
- `parallel_timeout_seconds` — wall-clock deadline applied to every model dispatch. Models that exceed this are skipped; their timeout is recorded as a warning in the review output.
- `min_confidence` — controls which findings are surfaced:
  - `low` — any single model's finding
  - `medium` — confirmed by 2 or more models (default)
  - `high` — confirmed by all configured models

Do not put API keys in the `models` list. Keys are read from environment variables as usual (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.).

---

### `prompt`

Controls the 7-stage prompt optimization pipeline. Auto-optimization rewrites every shell message before sending it to the AI — injecting codebase context, constraints, few-shot examples, and model-specific formatting.

- `enabled: true` — turn auto-optimization on or off globally. When `false`, messages are sent as typed.
- `mode` — when optimization runs:
  - `auto` — optimize only when the raw prompt is below `max_context_tokens` and the task classifier assigns a non-trivial label
  - `always` — optimize every message unconditionally
  - `never` — disable the pipeline (equivalent to `enabled: false`)
- `max_context_tokens` — maximum tokens that can be consumed by injected graph context (stage 2). Larger values inject more codebase context but increase LLM cost.
- `few_shot_k` — number of past prompt/response pairs to inject as few-shot examples (stage 4). Set to `0` to disable few-shot injection.
- `compress_threshold` — if the assembled prompt exceeds this token count, stage 7 (token compression) activates. Lower values compress more aggressively; higher values leave prompts unchanged unless they are very large.
- `context_depth` — BFS depth used when traversing the codebase graph for context injection. Depth 1 includes only direct neighbors; depth 2 includes neighbors-of-neighbors. Higher values surface more context but increase token usage.
- `cot_tasks` — list of task types that automatically get chain-of-thought appended. Recognized values: `debug`, `plan`, `security`, `review`, `refactor`, `code_gen`, `test`, `question`.
- `history_path` — JSONL file where every prompt/response pair is appended for future few-shot retrieval.
- `history_max_entries` — maximum entries kept in the history file. Older entries are evicted when this limit is reached.

Set `enabled: false` or `mode: never` in the `ci` profile to skip optimization in pipelines where deterministic, unmodified prompts are required.

---

### `security`

Controls thresholds for the SecurityReview tool.

- `cvss_threshold` — minimum CVSS severity level to report in dependency CVE scans: `low`, `medium`, `high`, or `critical`. Findings below this threshold are suppressed.
- `secret_entropy_threshold` — Shannon entropy value above which a string literal is flagged as a potential hardcoded secret. The default of `3.5` catches most API keys, tokens, and base64-encoded values while reducing false positives on normal strings. Lower values increase sensitivity; higher values reduce noise.

---

### `privacy`

Controls how JSAT handles potentially sensitive data in the graph and logs.

- `hash_pii: true` — before storing any value extracted from source code that matches a PII pattern (email addresses, phone numbers, national IDs), JSAT replaces the raw value with a SHA-256 hash. This prevents PII from being stored in the graph or sent to an LLM.
- `audit_log: true` — write a structured audit log of every JSAT operation (index, query, review, knowledge write, MCP tool call) to `audit_log_path`. Each entry includes a timestamp, operation type, user identity (if available), and a summary of inputs/outputs with sensitive values redacted.
- `audit_log_path` — path to the audit log file (relative to repo root). Default: `.jsat/audit.log`.

Neither setting is enabled by default. Enable both in regulated environments or wherever a record of AI-assisted operations is required for compliance.

---

## Environment Variables

All secrets should be passed via environment variables, never stored in config:

| Variable | Purpose |
|---------|---------|
| `JSAT_CONFIG` | Override config file path |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GEMINI_API_KEY` | Gemini API key (`GOOGLE_API_KEY` also accepted) |
| `NEO4J_PASSWORD` | Neo4j password (key name configurable via `password_env`) |
| `QDRANT_API_KEY` | Qdrant API key (key name configurable via `api_key_env`) |
| `JSAT_MCP_TOKEN` | MCP server auth token |
| `CI` | If `true`/`1`/`yes`, forces CI profile overrides |
