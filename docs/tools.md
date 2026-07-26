# Tools

JSAT provides 15 tools. Each tool is a focused capability that can be called from the CLI, the Python SDK, or automatically by Claude Code via MCP.

The 15 tools correspond to the Python modules in `jsat/tools/`:

| # | Name | Module |
|---|------|--------|
| 0 | Shell | `tools/shell.py` |
| 1 | Indexer | `tools/indexer.py` |
| 2 | TestHelper | `tools/test_helper.py` |
| 3 | FeatureHelper | `tools/feature.py` |
| 4 | BlastRadius | `tools/blast_radius.py` |
| 5 | ContractValidator | `tools/contract.py` |
| 6 | SecurityReview | `tools/security.py` |
| 7 | IncidentHelper | `tools/incident.py` |
| 8 | MigrationValidator | `tools/migration.py` |
| 9 | MultiModelReview | `tools/review.py` |
| 10 | KnowledgeBase | `tools/knowledge.py` |
| 11 | Orchestrator | `tools/orchestrator.py` |
| 12 | Export | `tools/export.py` |
| 13 | SDK | (the `JSAT` class itself — `_core.py`) |
| 14 | IThinking | `tools/ithinking.py` |

---

## Tool 0 — Shell

The JSAT interactive shell. Provides a REPL with access to all JSAT tools, AI switching, and natural language queries over the indexed codebase.

**CLI usage:**

```bash
jsat shell
jsat shell --repo /path/to/project
jsat claude     # shell preconfigured for Claude Code CLI
jsat gpt        # shell preconfigured for OpenAI
jsat ollama     # shell preconfigured for Ollama
```

**Shell commands:**

```
> what does this project do?           # natural language query
> blast-radius src/payment/refund.py   # trace impact
> security-review                      # OWASP scan
> incident "500 errors since 14:00"    # investigate
> status                               # graph stats
> switch ollama                        # change AI provider
> switch claude                        # switch to Claude Code CLI
> switch gpt                           # switch to GPT
> help                                 # show all commands
```

**Python SDK usage:**

The shell is not directly accessible via the Python SDK — use the individual tools instead.

---

## Tool 1 — Indexer

Parses source files using tree-sitter and stores rich metadata in the graph database. As of v0.2.0, the indexer is dramatically more powerful across every dimension.

**Languages:** Python, JavaScript/TypeScript, Go, Java (`jsat[standard]`), Ruby (`jsat[standard]`), Rust (`jsat[standard]`)

### What gets extracted (v0.2.0+)

Every **Function** node:

| Property | Type | Example |
|---|---|---|
| `name` | str | `"PaymentService.process"` |
| `file`, `language` | str | `"src/pay.py"`, `"python"` |
| `line_start`, `line_end`, `line` | int | `42`, `61`, `42` |
| `parameters` | list | `[{"name":"amount","type":"float"}]` |
| `return_type` | str | `"bool"`, `"list[Payment]"` |
| `decorators` | list | `["staticmethod","login_required"]` |
| `docstring` | str | first line, max 200 chars |
| `complexity` | int | cyclomatic (1 + branch count) |
| `loc` | int | `line_end - line_start + 1` |
| `is_async`, `is_public` | bool | `True`, `False` |

Every **Class** node:

| Property | Type | Example |
|---|---|---|
| `bases` | list | `["BaseModel","Serializable"]` |
| `decorators` | list | `["dataclass"]` |
| `docstring` | str | first line |
| `method_count` | int | number of methods |
| `line` | int | alias for `line_start` |

New **edge types:**

| Edge | Meaning | Languages |
|---|---|---|
| `INHERITS` | class → parent class | all |
| `IMPLEMENTS` | class → interface/trait | Java, Go, Rust |
| `RAISES` | function → exception type | Python |

### Architecture

**Parallel parsing** — `ThreadPoolExecutor(max_workers=min(cpu_count, 8))`. Each worker owns its own parser instance (tree-sitter is not thread-safe). Expected speedup: 4–8× on multi-core machines.

**True incremental indexing** — `.jsat/index-manifest.json` tracks `mtime + sha256` per file. On the second run, only changed files are re-parsed; unchanged files are skipped entirely. A 500-file repo with 5 changed files indexes in ~100ms instead of 3s.

