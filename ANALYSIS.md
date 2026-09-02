# JSAT — complete analysis

A full audit of JSAT at **v0.4.17**, written 2026-09-02. Every claim here was
verified against the code or by running the real artifact; where a documented
behaviour and the code disagreed, the code won and the disagreement is
recorded in [§18](#18-verified-findings). Counts drift — re-derive with
`jsat index .` and `./scripts/jsat-selftest.sh` rather than quoting this file.

| Measured | Value |
|---|---|
| Python modules in `jsat/` | 90 |
| Package LOC | ~27,300 |
| CLI commands (top level) | 41 |
| MCP tools | 69 |
| Slash commands (`jsat/commands/jsat-*.md`) | 47 (46 + `help`) |
| Tree-sitter parsers | 7 languages |
| AI providers | 9 |
| Graph backends | 3 · cache backends 3 · embedder backends 3 |
| pytest | 46 files, 709 tests — 735 passed / 11 skipped / 34 deselected |
| Self-test | 18 modules, ~5,900 LOC, ~230 checks across 12 suites |

---

## 1. What JSAT is

JSAT parses a codebase with tree-sitter into a persistent graph, then exposes
that graph through three surfaces that share one core: a **CLI** (`jsat …`), a
**Python SDK** (`from jsat import JSAT`), and an **MCP server** any AI tool can
call. Every feature — blast radius, security review, incident investigation,
test gaps — is a query over that graph, plus optionally an LLM.

The strategic bet is worth naming because it shapes everything: JSAT is not an
AI product, it is a *retrieval substrate for* AI products. It ships no model,
and its most-used features (blast radius, token accounting, migration
analysis, incident ranking, contract diffing) need no model at all. The LLM is
an optional consumer of the graph, not the engine. That is why the CLI is fast,
why the package installs in ~80MB, and why the tool is useful with `ai.provider:
none`.

## 2. The three surfaces, and how a call flows

```
jsat <cmd>  ─┐
             ├─►  jsat/_cli_*.py  ──►  JSAT (_core.py)  ──►  tools/<feature>.py
SDK JSAT()  ─┤                              │                      │
             │                              ├──► _graph/ (SQLite)  │
MCP client  ─┘                              └──► _ai/ (provider)   │
   └── mcp/server.py  ──────────────────────────────────────────────┘
```

`JSAT.__init__` (`jsat/_core.py:56`) loads config, detects the system, pins
paths, sets up logging and primes the improve gates. It does **not** open the
graph or the AI — both are lazy (`_get_graph()`, `_get_ai()`), which is why
`jsat --help` is fast and why a stale install breaks only at call time.

Two sharp edges are worth internalising. First, `_get_ai()` never raises for a
missing key — it substitutes `NoOpProvider` — but `NoOpProvider.complete()`
*does* raise `AIError`. Always check `ai.is_available()` first. Second, the MCP
server deliberately does **not** construct a full `JSAT`: `jsat mcp-server`
builds a `_MinimalJSAT` shim (`_cli_setup.py:564`) that skips system detection,
because Claude Code's startup timeout would otherwise mark the server failed.
That shim re-implements a subset of the `JSAT` surface by hand, and is a
standing source of drift — see [§19](#19-remaining-gaps).

## 3. Data model

Everything is Pydantic v2 in `jsat/_models.py`. Three families:

**Config tree** — `JSATConfig` is the root, composed of `GraphConfig`,
`EmbeddingsConfig` + `VectorStoreConfig`, `AIConfig`, `CacheConfig`,
`IndexerConfig`, `MCPConfig`, `IThinkingConfig`, `PrivacyConfig`,
`ImproveConfig`, `SecurityConfig`, `ReviewConfig`, `PromptConfig`. Every field
is defaulted, so an old config file stays valid across upgrades — and unknown
keys are ignored rather than rejected, which is what made removing the dead
`cache.similarity_threshold` safe.

**Graph primitives** (`jsat/_graph/__init__.py`) — deliberately untyped:
`Node(id, label, properties)` and `Edge(source_id, target_id, type,
properties)`, with labels as free-form strings and no schema enforcement
anywhere. Node ids are `<rel_path>` for files and `<rel_path>::<qualified_name>`
for symbols (`jsat/tools/query.py::QueryTool.run`).

**What the parsers actually emit** — three labels (`File`, `Class`, `Function`)
and five edge types (`CALLS`, `IMPORTS`, `INHERITS`, `IMPLEMENTS`,
`RAISES`). `blast_radius.py` additionally classifies `READS_FROM`,
`WRITES_TO`, `CONSUMES`, `PRODUCES`, `DEPENDS_ON`, and `get_data_flow` queries
them — but no parser produces them, so those code paths return empty on any
real repo. Similarly `Service`, `Endpoint`, `Table` and `Topic` are queried by
`query.py`, `feature.py`, `test_helper.py` and `INDEX.md` generation, yet are
never persisted; they exist only as request-time heuristics inside the MCP
server. This is the single largest gap between the documented model and the
stored one.

**Result models** — `IndexResult`, `BlastRadiusReport`/`ImpactItem`,
`SecurityReport`/`SecurityFinding`/`CVEFinding`, `IncidentReport`/`Hypothesis`,
`QueryResult`, `ExportManifest`. Note `ContractReport` is a plain dataclass
whose `changes` are dicts keyed `is_breaking` — an inconsistency that already
caused one bug in this release.

## 4. Indexing pipeline

`IndexerTool.run` (`jsat/tools/indexer.py:45`): collect files (`rglob` +
exclude patterns + a 500KB size cap) → load the prior manifest → compute the
delta → parse in a `ThreadPoolExecutor(min(cpu_count, 8))`, one parser instance
per file so it is thread-safe → batch `bulk_add_nodes`/`bulk_add_edges` every
2,000 rows → **symbol resolution** → complexity hotspots → save manifest →
write `INDEX.md`.

Two parts deserve attention. The **delta** (`_parsers/manifest.py`) tracks
`{mtime, sha256}` per file, using mtime as a cheap pre-filter and hashing only
on mismatch — so `touch` and copy-with-same-content correctly count as
unchanged. Deletes are batched to 900 bound variables to stay under
`SQLITE_MAX_VARIABLE_NUMBER`. The **symbol-resolution pass**
(`_resolve_edges`, line 251) is what turns a textual callee (`self.foo`,
`os.path.join`) into a real node id: it builds one in-memory name→ids map and
rewrites only unambiguous single-candidate names. Overloaded names stay
unresolved, cross-language calls are never linked, and the whole pass is
**skipped for non-SQLite backends**.

On disk (`.jsat/`, or `~/.jsat/<sha1_12(repo)>/` when no legacy local dir
exists): `graph/graph.db`, `index-manifest.json`, `INDEX.md`, `cache/`,
`vectors/`, `prompt-history.jsonl`, `audit.log`. The hashed global fallback
keeps `.jsat/` out of every repo's git tree — clever, but it means **moving or
renaming a checkout silently orphans its index**.

"Incremental" means "re-run and compare against the manifest". There is no
filesystem watcher; `jsat index --watch` shells out to `entr`.

## 5. Parsers

All seven share one architecture: read bytes → tree-sitter parse → emit a
`File` node (path, language, loc) → walk classes → walk functions/methods →
walk imports → walk calls. Every parser wraps failures and degrades to a bare
`File` node, so one unparseable file never fails an index — and a missing
optional grammar degrades the same way, which is why defaulting
`indexer.languages` to all seven is safe.

| Language | Extracted | Edges | Gaps |
|---|---|---|---|
| **Python** | params with type+default, return type, decorators, first docstring line, cyclomatic complexity, async | `INHERITS`, `RAISES`, `IMPORTS`, `CALLS` | callee text resolved only post-hoc |
| **JS/TS** | params incl. TS types/optional/rest/default, TS return type, decorators, JSDoc, complexity | `INHERITS`, `IMPORTS` (ES only), `CALLS` | no `require()`; no JSX-specific extraction |
| **Go** | params, return type, `//` doc, complexity; receivers qualified as `Type.Method` | `IMPORTS`, `CALLS` | docstring claims `IMPLEMENTS`; struct-embedding→interface edges not emitted |
| **Java** | params, return type, annotations, Javadoc, complexity, `is_constructor` | `INHERITS`, `IMPLEMENTS`, `IMPORTS` (incl. wildcard), `CALLS` | solid |
| **Ruby** | params incl. splat/kwargs/block, `#` doc, complexity, singleton methods | `INHERITS`, `IMPORTS` (`require`/`require_relative`), `CALLS` | no return types (none in the language) |
| **Rust** | params (skips `self`), return type, `#[attr]`, `///` doc | `IMPLEMENTS` (`impl Trait for Type`), `IMPORTS` (recursive `use` lists), `CALLS` | trait method_count scans all `impl` blocks by type name |

`_parsers/manifest.py` is not a language parser — it is the delta tracker
described above.

## 6. Graph layer

The `GraphClient` contract: `add_node`, `add_edge`, `get_node`,
`outgoing_edges`, `bfs`, `edges`, `checkpoint`, `query`, `node_count`,
`edge_count`, `close`. (`edges` and `checkpoint` were added in 0.4.17 — the
former because two MCP tools called a method that existed nowhere, the latter
because `export` copied the database file while rows were still in the WAL.)

**SQLiteGraph** is the default and the only fully-supported backend. It uses
`sqlean.py` when present, else stdlib `sqlite3`; two tables indexed on
`source_id`, `target_id`, `type`, `label`; tuned pragmas (WAL,
`synchronous=NORMAL`, 64MB cache, 256MB mmap, `busy_timeout=5000`). Its
`query()` is a **raw SQL pass-through** with two regex-matched Cypher
lookalikes bolted on; anything else logs `sqlite_graph_unsupported_query` and
returns `[]`. That is the honest description: JSAT's "graph queries" are SQL
over two JSON-valued tables.

**LightGraph** is the same thing without the `sqlean` dependency, and is
verified to produce byte-identical node/edge counts on the same tree.

**Neo4jGraph** requires `jsat[team]` and is **partial by design**. Its
`query()` detects and rejects SQL-shaped input, because every tool call site
emits SQLite SQL — a good defensive choice that nonetheless means selecting
this backend breaks `query`, `feature`, `get_test_gaps` and the indexer's
symbol resolution. As of 0.4.17 it warns at construction naming exactly what
degrades, rather than half-working silently.

`GraphConfig.max_nodes`/`max_edges` (5M/20M) are now enforced at the
bulk-insert boundary — the path mass growth takes — where one `COUNT` per
2,000-row batch costs nothing.

## 7. Cache and embeddings

**Cache** — `get_cache(cfg)` picks `redis`/`disk`/`memory` (default memory),
falling back to memory if the redis import fails. All three implement `get`,
`set`, `invalidate_for_files`, `clear`, `stats`. Keying is **exact match** on
`(query, context_hash)`; nothing computes similarity. `DiskCache` writes
atomically (tmp → `os.replace` + `fsync`). File-scoped invalidation works
across all three and is verified: an entry that recorded a source file is
dropped when that file changes.

**Embeddings** — an `Embedder` ABC with `embed`, `embed_batch`, `dimensions`,
`model_name` and a pure-Python `cosine_similarity`, plus three backends
(`LocalEmbedder` via Ollama, `OpenAIEmbedder`, `NoOpEmbedder`). **None of it is
called.** There is no `get_embedder()` factory and no `.embed()` call site
outside `_embed/`. All retrieval in `query.py`, `feature.py`, `knowledge.py`
and the prompt optimizer's context/few-shot agents is
keyword/substring/Jaccard based. As of 0.4.17 the config schema and
`docs/configuration.md` say so explicitly instead of presenting it as live.

## 8. The tools layer

`jsat/tools/` holds the logic; `_cli_*` holds parsing and presentation;
`mcp/server.py` holds the MCP surface. A feature usually needs all three plus
tests.

- **`indexer.py`** — §4. No LLM.
- **`query.py`** — assembles a text context from graph rows filtered by
  keyword overlap (optionally service-scoped), then makes **one** LLM call with
  a grounding prompt. Needs an LLM for the answer; the retrieval is pure SQL.
- **`blast_radius.py`** — resolves a target (node id, file path, or bare name
  via `id LIKE '%::name'`) to start nodes, BFS to `max_depth`, classifies each
  traversed edge type as breaking/degraded/warning/safe from a fixed table,
  optionally seeded from a unified diff's changed files, and renders Mermaid.
  **No LLM.** Verified: 8 impacts and a diagram from a 4-deep fixture chain.
- **`contract.py`** — finds OpenAPI/AsyncAPI specs, diffs them across two git
  refs, classifies line changes (endpoint/path removal, required-field
  additions) with regex heuristics including multi-line YAML `required:` list
  detection, and computes `compat_score = 100·e^(-0.15·breaking)`. **No LLM.**
  Verified: 3 breaking changes and 64% compatibility on the fixture's v1→v2.
- **`export.py`** — zips `graph.db` + `INDEX.md` + config with a JSON manifest;
  `restore()` does version checking and zip-slip-safe extraction (resolve then
  verify containment). Verified both ways, including that a `../` archive member
  is rejected.
- **`feature.py`** — one LLM call asking for a structured JSON implementation
  plan, regex-extracted from the response, degrading to a single free-text step
  on parse failure. Its Service/Endpoint context is empty in practice (§3).
- **`incident.py`** — ranks recent git commits as root-cause hypotheses with a
  weighted score: `0.35·recency(exp decay) + 0.25·blast radius(file count) +
  0.15·author/file frequency + 0.25·keyword overlap`. **No LLM** — git plus
  arithmetic. Verified: 5 ranked hypotheses from real history.
- **`migration.py`** — parses SQL statements, maps each op to a Postgres lock
  type and a throughput-based duration, flags dangerous locks, detects the
  `ADD COLUMN … NOT NULL DEFAULT` full-rewrite trap, `atomic=False`, missing FK
  indexes, and multiple locking ops in one file. **No LLM.**
- **`security.py`** — three independent scans merged under one severity
  threshold: semgrep (`p/owasp-top-ten`, `p/secrets`, a graceful no-op when
  absent); regex + Shannon-entropy secret detection; and a live osv.dev CVE
  lookup for parsed requirements. **No LLM.** Contains a genuinely clever
  false-positive filter, `_is_sequential_charset_literal`, which distinguishes
  a hardcoded alphabet (high entropy, but characters ascend by one code point)
  from a real token — a bug the tool hit on its own source. Verified: all three
  sources fire on the fixture (1 semgrep finding, 1 secret, 42 real CVEs).
- **`crack.py`** — a "war room": five specialist roles (architect, security,
  implementer, tester, skeptic) run **in parallel** per round via a thread
  pool, each seeing all prior statements, with a moderator synthesising after
  each round. Needs an LLM, with an offline template fallback per role.
- **`review.py`** — sends the identical diff to N configured models in
  parallel, requires a JSON findings array from each, dedups by title prefix,
  and assigns `high` confidence when ≥2 models agree. Degrades per-model on
  timeout. Needs LLMs.
- **`test_helper.py`** — file-level coverage (source files with no matching
  `test_*`/`*_test` stem), graph-based function-name-in-test-content coverage,
  over-mocked test detection (mock-call ratio > 0.6), and untested `Endpoint`
  nodes (empty in practice). **No LLM.**
- **`token_optimizer.py`** — fully offline. `estimate_tokens` is a three-tier
  chars-per-token heuristic (3.2/3.8/4.2 by code-punctuation density, ±12%
  claimed) chosen deliberately over a `tiktoken` dependency, so every token
  budget in JSAT is an approximation by design. `compress` runs an ordered
  pipeline: whitespace normalise → AI-filler strip → optional comment strip →
  import collapse → Jaccard sentence dedup at 0.82 → a last-resort 70/30
  head/tail "recency pin". Maintains a hardcoded `MODEL_LIMITS` table.
- **`prompt_optimizer.py`** — the most elaborate module. **Phase 1 (offline,
  always)**: `ClassifyAgent` (keyword→task type), `ContextAgent` (BFS bounded
  by a token budget, 70/30 recency split), `ConstraintAgent` (keyword-scored KB
  lookup, top 3), `FewShotAgent` (Jaccard kNN over an mtime-cached history
  JSONL), `FormatAgent` (provider-specific XML/Markdown/plain), `CompressAgent`
  (3-pass regex pruning). **Phase 2 (opt-in)**: up to three LLM agents in
  parallel — rewrite (temp 0.2), context-expand (0.3), constraint-harden (0.1)
  — scored by coverage×specificity×efficiency, winner selected.
- **`orchestrator.py`** — a 7-agent roster (understanding, generation, review,
  test, security, documentation, conflict_resolver) run **sequentially**,
  passing truncated prior output forward, with a keyword-based conflict
  detector. Overlaps heavily with `crack.py` without sharing code.
- **`knowledge.py`** — dual mode: full Graphiti/Neo4j when `jsat[team]` is
  installed, else a regex + AI extraction pipeline. It is the one place in the
  tools layer that writes non-standard labels into the graph directly. Query
  path scores by keyword + entity + recency, optionally AI-reranks the top 10,
  then synthesises. Its **decay detection** is the standout: for each retrieved
  entry it checks whether the FILE/FUNCTION entities still exist in the graph
  and auto-flags the entry stale if not — knowledge that rots is marked as
  rotten.
- **`knowledge_ingest.py`** — pure parsing: `ingest_claude_md`, `ingest_adr`
  (Nygard/MADR splitting with ADR-number extraction), `ingest_markdown`, and
  `scan_repo` globbing conventional doc locations.
- **`shell.py`** — the interactive REPL (§10).
- **`ithinking.py`** — a 7-phase meta-cognitive gate wrapped around any
  callback: ambiguity check, local-feasibility classification (routing "where
  is"/"list" to a 0-token local path), filler stripping, task decomposition,
  risky-term assumption audit, a **hard stop** on destructive patterns
  (`drop table`, `rm -rf`, `truncate`), execution, reflection. No LLM inside —
  it is policy around whatever it wraps.
- **`_patch.py`** — a hand-rolled unified-diff parser/applier, deliberately not
  shelling out to `git apply` (the validation sandbox is not a git repo and
  `patch` is absent on Windows). Rejects absolute paths, `..` traversal and
  non-`jsat/` targets; verifies every context and removal line before
  mutating; dry-runs in a `mkdtemp` sandbox; `ast.parse`s patched `.py` files.
- **`improve.py` / `improve_submit.py`** — §16.

## 9. The MCP surface

Transport is a **hand-rolled** JSON-RPC 2.0 over stdio (`MCPServer.run`,
`mcp/server.py:333`) — not the official MCP SDK. `_build_registry()` returns
one dict `name → {description, schema, handler}` of closures over the JSAT
instance; that dict is the only source of truth for what exists. There are no
MCP resources or prompts, just `initialize`, `notifications/initialized`,
`tools/list`, `tools/call` and a custom `health`.

**All 69 tools**, by theme — every one now exercised end-to-end by the
self-test:

- *Index/meta* (10): `index_repo`, `get_index_status`, `create_index_md`,
  `lookup_index_md`, `get_jsat_version`, `improve_status`, `health`,
  `export_index`, `import_index`, `get_metrics`
- *Graph exploration* (8): `list_services`, `list_endpoints`, `get_function`,
  `get_class`, `list_tables`, `trace_call_chain`, `get_data_flow`, `query`
- *Blast radius* (7): `blast_radius`, `blast_radius_file`, `blast_radius_diff`,
  `blast_radius_symbol`, `blast_radius_topic`, `get_consumers`,
  `get_consumers_of_endpoint`
- *Security* (6): `security_review`, `security_scan_file`, `list_secrets`,
  `get_auth_coverage`, `get_dependency_cves`, `trace_data_flow`
- *Tests* (6): `get_test_gaps`, `get_behavioral_coverage`,
  `list_untested_paths`, `generate_unit_test`, `generate_integration_test`,
  `generate_contract_test`
- *API contract* (3): `get_api_diff`, `check_breaking_changes`,
  `get_compat_score`
- *Migration* (3): `validate_migration`, `estimate_lock_duration`,
  `suggest_zero_downtime`
- *Review* (3): `submit_for_review`, `get_review_findings`,
  `get_high_confidence_bugs`
- *Knowledge* (5): `knowledge_query`, `knowledge_add`, `knowledge_search`,
  `knowledge_list`, `knowledge_flag_stale`
- *Incident* (4): `investigate_incident`, `get_hypotheses`,
  `get_recent_changes`, `generate_runbook`
- *IThinking* (5): `ithinking_plan`, `ithinking_execute`, `ithinking_reflect`,
  `ithinking_audit_assumptions`, `ithinking_token_estimate`
- *Prompt* (4): `prompt_diff`, `prompt_optimize`, `prompt_rewrite`,
  `prompt_multi_agent`
- *Token* (3): `token_count`, `token_compress`, `token_budget`
- *Multi-agent/UX* (2): `crack`, `short`

`get_hypotheses` is intentionally a pointer ("call `investigate_incident`
first"), since hypotheses are not stateful.

**The reliability engine is the most distinctive code in the project.**
Hierarchical per-depth timeout budgets halve with nesting (120→30→15→8→4→2→1s);
a hard call-depth cap of 7 rejects recursion with actionable `ai_guidance`;
per-tool soft budgets run a background monitor thread that emits
`notifications/progress` at the budget and hard-kills at 5× via
`future.result(timeout=…)`. Because Python cannot kill a running thread,
abandoned futures are *tracked* in `_abandoned_futures` and warned about on the
next call rather than silently leaked. Every timeout and depth-exceed also
feeds the self-improvement store, closing the loop on itself. All of it is now
verified live: the 1s soft budget fires a correctly-tokened progress
notification while the call continues, and — per MCP spec — sends nothing when
the client supplied no `progressToken`.

**Auth** is optional and off by default with a startup warning
(`JSAT_MCP_ALLOW_INSECURE=1` silences it). Two mechanisms, both env-driven and
both keyed off `params["_auth_token"]`: a shared bearer token
(`JSAT_MCP_TOKEN`, compared with `hmac.compare_digest`) and RBAC
(`JSAT_MCP_TOKEN_ROLES`, a JSON token→role map over `viewer`/`developer`/
`admin`). Verified live: an unknown token is refused, and a `viewer` token can
read the graph but is denied `security_review`. As of 0.4.17 every registered
tool is reachable by a named role except `import_index`, which is admin-only
because it replaces the entire graph.

**Dashboard** (`mcp/dashboard.py`, stdlib-only) — one persistent `HTTPServer`
on port 7432, one browser tab per named `/jsat` session, showing a live
collapsible call tree over Server-Sent Events at `/jsat/events`. Enabled
per-call by the universal `_dashboard`/`_dashboard_session` schema params
injected into every tool. Sessions idle out after 30s. Verified live: a real
tool call starts it, both the session and landing pages serve, and the SSE
stream delivers frames for an in-flight call.

**Prometheus** (`mcp/prometheus.py`) — a fully optional side-car that no-ops
unless `prometheus_client` is installed *and* `JSAT_METRICS_PORT` is set,
exporting `jsat_tool_calls_total{tool,status}`,
`jsat_tool_duration_seconds{tool}`, `jsat_graph_nodes_total` and
`jsat_cache_hits_total{tool}`. It binds synchronously so a port conflict
surfaces immediately. Verified live, including that the counter increments for
real calls.

## 10. The CLI surface

41 top-level commands, all registered on one Typer app assembled by importing
every `_cli_*` module from `jsat/cli.py`, which wraps `app()` in a crash net
that feeds `record_signal` on genuine bugs (never on `SystemExit`/`Exit`/
`Abort`, since every ordinary user error raises those).

- **Graph & index** — `index` (`--branch --force --languages
  --incremental/--full --watch`), `doctor` (`--refresh --json`), `export`,
  `import`, `clean`, `remove`
- **Analysis** (new in 0.4.17) — `blast-radius`, `contract-check`,
  `security-review`, with `--diff`, `--output`, `--base`, `--sarif` and
  non-zero exits on breaking changes or critical findings
- **Tools** — `crack`, `short`, `prompt`, `tokens`, `knowledge-ingest`,
  `improve`, `session` (list/show/resume/rm/prune), `note` (add/list/search)
- **AI launchers** — `shell`, `claude`, `bob`, `gpt`, `ollama`, `codex`,
  `cursor`, `windsurf`, `gemini`, `zed`
- **Lifecycle** — `start`, `stop`, `restart`, `resume`, `ps`
- **Setup** — `connect`, `disconnect`, `ai` (status/use/test/models), `skills`,
  `init`, `ci-setup`, `mcp-server`
- **Package** — `version`, `update`

The **lifecycle** model has no daemon: `start` runs the tool in the foreground
and returns its exit code, tracking it in `~/.jsat/runtime/<tool>.json` written
atomically at mode 0600. Its best idea is PID-reuse resistance: `process_token`
fingerprints a process by its `/proc/<pid>/stat` start time, so a recycled PID
is not mistaken for the tracked client — verified both ways against this
interpreter's own PID. `stop` SIGTERMs the whole descendant tree (via `/proc`,
`psutil` fallback), polls 5s, and only SIGKILLs with `--force`. `start all`
fans out into separate terminal windows via `x-terminal-emulator`/
`gnome-terminal`/`konsole`/`xfce4-terminal`.

**`jsat shell`** is a readline REPL with persistent history, tab completion
over commands, provider aliases and up to 150 live graph symbols. It handles
piped stdin. Beyond the analysis built-ins it can `switch` provider — either
swapping its own lightweight backend or **launching a real external CLI** with
a temp MCP config pointing back at `jsat mcp-server`. Anything unmatched is
sent as AI chat, run through the prompt optimizer first unless `opt off`.
Inline API-key prompting uses masked `getpass` and `shlex.quote`s any
shell-profile persistence.

## 11. The Python SDK

`from jsat import JSAT` exposes 18 public methods, all verified: `index`,
`index_stream` (a generator of real progress events), `index_status`, `query`,
`blast_radius`, `security_review`, `investigate_incident`, `export`,
`from_import`, `import_archive`, `reload_graph`, `switch_ai`, `doctor`,
`active_ai_label`, `prompt`, `prompt_and_send`, `prompt_stream`,
`token_count`/`token_budget`/`token_compress`. `jsat/__init__.py` re-exports
these plus 28 exception classes, every one of which derives from `JSATError`.

One naming hazard: `jsat.IndexError` shadows the builtin within the namespace,
and `__all__` invites `from jsat import IndexError`.

`switch_ai` accepts any of 27 documented aliases. Eight switch outright; the
other 19 deliberately refuse until given an explicit model, because
`require_explicit_model()` enforces that JSAT ships no hardcoded model
catalogue — each raising a `ValueError` naming the exact `jsat ai models` /
`jsat ai use` command to run. That is a feature, and the self-test asserts the
*actionability* of the refusal rather than its absence.

## 12. Slash commands and the dispatcher

47 files in `jsat/commands/`, each frontmatter (`description:`) plus a body
instructing the AI which `jsat__*` tools to call and how to format the answer.
`jsat connect claude` compiles them into a single **`/jsat` dispatcher**
(`.claude/commands/jsat.md`, ~5,100 lines) that parses `/jsat <command> [flags]
<args>`, applies an LLM input-correction pass unless `raw=true`, extracts two
universal flags — `timeout=N` → `_budget`, `dashboard=true` → `_dashboard` —
then routes to the matching `### <command>` section. `jsat-help.md` is a
generated index. Grouped by theme: exploration (10), impact/risk (6),
security/quality (5), workflow orchestration (7), git (4), knowledge/decisions
(4), prompt/token (5), ops/incident (2), meta (4 — including `internet`, the
one command sanctioned to use `WebSearch`/`WebFetch` instead of `jsat__*`).

As of 0.4.17 the registry has **one** source of truth: `_JSAT_SKILLS` is
derived from these files rather than duplicating them, which is what
Continue.dev and Bob install from. Previously the two had drifted — ten command
files had no entry, so those users silently received a smaller command set than
Claude users.

## 13. Connectors

`jsat connect <tool>` edits configuration that belongs to other programs, so
the interesting property is not that it writes but that it **merges**. All
seven JSON/TOML targets are verified to round-trip: connect adds the jsat
entry, preserves a pre-existing unrelated key, and disconnect removes only
JSAT's own entries.

| Tool | Config | Guidance |
|---|---|---|
| Claude Code | `.claude/settings.json` (project or `--global`) | `CLAUDE.md` block + `/jsat` dispatcher |
| Codex | `~/.codex/config.toml` | `~/.codex/skills/jsat/SKILL.md` |
| OpenCode | `opencode.json` | commands dir |
| Cursor | `~/.cursor/mcp.json` | `.cursorrules` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `.windsurfrules` |
| Zed | `~/.config/zed/settings.json` | `.zed/JSAT.md` |
| Gemini CLI | `~/.gemini/settings.json` | `GEMINI.md` |
| Continue.dev | `~/.continue/config.json` (array form) | 46 custom commands |
| Bob Shell | `.bob/settings.json` | `BOB.md` + 46 commands |
| Ollama | delegates to Ollama's own launcher wiring | — |
| GitHub | wires *GitHub's* MCP server alongside JSAT | — |

Only `claude`, `codex` and `bob` accept `--global`/`--scope`; the rest always
write their tool's user-level config. Two defensive touches are verified:
a pre-existing malformed config causes a clean refusal with the file left
byte-identical (`_read_json_or_abort`), and `connect github --token-env`
validates the env-var name against `[A-Za-z_][A-Za-z0-9_]*` before it is
interpolated into a `sh -c` string — a real shell-injection vector, closed, and
confirmed closed by a hostile-input test. Only the *name* of the PAT variable
is ever written to disk.

## 14. AI providers

`AIProvider` (`_ai/__init__.py:52`) declares `complete`, `complete_async`,
`stream`, `provider_name`, `model_name`, `is_available`. `get_ai_provider()`
dispatches on nine names; a missing optional dep raises `ProfileError` naming
the extra to install.

The **CLI-subprocess providers** are the strategically important ones, because
they need no API key: `claude_cli` (`claude -p`), `codex_cli` (`codex exec`
with `--sandbox read-only --ephemeral`, prompt piped via stdin to avoid ARG_MAX
and process-listing leakage), `bob_cli`, `opencode_cli`. They pass an explicit
model through untouched and never substitute one. `claude_cli` and `bob_cli`
support a **stateful** mode (`--continue`/`--resume`) for the interactive
shell, versus stateless for the MCP server so the host tool owns its own
history. `opencode_cli` disables JSAT inside its own nested subprocess env to
prevent infinite self-invocation.

The **API providers** (`anthropic`, `openai`, `openai_compat`) read a key from
a configurable env var name, never from config files, and translate SDK errors
into JSAT's typed hierarchy — verified: with no key set, all three raise a
typed `AIError` rather than a raw traceback.

**Ollama** supports both the local daemon and Ollama Cloud (`:cloud` suffix
detection), falling back from the optional SDK to a stdlib httpx client, and
turns an opaque 404 into a message listing installed models.

**`aliases.py` is the single source of truth** for 27 human names across the
SDK, the shell and `jsat ai use`, mapping each to `(provider, default_model,
base_url, api_key_env)`. `claude` resolves to `claude_cli` when the binary is
on PATH and to the `anthropic` API otherwise — decided at call time, not
import. Gemini/DeepSeek/LM Studio all route through `openai_compat` with preset
base URLs. `suggest()` does `difflib` typo correction.

**`routing.py`** resolves which backend the *launching* process already owns,
so JSAT's tool calls do not fight over models — reading
`OPENCODE_CONFIG_CONTENT` or the `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN=
ollama` combination. It explicitly never forwards a model across providers,
with a comment recording the bug that motivated it (Codex receiving Ollama
model names).

## 15. Configuration, lifecycle, sessions

**Config precedence** (`load_config`): explicit arg → `$JSAT_CONFIG` →
`{repo}/.jsat/config.yaml` → `{repo}/.jsat.yaml` → `./.jsat/config.yaml` →
`./.jsat.yaml` → `~/.jsat/config.yaml` → `~/.config/jsat/config.yaml` →
`/etc/jsat/config.yaml`. First file wins; **nothing is merged across levels**.
`CI=true` then forces `embeddings.provider=none`, `cache.backend=memory`,
`ithinking.mode=silent`.

**Data directory** (`jsat_data_dir`): `$JSAT_DATA_DIR` → an existing
non-trivial `{repo}/.jsat/` → else `~/.jsat/<sha1_12(repo_path)>/`.

**Profiles** — four presets (`solo`, `team`, `ci`, `raspberry-pi`).
`detect_system()` pings Ollama/Neo4j/Qdrant/Redis and checks RAM/arch to pick
one, caching to `system-profile.json`. `auto_configure()` layers the preset on
but **preserves anything explicitly set** via `model_fields_set` — without
that it silently reverted a user's explicit `codex_cli` choice back to Ollama.
If the configured provider is unreachable it falls back through a fixed
priority order (CLI tools > hosted APIs > Ollama > LM Studio).

**Sessions** are resumable-task records for long-running skills, stored as
human-editable Markdown with YAML frontmatter in `~/.jsat/sessions/`
(`<skill>-<slug>-<YYYYMMDD-HHMM>.md`), holding `## Steps` checkboxes and
`## Findings`. Parsing is deliberately tolerant so a hand-edited or truncated
file still loads.

## 16. Self-improvement and the privacy invariant

This is the part of JSAT most deserving of trust, and the part where being
wrong would be worst: JSAT records friction in *itself* while running on other
people's private codebases.

**Capture** — `record_signal(kind, source, exc, op, detail)` is called from
`except` blocks and is guaranteed never to raise (wrapped in
`except BaseException: pass`). Buffered in memory, flushed on 10 records, 60s,
or `atexit`. Per-fingerprint throttling collapses tight retry loops into a
suppressed count; capped at 50 records per process. A CLI nudge prints to
stderr past a threshold, behind a **dual-TTY check** so it can never pollute
MCP stdio or `--json | jq`.

**Sanitisation is "drop, never redact."** Stage one keeps only
package-relative frames (anything outside the package collapses to
`<external>`), exception *type* names, and messages matching a fixed allowlist
of ~28 JSAT-authored prefixes — the raw message is never stored, because
messages interpolate user paths. Context values survive only if the key is
allowlisted and the value is short and alnum-ish. Stage two, `verify_clean`, is
an **adversarial second pass** re-scanning the finished blob — and every bundle
file, *including AI-generated output* — for absolute paths, the machine's home
dir/username/cwd, known secret patterns, high-entropy tokens, and any value
from `os.environ`. Any hit drops the whole record. Fingerprints deliberately
exclude line numbers and version so occurrences cluster across releases.

**Storage** is `~/.jsat/improve/`, never inside a repo. `_safe_write` resolves
every target and refuses anything outside the improve dir — that structural
guarantee is *why* JSAT cannot patch its own installed source.

**The loop**: `jsat improve` reads clusters, locates the failing function by
*name* (not line number, which drifts), asks the AI for an analysis and a
unified diff, validates the diff in a throwaway sandbox, and writes an inert
bundle. `--report` only pre-fills a GitHub issue — a human presses Submit.
`--submit` is maintainer-only and refuses unless `git remote origin` matches
the real JSAT repo.

All of this is verified by independent means: the self-test triggers a real
crash and then scans the stored bytes itself — not by asking `verify_clean`,
which is the code under test — for home dirs, usernames, cwd, absolute paths
and every environment variable's value; it plants a poisoned record and asserts
it is dropped whole; it hashes the installed `jsat/` tree before and after
`jsat improve` to prove nothing was patched; and it confirms `doctor --json`
stays machine-readable with 99 pending signals on disk.

## 17. Quality posture

**pytest** — 46 files, 709 tests, `asyncio_mode=auto`. Only the `ci` marker is
actually applied (`integration`/`slow` are declared but unused, because tests
that would need live services instead test the guard logic). House style is
`MagicMock` for the whole `JSAT` object plus hand-rolled `Fake*` classes for
process-shaped things. State is isolated via `JSAT_IMPROVE_DIR`/
`JSAT_SESSIONS_DIR`/`JSAT_DATA_DIR` so a run never touches `~/.jsat`.

**The self-test** (`scripts/selftest/`) is the no-mocking counterpart: real
subprocesses, a real multi-language fixture repo with real git history and
tags, the real MCP server over real stdio, real connector files, and the built
wheel installed into a clean virtualenv. ~230 checks across 12 selectable
suites. Three properties make it worth maintaining: **coverage gates** turn the
suite red when a new MCP tool, CLI command or public SDK method is added
without a case; the only thing ever substituted is a *third-party* binary
(a recorder stub in place of `claude`/`codex`, so launcher argv and the
generated `--mcp-config` can be asserted without a TTY); and `unavailable` is
strictly distinguished from `fail`, so a missing dependency is never a false
alarm and never a silent skip.

**CI** — `ci.yml` runs `pytest -m ci` on 3.10/3.11/3.12 with core deps only,
plus `ruff check jsat/ tests/` with no inline overrides. `publish.yml` triggers
on `v*` tags, validates the tag against `pyproject.toml` *before* building, and
uses PyPI trusted publishing (OIDC, no stored token). `docs.yml` runs
`mkdocs gh-deploy`. Release convention (`RELEASING.md`): PEP 440, and the
version must be bumped in **both** `pyproject.toml` and `jsat/__init__.py`.

**Docs** — an MkDocs Material site organised by integration path first:
per-tool pages (Claude/Codex/OpenCode/Bob, each with an "+ Ollama" variant),
then `architecture.md` (the deepest), `getting-started.md`,
`ai-integrations.md`, `ai-providers.md`, `cli-reference.md`, `tools.md`,
`sdk.md`, `configuration.md`, `publishing.md`, `claude-integration.md`.
`mkdocs build --strict` is clean.

## 18. Verified findings

Twenty-eight defects found by running the real artifact and then reviewing the fixes; all fixed in 0.4.17. Ordered by severity.
Full detail in `CHANGELOG.md`.

| # | Finding | Why it mattered |
|---|---|---|
| 1 | `jsat export` wrote an **empty archive** — it copied `graph.db` while rows were still in the WAL, while the manifest reported the true count | Silent data loss in the backup feature; the archive looked correct until restored |
| 2 | `jsat import` restored nothing usable; via MCP it then broke **every subsequent call** with "closed database" | The graph file was replaced under a live connection |
| 2b | A **profile preset overrode explicit config** — a Neo4j container running for anything else made `detect_system` pick `team`, replacing `graph.backend: sqlite` with `neo4j`, and indexing failed | Anyone with Neo4j on :7687 got a broken JSAT, regardless of what they configured |
| 2c | `cache.backend: redis` crashed on `None.startswith` when no `redis_uri` was set | The documented default was never applied |
| 2d | The **`anthropic` provider was broken for every caller** — it sent `temperature`, removed from the Messages API and dropped from the 1.x SDK, so every call raised `TypeError` regardless of the key; it also indexed `content[0]`, which is a thinking block on current models | `ai.provider: anthropic` could not complete a single request |
| 2e | The **MCP shim never pinned its paths**, so `export_index` zipped no database and `import_index` restored into the editor's cwd — both reporting success | Same silent-empty-archive class, via the other surface |
| 2f | `blast-radius --diff <git range>` was forwarded as diff *text* → zero changed files, zero impact, exit 0 | The `ci-setup` step was green by construction |
| 2g | The **capacity guard counted upserts as growth** | `index --force` failed on any repo above ~half the cap |
| 3 | `get_data_flow` and `get_consumers` **never worked** — both called `graph.edges()`, which no backend implemented, with a `# type: ignore` silencing the warning | Two advertised MCP tools always returned an error |
| 4 | `security_scan_file` gave a **false all-clear for any file** — `rglob` on a file path yields nothing | Worst possible failure mode for a security tool |
| 5 | MCP file arguments resolved against the server's cwd, not `--repo`; `validate_migration` raised ENOENT while `security_scan_file`, `list_secrets` and `get_test_gaps` silently scanned nothing | Agents pass repo-relative paths, which is what the graph stores |
| 6 | TypeScript, Java, Ruby and Rust files were **never indexed** — the default language list was three of seven | Contradicted documented language support, silently |
| 7 | `jsat ci-setup` generated a workflow calling three commands that did not exist | Anyone following it got broken CI |
| 8 | **26 of 69 MCP tools** were unreachable by any non-admin role | Securing the server silently removed a third of the toolset |
| 9 | `get_dependency_cves` reported "not implemented — planned for v0.3" while the osv.dev lookup was already working inside `security_review` | An advertised capability turned away |
| 10 | `graph.max_nodes`/`max_edges` were never enforced | `GraphCapacityError` could not fire |
| 11 | `_JSAT_SKILLS` duplicated `commands/*.md` and had drifted 10 entries | Continue and Bob users got a smaller command set than Claude users |
| 12 | All 7 skill clusters named skills that never existed | Every cluster resolved to nothing |
| 13 | One slash command referenced a nonexistent `jsat__tokens` | Silent runtime no-op |
| 14 | A docs link outside the docs tree broke `mkdocs build --strict`; README documented `jsat smart` as a shell command | Broken published docs |

Also corrected as honesty fixes rather than bugs: `graph.backend: neo4j` now
warns at construction naming exactly what degrades; the embeddings and
vector-store config is marked **NOT YET WIRED IN** at the schema and in the
docs; the inert `cache.similarity_threshold` (documented as doing cosine
matching no cache performs) is removed; and the dead second tool catalogue
`jsat/mcp/tools.py` — 52 entries, imported by nothing, drifted to under 70% of
the real registry while reading like ground truth — is deleted.

## 19. Remaining gaps

Honest list of what a reader should still know. None is a regression; all are
tracked in `AGENTS.md` §9.

1. **`Service`/`Endpoint`/`Table`/`Topic` are still not persisted.** The MCP
   server infers services and endpoints heuristically per request, so it reports
   services while the SDK and `jsat query` see none on the same repo. Moving
   the inference into the indexer would make all three surfaces agree. This is
   the biggest remaining correctness gap.
2. **`mypy` is declared `strict = true` and not enforced** — ~377 errors across
   58 files, and CI runs only ruff. The self-test ratchets the count so it
   cannot grow and reports the declaration-vs-reality gap as its own finding.
3. **`_MinimalJSAT` is a second JSAT-shaped object** maintained by hand. Any
   method an MCP tool calls must be mirrored there; `import_archive` was missed
   exactly this way during this release.
4. **Embeddings and vector stores remain unwired** — implemented, tested, zero
   call sites. Now documented as such.
5. **`skills/` (the YAML registry) is dormant** — `registry.run()` executes only
   `source.type == "script"` and no manifests ship, so clusters are correct as
   documented *orderings*, not as an execution engine.
6. **Neo4j is partial by design** and now says so.
7. **`crack.py` and `orchestrator.py` are near-duplicate multi-agent engines**
   with large inline prompts and no shared code.
8. **`mcp/server.py` is the biggest cohesion problem** — `_handle` is ~450
   lines juggling auth, RBAC, budgets, dashboards, metrics and error shaping.
9. **Token accounting is heuristic by design** (chars-per-token, ±12%), so
   every budget decision is approximate.
10. **A moved or renamed checkout silently orphans its index**, because the
    global store is keyed by a hash of the absolute repo path.
11. **`bob_cli` ships without confirmed ground truth** for Bob Shell's NDJSON
    event schema (there is a TODO in the module to verify it).
12. **`integration`/`slow` pytest markers are declared but unused.**

## 20. Assessment

JSAT is substantially more solid than its 0.4.x "Alpha" classifier suggests,
and the gap between its best and worst parts is wide.

The best parts are genuinely thoughtful. The MCP reliability engine — depth-
halved budgets, soft-notify then hard-kill, tracked abandoned futures, and
feeding its own timeouts back into the improvement store — is better than most
production MCP servers. The self-improvement privacy design ("drop, never
redact", plus an adversarial second pass applied to the LLM's own output) is
unusually rigorous for telemetry. The knowledge layer's decay detection, the
security scanner's sequential-charset filter, the PID-reuse-resistant process
tracking, and the deliberate refusal to hardcode a model catalogue are all
signs of someone who has been bitten and fixed the root cause rather than the
symptom. `AGENTS.md` is candid about debt in a way most projects are not.

The weakness is uniform and diagnosable: **the surfaces were tested by
construction, not by use.** Almost every one of the findings above is a case
of code that type-checks, passes 709 unit tests, reads correctly, and does not
work when actually invoked — a method that exists nowhere behind a
`type: ignore`, an `rglob` on a file path, a WAL that had not been checkpointed,
a default list with four of seven entries. Unit tests with a `MagicMock` JSAT
cannot catch any of them, and that is exactly the class the rebuilt self-test
now covers, with coverage gates so the next addition cannot skip it.

The remaining structural issue worth prioritising after this release is item 1
in §19: three surfaces that disagree about whether the graph contains services
is a correctness problem that no amount of testing papers over, and it
undermines the tool's central claim of being one shared substrate.
