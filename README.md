# JSAT — JaySoft AI Tools

<!-- Logo placeholder -->
<!-- ![JSAT Logo](docs/logo.png) -->

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/jsat.svg)](https://pypi.org/project/jsat/)

**Codebase intelligence for AI sessions — index once, query forever, works with any AI.**

---

## What is JSAT?

Every AI session starts with the same problem: you spend the first ten minutes re-explaining your architecture, re-pasting function signatures, and re-describing how services talk to each other. JSAT solves this by building a persistent graph of your codebase once — functions, classes, files, services, API endpoints, database tables, Kafka topics, and every relationship between them — and making that context instantly available to any AI you use.

JSAT works as a CLI, a Python SDK, and an MCP server that plugs directly into Claude Code. If Claude Code CLI is installed, JSAT uses it automatically with no API key required. For everything else — Anthropic API, OpenAI, Gemini, Ollama, LM Studio — one command switches the provider.

---

## Quick Start

```bash
pip install jsat

# Wire JSAT into Claude Code (if installed — no API key needed)
jsat connect claude

# Index your project
cd your-project/
jsat index .

# Open Claude with full codebase context and JSAT tools available
jsat claude
```

Inside Claude Code you can then use slash commands:

```
/jsat-query what does the payment service do?
/jsat-blast-radius src/payment/refund.py
/jsat-security
/jsat-incident "500 errors spiking on checkout"
```

---

## Installation

JSAT ships as a minimal core with optional extras. Install only what you need.

| Extra | What's added | Approx. size | When to use |
|---|---|---|---|
| *(none)* / `core` | tree-sitter parsers, SQLite graph, CLI | ~80 MB | Starting point for any setup |
| `local` | Ollama client | +small | Local models via Ollama |
| `standard` | Semgrep, OpenAPI/AsyncAPI validator, more language parsers (Java, Ruby, Rust) | +medium | Security reviews, API contract checks |
| `team` | Neo4j, Qdrant, Redis, Graphiti (includes `standard`) | +large | Shared graph across a team |
| `anthropic` | Anthropic Python SDK | +small | Claude API (key required) |
| `openai` | OpenAI Python SDK | +small | GPT-4o, GPT-4o-mini (key required) |
| `ci` | PyGitHub, SARIF tools (includes `standard`) | +small | CI/CD pipelines, GitHub Actions |
| `all` | Everything above | +large | Full feature set |

```bash
pip install jsat                   # core only
pip install 'jsat[local]'          # + Ollama
pip install 'jsat[standard]'       # + security analysis, OpenAPI validation
pip install 'jsat[team]'           # + Neo4j, Qdrant, Redis
pip install 'jsat[anthropic]'      # + Claude API SDK
pip install 'jsat[openai]'         # + OpenAI SDK
pip install 'jsat[all]'            # everything
```

---

## AI Providers

JSAT auto-detects available providers at startup and picks the best one in priority order:

1. **Claude Code CLI** — detected via `which claude`; no API key, no extra SDK, full tool calling
2. **Anthropic API** — if `ANTHROPIC_API_KEY` is set and `jsat[anthropic]` is installed
3. **OpenAI** — if `OPENAI_API_KEY` is set and `jsat[openai]` is installed
4. **Ollama** — if `ollama serve` is running at `localhost:11434`
5. **LM Studio** — if an OpenAI-compatible server is running at `localhost:1234`
6. **No AI** — tools that don't need AI (indexing, blast radius, export) still work

### Check what's available

```bash
jsat ai status        # shows all providers, which is active, and switch commands
```

### Switch providers

```bash
jsat ai use ollama                        # free, local, no key
jsat ai use ollama --model qwen2.5-coder:7b
jsat ai use anthropic                     # needs ANTHROPIC_API_KEY
jsat ai use openai --model gpt-4o-mini    # needs OPENAI_API_KEY
jsat ai use lmstudio                      # any OpenAI-compat server at localhost:1234
jsat ai test                              # verify the configured provider works
```

### Switch inside the JSAT shell

```
switch claude    → Claude Code CLI (no key) or Claude API
switch gpt       → GPT-4o
switch ollama    → local Ollama
switch haiku     → Claude Haiku
switch phi       → phi3:mini (fast, low RAM)
switch lmstudio  → LM Studio
```

---

## Claude Code Integration

JSAT's tightest integration is with Claude Code. One command registers JSAT as an MCP server and installs `/jsat-*` slash commands. After that, Claude can call JSAT tools automatically — or you can invoke them explicitly.

### Setup

```bash
jsat connect claude                       # project-level (this repo only)
jsat connect claude --scope global        # global (all Claude Code sessions)
```

Restart Claude Code. JSAT tools are now available.

### Open Claude with JSAT context pre-loaded

```bash
jsat claude
```

### Slash commands installed into Claude Code

| Command | What it does |
|---|---|
| `/jsat-query <question>` | Natural language query over the indexed graph |
| `/jsat-blast-radius <file or symbol>` | Trace downstream impact grouped by severity |
| `/jsat-security [path]` | Security scan — Critical and High issues first |
| `/jsat-incident <description>` | Root-cause hypotheses ranked by confidence |
| `/jsat-index [path]` | Rebuild the codebase graph |
| `/jsat-status` | Node and edge counts |
| `/jsat-doctor` | Full health check |

### MCP tools Claude can call automatically

JSAT exposes 47 MCP tools across 12 categories. Highlights:

- `jsat__query` — answer any codebase question
- `jsat__blast_radius_file`, `jsat__blast_radius_diff`, `jsat__blast_radius_symbol`, `jsat__blast_radius_topic`
- `jsat__security_scan_file`, `jsat__get_auth_coverage`, `jsat__list_secrets`, `jsat__get_dependency_cves`
- `jsat__investigate_incident`, `jsat__generate_runbook`
- `jsat__check_breaking_changes`, `jsat__get_compat_score`
- `jsat__validate_migration`, `jsat__suggest_zero_downtime`
- `jsat__submit_for_review`, `jsat__get_high_confidence_bugs`
- `jsat__ithinking_plan`, `jsat__ithinking_execute`

### Connect to Cursor

```bash
jsat connect cursor        # writes to ~/.cursor/mcp.json
```

### Disconnect or remove

```bash
jsat disconnect claude                        # project-level
jsat disconnect claude --scope global         # global
jsat disconnect claude --scope all            # everywhere
jsat remove                                   # remove all JSAT artifacts from this repo
```

---

## CLI Reference

### Core commands

| Command | Description |
|---|---|
| `jsat index [path]` | Build or update the codebase graph |
| `jsat index . --force` | Full re-index (skip incremental check) |
| `jsat index . --languages python,go` | Index specific languages only |
| `jsat shell` | Start the interactive JSAT REPL |
| `jsat claude` | Open Claude Code with JSAT MCP tools loaded |
| `jsat gpt` | Open a GPT session with JSAT tools |
| `jsat ollama [--model llama3.2]` | Open a local Ollama session |
| `jsat doctor` | System health check (graph, AI, services) |
| `jsat doctor --json` | Health check as raw JSON |
| `jsat version` | Print JSAT version |

### Configuration

| Command | Description |
|---|---|
| `jsat init` | Generate `.jsat/config.yaml` (default: `solo` profile) |
| `jsat init --profile team` | Team profile (Neo4j, Qdrant, Redis, Claude API) |
| `jsat init --profile ci` | CI profile (SQLite, no AI, JSON logs) |
| `jsat init --profile raspberry-pi` | Low-RAM profile (SQLite, phi3:mini, batch size 8) |

### AI provider management

| Command | Description |
|---|---|
| `jsat ai status` | Show all providers: available, active, free/paid |
| `jsat ai use <provider>` | Configure a provider and write to config |
| `jsat ai use ollama --model phi3:mini` | Use a specific Ollama model |
| `jsat ai test` | Send a test prompt and verify the provider works |
| `jsat ai models` | List models available from the configured provider |

### Claude Code integration

| Command | Description |
|---|---|
| `jsat connect claude` | Wire JSAT into Claude Code (project scope) |
| `jsat connect claude --scope global` | Wire JSAT globally (all sessions) |
| `jsat connect claude --no-skills` | MCP only — skip installing slash commands |
| `jsat connect cursor` | Wire JSAT into Cursor |
| `jsat connect list` | Show all active JSAT MCP configs |
| `jsat disconnect claude` | Remove from project Claude Code config |
| `jsat disconnect claude --scope all` | Remove from all scopes |

### Export and import

| Command | Description |
|---|---|
| `jsat export backup.jsat.zip` | Export the current index as a portable zip |
| `jsat export backup.jsat.zip -z 9` | Export with maximum compression |
| `jsat import backup.jsat.zip` | Restore an index from an exported archive |

### Skills

| Command | Description |
|---|---|
| `jsat skills list` | List installed JSAT skill manifests |
| `jsat skills run <name>` | Run a named skill with optional `key=val` args |

---

## Python SDK

```python
from jsat import JSAT

# Instantiate — auto-detects AI provider, loads config
js = JSAT(repo=".")

# Build the graph (incremental by default)
result = js.index()
print(f"Indexed {result.nodes_indexed} nodes, {result.edges_indexed} edges")

# Natural language query over the graph
result = js.query("what calls the refund endpoint?")
print(result.answer)

# Trace blast radius of a change
report = js.blast_radius("src/payment/refund.py")
for item in report.impacts:
    print(f"{item.severity:10s}  {item.node_id}")

# Security analysis (requires jsat[standard])
sec = js.security_review(path="src/")
for finding in sec.findings:
    print(f"{finding.severity}: {finding.title} — {finding.file}:{finding.line}")

# Incident investigation
incident = js.investigate_incident("500 errors on checkout", since="24h")
for h in incident.hypotheses:
    print(f"[{h.score:.0%}] {h.title}")

# Export the index for sharing or CI caching
manifest = js.export("snapshot.jsat.zip")
print(f"Exported {manifest.size_mb:.1f} MB")

# Restore from an export
js2 = JSAT.from_import("snapshot.jsat.zip")

# Switch AI provider mid-session
js.switch_ai("ollama", model="qwen2.5-coder:7b")
js.switch_ai("anthropic")
js.switch_ai("gpt", model="gpt-4o-mini")

# Health check
health = js.doctor()
print(health["profile"], health["graph"]["backend"])
```

---

## Tools Overview

| # | Tool | Description |
|---|---|---|
| 0 | **JSAT Shell** | Interactive REPL — run any tool directly, switch AI mid-session, no AI required |
| 1 | **Directory Indexer** | Walks a repo, parses source with tree-sitter, writes nodes and edges to the graph |
| 2 | **Test Intelligence Helper** | Finds test gaps, maps behaviors to coverage, generates unit/integration/contract tests |
| 3 | **Feature Helper** | Answers "how do I add X?" using graph context — finds relevant files and patterns |
| 4 | **Blast Radius Analyzer** | BFS over the graph to trace downstream impact; classifies edges as breaking/degraded/warning/safe |
| 5 | **API Contract Validator** | Diffs OpenAPI/AsyncAPI specs, classifies breaking changes, scores backward compatibility (0–100) |
| 6 | **Security Review Agent** | OWASP pattern scan, auth coverage gaps, hardcoded secret detection, dependency CVE lookup |
| 7 | **Incident Investigation Helper** | Correlates an incident description against recent commits and graph topology; ranks root-cause hypotheses |
| 8 | **Migration Safety Validator** | Validates migration files, estimates lock duration, generates zero-downtime migration plans |
| 9 | **Multi-Model Code Review** | Submits a diff to multiple AI models independently; surfaces only bugs confirmed by two or more |
| 10 | **Knowledge Base Builder** | Persistent searchable store of architectural decisions, runbooks, and tribal knowledge |
| 11 | **Multi-Agent Orchestrator** | Decomposes a task and runs specialized sub-agents (understanding, generation, review, test, security, docs) |
| 12 | **Export / Import System** | Portable zip snapshots of the full graph — share between machines, cache in CI, restore in seconds |
| 13 | **Python SDK** | Programmatic access to every tool via `from jsat import JSAT` |
| 14 | **IThinking Meta-Cognitive Layer** | Structured seven-phase reasoning: clarify, plan, context, assumptions, execute, reflect — with human approval gates |

---

## Graph Schema

JSAT indexes these node types and relationship edges:

**Nodes:** `function`, `class`, `file`, `service`, `endpoint`, `table`, `kafka_topic`

**Edges:**

| Edge | Meaning |
|---|---|
| `CALLS` | Function A calls function B |
| `IMPORTS` | File A imports module B |
| `READS_FROM` | Code reads from a table or topic |
| `WRITES_TO` | Code writes to a table or topic |
| `PRODUCES` | Service produces a Kafka message |
| `CONSUMES` | Service consumes a Kafka topic |
| `IMPLEMENTS` | Class implements an interface |
| `INHERITS` | Class inherits from another |
| `DEPENDS_ON` | Service depends on another service |

---

## Configuration

JSAT stores all state under `.jsat/` in your repo root. The config file is `.jsat/config.yaml`.

```bash
jsat init                        # write starter config (solo profile)
jsat init --profile team         # team profile
jsat init --profile ci           # CI/CD profile
```

Key settings in `.jsat/config.yaml`:

```yaml
graph:
  backend: sqlite          # sqlite (default) | neo4j (team profile)
  path: .jsat/graph/graph.db

embeddings:
  provider: local          # local | openai | none
  model: nomic-embed-code

ai:
  provider: ollama         # ollama | anthropic | openai | openai_compat | claude_cli | none
  model: llama3.2
  base_url: null           # for openai_compat (LM Studio, Gemini, etc.)

cache:
  backend: memory          # memory | disk | redis

indexer:
  languages: [python, javascript, go, java, ruby, rust]
  exclude_patterns: ["**/node_modules/**", "**/.git/**", "**/dist/**"]
  max_file_size_kb: 500

ithinking:
  enabled: true
  mode: interactive        # interactive | silent
  gate_level: medium       # low | medium | high
```

### Profiles at a glance

| Profile | Graph | AI | Cache | Use case |
|---|---|---|---|---|
| `solo` | SQLite | Ollama / llama3.2 | Memory | Individual developer, no external services |
| `team` | Neo4j | Claude API | Redis | Shared graph, team-wide knowledge base |
| `ci` | SQLite | None | Memory | GitHub Actions, no API keys, JSON logs |
| `raspberry-pi` | SQLite | Ollama / phi3:mini | Disk | Low-RAM devices, batch size 8 |

### Config search order

JSAT finds its config by checking these locations in order (first found wins):

1. Explicit path passed to `JSAT(config=...)` or `--config` flag
2. `$JSAT_CONFIG` environment variable
3. `{repo}/.jsat/config.yaml` (canonical)
4. `{repo}/.jsat.yaml` (legacy)
5. `./.jsat/config.yaml` (CWD)
6. `~/.config/jsat/config.yaml`
7. `/etc/jsat/config.yaml`

---

## Supported Languages

| Language | Parser | Notes |
|---|---|---|
| Python | tree-sitter-python | Core (always available) |
| JavaScript / TypeScript | tree-sitter-javascript | Core |
| Go | tree-sitter-go | Core |
| Java | tree-sitter-java | Requires `jsat[standard]` |
| Ruby | tree-sitter-ruby | Requires `jsat[standard]` |
| Rust | tree-sitter-rust | Requires `jsat[standard]` |

---

## Contributing

Contributions are welcome. Please open an issue or pull request on GitHub.

- Repository: [github.com/iamjpsonkar/JaySoft-AI_Tools](https://github.com/iamjpsonkar/JaySoft-AI_Tools)
- Bug reports: open an issue on GitHub
- Author: Jay Prakash Sonkar — [iamjpsonkar@gmail.com](mailto:iamjpsonkar@gmail.com)
- License: MIT

---

## License

MIT License. Copyright (c) Jay Prakash Sonkar.