**Symbol resolution** — after all files are parsed, a post-processing pass resolves CALLS/IMPORTS string-name targets (e.g. `"refund"`) to actual graph node IDs (e.g. `src/pay.py::PaymentService.refund`), so BFS traversal follows real edges.

### CLI usage

```bash
jsat index .                                 # incremental, parallel
jsat index . --force                         # full re-index
jsat index . --watch                         # re-index on file save (needs: brew install entr)
jsat index src/ --languages python,go        # specific languages
jsat index . --branch feature/api-v2        # specific branch
```

### Python SDK usage

```python
from jsat import JSAT

js = JSAT(repo=".")
result = js.index()

print(f"Nodes: {result.nodes_indexed} | Edges: {result.edges_indexed}")
print(f"Files indexed: {result.files_indexed} | Skipped: {result.files_skipped}")
print(f"Incremental: {result.incremental} | Workers: {result.parallel_workers}")
print(f"Resolved edges: {result.resolved_edges}")
print(f"Hotspots: {result.complexity_hotspots}")
```

### IndexResult fields

```python
class IndexResult:
    nodes_indexed: int
    edges_indexed: int
    files_indexed: int       # files actually parsed this run
    files_skipped: int       # unchanged files skipped (incremental mode)
    duration_ms: int
    languages: list[str]
    commit: str
    repo_path: str
    incremental: bool        # True when delta mode was used
    resolved_edges: int      # CALLS/IMPORTS edges resolved to node IDs
    parallel_workers: int    # thread count used
    complexity_hotspots: list[dict]  # top-5 {name, file, complexity}
```

### INDEX.md artifact

After every index run, `.jsat/INDEX.md` is written with:

- Overview table (files, nodes, edges, commit, duration)
- Language breakdown (Files | Functions | Classes per language)
- Complexity hotspots (top-10 functions by cyclomatic complexity)
- Largest files (top-10 by LOC)
- Inheritance map (Child → Parent chains)
- Most called functions (top-10 by incoming CALLS count)
- Dead code candidates (public functions with 0 incoming CALLS, max 20)

---

## Tool 2 — TestHelper

Identifies test gaps in the codebase, generates unit tests, integration tests, and contract tests, and maps behaviors to coverage.

**CLI usage:**

Via MCP in Claude Code:

```
/jsat-query find untested code paths in src/payment/
```

Or direct MCP tool call (Claude calls this automatically):

```
jsat__get_test_gaps service=payment_service type=unit
jsat__generate_unit_test function=process_refund
jsat__generate_integration_test endpoint=POST /api/v1/orders
jsat__generate_contract_test producer=payment_service consumer=order_service
```

**Python SDK usage:**

```python
# TestHelper is exposed via MCP tools; direct SDK access is via the graph
js = JSAT(repo=".")
result = js.query("what functions in src/payment/ have no tests?")
print(result.answer)
```

---

## Tool 3 — FeatureHelper

Assists with feature development by providing codebase context, tracing where a feature is implemented across services, and suggesting integration points.

**CLI usage:**

Natural language queries in the shell or via `/jsat-query`:

```bash
/jsat-query where is the coupon system implemented?
/jsat-query what services would be affected by adding a new payment method?
```

**Python SDK usage:**

```python
result = js.query("where is the coupon system implemented?", service="promotions")
print(result.answer)
for source in result.sources:
    print(f"  - {source}")
```

---

## Tool 4 — BlastRadius

Traces the downstream impact of a change to a file, symbol, git diff, or Kafka topic. Groups impacted nodes by severity: breaking, degraded, warning, safe.

**CLI usage:**

```bash
# Via /jsat-blast-radius slash command in Claude Code:
/jsat-blast-radius src/payment/refund.py
/jsat-blast-radius PaymentService.process_refund

# Direct MCP tools (Claude calls these automatically):
# jsat__blast_radius_file, jsat__blast_radius_symbol, jsat__blast_radius_diff
```

**Python SDK usage:**

```python
report = js.blast_radius("src/payment/refund.py")

# Or for a symbol:
report = js.blast_radius("PaymentService.process_refund", max_depth=4)

# Filter by severity:
report = js.blast_radius(
    "src/payment/refund.py",
    severity_filter=["breaking", "degraded"]
)

for item in report.impacts:
    print(f"{item.severity:10} {item.node_name} ({item.file}:{item.depth})")
    print(f"           reason: {item.reason}")

print(f"\nSummary: {report.summary}")
# Summary: {'breaking': 2, 'degraded': 5, 'warning': 12, 'safe': 31}
```

**Example output snippet:**

```
breaking   OrderService.cancel_order (src/orders/service.py, depth=1)
           reason: directly calls refund_payment() from process_refund
degraded   RefundNotificationJob (src/jobs/notify.py, depth=2)
           reason: depends on refund result dict shape
warning    AuditLogger (src/audit/logger.py, depth=3)
           reason: subscribes to order.status_change events

Summary: {'breaking': 2, 'degraded': 1, 'warning': 1, 'safe': 8}
```

---

## Tool 5 — ContractValidator

Validates API contracts between services. Diffs OpenAPI or AsyncAPI specs, classifies changes as breaking or non-breaking, scores backward compatibility 0-100, and identifies all consumers of a changed endpoint.

**CLI usage:**

```
# MCP tools in Claude Code (called automatically or via /jsat-query):
jsat__get_api_diff base=main head=feature/new-endpoints
jsat__check_breaking_changes base=main head=feature/new-endpoints
jsat__get_compat_score base=main head=feature/new-endpoints
jsat__get_consumers_of_endpoint endpoint=POST /api/v1/payments
```

**Python SDK usage:**

```python
# Via natural language query (ContractValidator backs the answer):
result = js.query("are there any breaking API changes between main and feature/payments-v2?")
print(result.answer)
```

Requires `pip install jsat[standard]` for OpenAPI/AsyncAPI validation (adds `openapi-spec-validator` and `prance`).

---

## Tool 6 — SecurityReview

Runs an OWASP-style security scan. Uses Semgrep rules (with `jsat[standard]`) plus graph-based checks: endpoints missing auth, hardcoded secrets, data flow from user input to SQL/shell, and CVEs in dependencies.

**CLI usage:**

```bash
# Via /jsat-security in Claude Code:
/jsat-security
/jsat-security src/api/

# Or direct MCP tools:
# jsat__security_scan_file, jsat__get_auth_coverage
# jsat__list_secrets, jsat__get_dependency_cves, jsat__trace_data_flow
```

**Python SDK usage:**

```python
report = js.security_review(".", severity_threshold="medium", include_deps=True)

for finding in sorted(report.findings, key=lambda f: f.severity):
    print(f"[{finding.severity.upper()}] {finding.title}")
    print(f"  {finding.file}:{finding.line}")
    print(f"  {finding.description}")
    print(f"  Fix: {finding.remediation}")
    print()

print(f"Secrets detected: {report.secrets_found}")
print(f"CVEs: {len(report.cves)}")
```

**Example output snippet:**

```
[CRITICAL] SQL Injection in search endpoint
  src/api/search.py:47
  User input flows directly into raw SQL query without parameterization.
  Fix: Use parameterized queries or an ORM.

[HIGH] Hardcoded API key
  src/integrations/stripe.py:12
  API key literal detected. Move to environment variables.

Secrets detected: 1
CVEs: 3 (CVSS >= medium)
```

---

## Tool 7 — IncidentHelper

Investigates production incidents by correlating the incident description with recent git commits, affected services, and code structure. Returns ranked hypotheses with evidence and recommended actions.

**CLI usage:**

```bash
# Via /jsat-incident in Claude Code:
/jsat-incident 500 errors on checkout since 14:00
/jsat-incident payment gateway timeouts after the 3pm deploy
```

**Python SDK usage:**

```python
report = js.investigate_incident(
    "500 errors on checkout endpoint since 14:00",
    since="72h",
    services=["checkout_service", "payment_service"]
)

print(f"Top hypotheses for: {report.description}\n")
for i, h in enumerate(report.hypotheses, 1):
    print(f"#{i} Score={h.score:.2f}  {h.commit_summary}")
    print(f"    Commit: {h.commit_hash}  Author: {h.author}  At: {h.timestamp}")
    for ev in h.evidence:
        print(f"    - {ev}")
    print(f"    Action: {h.recommended_action}\n")

print("Mitigation steps:")
for step in report.mitigation_steps:
    print(f"  - {step}")
```

**Example output snippet:**

```
#1 Score=0.92  Add payment retries with exponential backoff
   Commit: a3f91cc  Author: alice  At: 2026-07-25T13:58:00Z
   - checkout_service/payment.py modified 2 hours before incident
   - retry loop introduced with incorrect exception type
   Action: Revert a3f91cc or hotfix exception handling in payment.py
```

---

## Tool 8 — MigrationValidator

Validates database migration files for safety: table-locking operations, reversibility, estimated lock duration, and zero-downtime alternatives.

**CLI usage:**

```
# MCP tools (called by Claude automatically during code review):
jsat__validate_migration file=migrations/20260725_add_index_orders.sql
jsat__estimate_lock_duration operation=CREATE INDEX table=orders row_count=5000000
jsat__suggest_zero_downtime operation=ADD COLUMN
```

**Python SDK usage:**

```python
result = js.query("is migrations/add_index.sql safe to run on a live database?")
print(result.answer)
```

Requires `pip install jsat[standard]` for full migration analysis.

---

## Tool 9 — MultiModelReview

Dispatches a diff to multiple AI models simultaneously using `ThreadPoolExecutor`, collects findings independently from each model, and merges the results. Bugs confirmed by two or more models are surfaced as high-confidence. Models that exceed `parallel_timeout_seconds` are skipped and their omission is logged as a warning.

**Configuration (`.jsat/config.yaml`):**

```yaml
review:
  models:
    - {provider: claude_cli, model: claude-sonnet-4-6}
    - {provider: ollama, model: qwen2.5-coder:7b}
  parallel_timeout_seconds: 90
  min_confidence: medium
```

- `parallel_timeout_seconds` — per-review wall-clock deadline applied to every model dispatch.
- `min_confidence` — `low` surfaces any finding, `medium` requires 2+ models to agree, `high` requires all models to agree.

**CLI usage:**

```
# MCP tools in Claude Code:
jsat__submit_for_review diff="$(git diff main)" base=main head=HEAD
jsat__get_review_findings min_confidence=high
jsat__get_high_confidence_bugs
```

**Python SDK usage:**

```python
result = js.query("review the changes in the current branch for bugs")
print(result.answer)
```

---

## Tool 10 — KnowledgeBase

A persistent notes store for the project. Add architectural decisions, gotchas, runbooks, and on-call notes. Supports semantic search. Entries can be flagged as stale when code changes.

**CLI usage:**

```
# MCP tools in Claude Code:
jsat__knowledge_add text="The checkout service uses optimistic locking on order rows." category=architecture
jsat__knowledge_query question="how does checkout handle concurrent orders?"
jsat__knowledge_search query="locking strategy" limit=5
jsat__knowledge_list category=architecture
jsat__knowledge_flag_stale entry_id=kb_001
```

**Python SDK usage:**

```python
result = js.query("what do we know about the checkout locking strategy?")
print(result.answer)
```

Requires `pip install jsat[team]` for Qdrant-backed semantic search. SQLite-VSS is used with `jsat[standard]`.

---

## Tool 11 — Orchestrator

Coordinates multi-step JSAT workflows across tools. Routes complex requests to the right combination of tools: for example, "review this PR for security and blast radius" triggers SecurityReview and BlastRadius and merges the results.

**CLI usage:**

Orchestration happens automatically behind the scenes when you use `/jsat-query` with a complex request:

```
/jsat-query review the current branch for security issues and trace the blast radius of any changed files
```

**Python SDK usage:**

```python
# Orchestrator is invoked implicitly when a query spans multiple tools
result = js.query("what is the blast radius and security risk of the changes in src/auth/")
print(result.answer)
```

---

## Tool 12 — Export

Exports the JSAT graph, vectors, and cache to a portable zip archive, or restores from one. Used for sharing the indexed codebase with teammates or CI.

**CLI usage:**

```bash
# Export
jsat export backup.jsat.zip
jsat export backup.jsat.zip --compress 9

# Import
jsat import backup.jsat.zip
```

**Python SDK usage:**

```python
# Export
manifest = js.export("backup.jsat.zip", compress_level=6)
print(f"Exported {manifest.nodes} nodes, {manifest.edges} edges to {manifest.path}")
print(f"Size: {manifest.size_mb:.1f} MB")

# Import / restore
from jsat import JSAT
js = JSAT.from_import("backup.jsat.zip")
print(js.index_status)
```

**Example output:**

```
ExportManifest(
    path='backup.jsat.zip',
    size_mb=4.2,
    nodes=1842,
    edges=4391,
    commit='a3f91cc',
    jsat_version='0.1.0',
    created_at='2026-07-25T12:00:00Z'
)
```

---

## Tool 13 — SDK

The `JSAT` Python class (`jsat._core.JSAT`). This is the main entry point for all programmatic use. All other tools are accessible through it.

See the [Python SDK reference](sdk.md) for the full API.

**Quick example:**

```python
from jsat import JSAT

js = JSAT(repo=".", ai_provider="ollama")
js.index()

result = js.query("what calls the refund endpoint?")
print(result.answer)

report = js.blast_radius("src/payment/refund.py")
print(report.summary)
```

---

## Tool 14 — IThinking

A structured thinking and planning framework. Before executing a complex task, IThinking decomposes it into phases, audits assumptions, estimates token cost (local vs LLM), and optionally pauses for human review before proceeding.

**CLI usage:**

```
# MCP tools in Claude Code (called by Claude on complex requests):
jsat__ithinking_plan task="Refactor the authentication module to support OAuth2"
jsat__ithinking_execute task="Refactor the authentication module to support OAuth2"
jsat__ithinking_reflect task="..." result="..."
jsat__ithinking_token_estimate task="Generate tests for all uncovered paths"
jsat__ithinking_audit_assumptions subtask="Update the user schema to add MFA fields"
```

IThinking is controlled via `.jsat/config.yaml`:

```yaml
ithinking:
  enabled: true
  mode: interactive   # interactive | silent | report-only
  gate_level: medium  # low | medium | high
  prompt_review: true
  decomposition_review: true
  assumption_audit: true
```

Set `mode: silent` in CI to skip interactive prompts. Set `mode: report-only` to always show the plan but never pause.

---

## Prompt Optimizer (`jsat prompt`)

A two-phase pipeline that converts any raw query into the best possible prompt for the configured AI.

### Phase 1 — Offline pipeline (always, zero LLM calls)

| Stage | What it does | Cost |
|---|---|---|
| Classify | Keyword-match task type (8 types) | ~0ms |
| Context | BFS graph traversal, 70/30 recency split | ~2ms |
| Constraints | KB top-3 lookup (ADRs, coding standards) | ~1ms |
| Few-shot | kNN over prompt history | ~3ms |
| Format | XML (Claude) / Markdown (GPT) / plain (Ollama) | ~0ms |
| Compress | Token pruning above 4000-token threshold | ~1ms |

### Phase 2 — LLM rewriting (optional)

After Phase 1 structures the prompt, 1–3 specialist LLM agents rewrite the task description in parallel, then the best result wins.

| Agent | Temperature | Focus |
|---|---|---|
| `rewrite` | 0.2 | Replaces vague words with specific identifiers revealed by context |
| `context_expand` | 0.3 | Fills missing technical detail (function names, error messages, paths) |
| `constraint_harden` | 0.1 | Makes success criteria measurable ("ensure X returns Y when Z") |

Winner is chosen by: **coverage × 0.45 + specificity × 0.40 + efficiency × 0.15**

### CLI usage

```bash
# Phase 1 only (offline)
jsat prompt "improve the retry logic"
jsat prompt --send "improve the retry logic"
jsat prompt --diff "improve the retry logic"
jsat prompt --send --cot --verbose "debug the 500 on checkout"

# Phase 1 + Phase 2: 1 LLM agent (fastest)
jsat prompt --rewrite "fix logger in this branch"

# Phase 1 + Phase 2: 3 parallel LLM agents (best quality)
jsat prompt --agents "fix logger in this branch"

# Rewrite + send in one step
jsat prompt --agents --send "fix logger in ValidateVPAHandler.post"

# All flags
jsat prompt --send --agents --ai claude --format code --cot "write test for refund()"
```

All flags:

| Flag | Default | Description |
|---|---|---|
| `--send` / `-s` | false | Send to AI and stream response |
| `--rewrite` | false | Run 1 LLM rewrite agent after offline pipeline |
| `--agents N` | 0 | Run N parallel LLM rewrite agents (1-3; omit N for 3) |
| `--ai` | config | Override AI provider: claude, openai, ollama, etc. |
| `--format` / `-f` | auto | code, plan, json, prose |
| `--cot` | false | Enable chain-of-thought |
| `--diff` | false | Show raw vs optimized side by side |
| `--verbose` / `-v` | false | Show per-agent timings + rewrite winner |
| `--self-critique` | false | Validate AI response (1 extra LLM call) |
| `--no-context` | false | Skip graph context injection |
| `--no-examples` | false | Skip few-shot examples |
| `--dry-run` | false | Optimize but don't send |
| `--max-tokens` | 4096 | Token budget |

### Shell usage

```
jsat> improve the retry logic
✦ Optimized refactor | 6→847 tokens (35% saved) | 3 ctx nodes | opt show to see diff

opt on        # enable auto-optimization (default)
opt off       # disable for the current session
opt show      # show raw input vs full optimized prompt for the last message
opt history   # browse past optimization diffs
noopt         # alias for opt off
```

### Python SDK usage

```python
from jsat import JSAT

js = JSAT(repo=".")

# Phase 1 only
result = js.prompt("improve the retry logic")

# Phase 1 + 1 LLM agent
result = js.prompt("fix logger in payments", rewrite=True)

# Phase 1 + 3 parallel LLM agents
result = js.prompt("fix logger in ValidateVPAHandler.post", n_agents=3)
print(f"Winner: {result.winning_agent} (score: {result.winning_score:.2f})")

# Optimize + send
r = js.prompt_and_send("write a test for refund()", n_agents=3)
print(r["response"])
```

### MCP tools

| Tool | Description |
|------|-------------|
| `jsat__prompt_optimize` | Offline pipeline only — no LLM |
| `jsat__prompt_diff` | Raw input vs fully optimized prompt as structured diff |
| `jsat__prompt_rewrite` | Offline + 1 LLM rewrite agent |
| `jsat__prompt_multi_agent` | Offline + up to 3 parallel LLM agents; returns winner |

### Configuration (`.jsat/config.yaml`)

```yaml
prompt:
  enabled: true                    # auto-optimize all shell messages
  mode: auto                       # auto | always | never
  max_context_tokens: 4096
  few_shot_k: 2                    # examples to inject per query
  compress_threshold: 4000         # enable compression above this token count
  context_depth: 2                 # BFS depth for graph context injection
  cot_tasks: [debug, plan, security]
  history_path: .jsat/prompt-history.jsonl
  history_max_entries: 10000
```

### Claude Code slash commands

```
/jsat-prompt <query>          — offline pipeline only
/jsat-prompt-diff <query>     — show raw vs optimized
/jsat-prompt-rewrite <query>  — 3 parallel LLM agents, show winner
```

---

## Tool 15 — Token Optimizer

Offline token analysis and multi-strategy compression. Zero LLM calls. All strategies are deterministic.

### Compression strategies

Applied in this order:

| Strategy | What it removes | Lossy? |
|---|---|---|
| `whitespace` | 3+ blank lines, trailing spaces | No |
| `stopphrase` | AI filler: "Certainly!", "As an AI...", "I hope this helps" | No |
| `import_collapse` | `from X import A` + `from X import B` → one line | No |
| `dedup` | Near-duplicate sentences (Jaccard ≥ 0.82) | Slightly |
| `comment_strip` | `# comment`, `// comment`, `/* */` (opt-in) | Yes |
| `recency_pin` | Drops middle content when still over budget; keeps first 70% + last 30% | Yes |

### Model context limits

Built-in table for 35+ models — Claude (200K), GPT-4o (128K), Gemini 1.5 (1M), llama3.2 (131K), etc.

### CLI usage

```bash
# Count tokens
jsat tokens "explain the payment service"
jsat tokens --file README.md

# Check budget vs model limit
jsat tokens --file context.py --model gpt-4o
jsat tokens --file context.py --model claude-cli

# Compress and show savings
jsat tokens --file context.py --compress
jsat tokens --file context.py --compress --model claude-cli --target 4000

# Strip code comments too
jsat tokens --file context.py --compress --strip-comments

# Verbose section breakdown
jsat tokens --file context.py --verbose

# Pipe stdin
cat big_file.py | jsat tokens --model gpt-4o --compress
```

### Python SDK usage

```python
from jsat import JSAT

js = JSAT(repo=".")

# Count tokens
count = js.token_count("explain the payment service")

# Compress a prompt
report = js.token_compress(
    long_context,
    model="gpt-4o",          # sets ceiling to 85% of 128K
    strip_comments=False,
    dedup=True,
)
print(f"Saved {report.savings_pct:.1f}% via: {report.strategies_applied}")
print(report.compressed_text)

# Budget check
budget = js.token_budget(my_context, "claude-cli")
# {"tokens": 1240, "limit": 200000, "budget_pct": 0.62,
#  "headroom_tokens": 198760, "status": "ok"}
```

### TokenReport fields

```python
class TokenReport:
    original_tokens: int
    compressed_tokens: int
    savings_tokens: int
    savings_pct: float             # e.g. 28.4
    strategies_applied: list[str]  # e.g. ["whitespace","stopphrase","dedup"]
    model: str | None
    model_limit: int | None        # context window size
    budget_used_pct: float | None  # compressed / limit × 100
    section_breakdown: dict        # per XML tag or Markdown header
    elapsed_ms: float
```

### MCP tools

| Tool | Description |
|---|---|
| `jsat__token_count` | Estimate token count with optional model budget context |
| `jsat__token_compress` | Compress text and return savings stats + compressed result |
| `jsat__token_budget` | Show budget status (ok/warn/critical) for a given model |

---

## Tool 16 — JSAT Crack

Multi-agent war room for complex engineering decisions. Six specialist agents discuss a task in rounds, responding to each other's arguments — like a real architecture meeting or incident war room.

### Architecture

```
Round 1 — all agents state positions IN PARALLEL:
  🏛 architect   → system design proposal
  🔒 security    → threat model + constraints
  ⚙  implementer → current code analysis
  🧪 tester      → coverage gaps, testability
  😈 skeptic     → challenges every proposal
  ← collected →

Round 2 — agents RESPOND to each other:
  Each agent reads round-1 transcript, addresses others' points directly

Round 3 — Moderator synthesis:
  🎯 moderator reads all rounds and produces:
    ✅ Agreed items
    ⚠️ Disputed items / open questions
    🎯 Recommended action plan
```

**Key difference from `jsat__prompt_multi_agent`:**
- `prompt_multi_agent`: 3 agents run independently in parallel, pick best output
- `crack`: agents *respond to each other's outputs* across rounds (cross-talk)

### CLI usage

```bash
jsat crack "redesign payment retry system"
jsat crack --roles architect,security "migrate users table to UUID"
jsat crack --rounds 2 --file output.md "sync vs async webhooks"
```

| Flag | Default | Description |
|---|---|---|
| `--roles` | all 6 | Comma-separated subset: architect,security,implementer,tester,skeptic |
| `--rounds` / `-n` | 3 | Number of discussion rounds |
| `--file` / `-f` | auto | Write output to specific file (default: `.jsat/crack/<slug>.md`) |

### Shell usage

```
> crack should we use Redis or Postgres for idempotency keys
```

### Python SDK

```python
from jsat.tools.crack import CrackTool
result = CrackTool(graph=g, cfg=cfg, ai=ai).run(
    "redesign payment retry system",
    roles=["architect", "security", "skeptic"],
    rounds=2,
)
print(result.synthesis)       # moderator's final synthesis
print(result.output_path)     # .jsat/crack/redesign-payment-retry-system.md
```

### MCP tool

| Tool | Description |
|---|---|
| `jsat__crack` | Multi-agent war room — architect, security, implementer, tester, skeptic, moderator |

### Graceful degradation

If no AI is configured, each agent returns a structural placeholder based on the task text and graph context (BFS keywords). The discussion still happens — it just uses offline templates instead of LLM completions.

---

## Tool 17 — JSAT Short

Get the briefest possible correct answer to any question. Prepends a brevity constraint to any query.

### CLI usage

```bash
jsat short "what does process_refund do"
jsat short --one-line "is PaymentService.process async"
jsat short --words 20 "explain the retry logic"
```

| Flag | Default | Description |
|---|---|---|
| `--words` / `-w` | 50 | Maximum word count |
| `--one-line` / `-1` | false | Strict one-sentence answer |

### Shell usage

```
> short is the checkout flow async
```

### MCP tool

| Tool | Description |
|---|---|
| `jsat__short` | Ask any question with a brevity constraint (≤50 words default) |

### Claude Code slash command

```
/jsat-short what does process_refund do
```
