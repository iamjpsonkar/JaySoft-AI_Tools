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

Long-running tools (`jsat__crack`, `jsat__query`, `jsat__short`, prompt rewriting) stream **live progress notifications** back to Claude Code so you see what's happening in real time — no more blank screens during 30-second operations.

---

## Quick Start

```bash
pip install jsat

# Index your project
cd your-project/
jsat index .

# Open your AI tool with JSAT pre-loaded (auto-connects on first use)
jsat claude      # Claude Code
jsat codex       # OpenAI Codex CLI
jsat cursor      # Cursor IDE
jsat windsurf    # Windsurf
jsat gemini      # Google Gemini CLI
jsat zed         # Zed editor
jsat bob         # Bob Shell

# War room discussion (new!)
jsat crack "redesign payment retry system"

# Shortest possible answer (new!)
jsat short "what does process_refund do"
```

Inside any connected tool you can use JSAT commands:

**Claude Code slash commands:**
```
/jsat query what does the payment service do?
/jsat blast-radius src/payment/refund.py
/jsat security
/jsat incident "500 errors spiking on checkout"
/jsat prompt-rewrite fix logger in ValidateVPAHandler.post
```

**Continue.dev custom commands** (same commands, `/jsat-*` prefix)

**All tools** have all JSAT MCP tools the AI can call automatically — no slash commands needed.

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
2. **Bob Shell CLI** — detected via `which bob`; no API key, IBM AI assistant with multiple modes
3. **Anthropic API** — if `ANTHROPIC_API_KEY` is set and `jsat[anthropic]` is installed
4. **OpenAI** — if `OPENAI_API_KEY` is set and `jsat[openai]` is installed
5. **Ollama** — if `ollama serve` is running at `localhost:11434`
6. **LM Studio** — if an OpenAI-compatible server is running at `localhost:1234`
7. **No AI** — tools that don't need AI (indexing, blast radius, export) still work

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
jsat ai use claude_cli                    # Claude Code CLI (no key, uses claude binary)
jsat ai use lmstudio                      # any OpenAI-compat server at localhost:1234
jsat ai test                              # verify the configured provider works

# Apply globally (all projects on this machine):
jsat ai use claude_cli --global
```

### Switch inside the JSAT shell

```
switch claude    → Claude Code CLI (no key) or Claude API
switch bob       → Bob Shell (no key)
switch gpt       → GPT-4o
switch ollama    → local Ollama
switch haiku     → Claude Haiku
switch phi       → phi3:mini (fast, low RAM)
switch lmstudio  → LM Studio
```

---

## AI Tool Integration

JSAT works as an MCP server with any AI tool that supports the Model Context Protocol. One command wires it in — the tool picks up all JSAT MCP tools automatically.

### Connect

```bash
# Recommended: one-time global setup (works in every project)
jsat connect claude --global               # Claude Code — all sessions
jsat connect codex --global               # OpenAI Codex CLI — all sessions
jsat connect bob --global                 # Bob Shell — all sessions

# Per-project (this repo only)
jsat connect claude                        # Claude Code
jsat connect codex                         # OpenAI Codex CLI
jsat connect bob                           # Bob Shell (+ /jsat-* slash commands)
jsat connect cursor                        # Cursor
jsat connect windsurf                      # Windsurf (Codeium)
jsat connect continue                      # Continue.dev
jsat connect zed                           # Zed editor
jsat connect gemini                        # Google Gemini CLI

jsat connect list                          # show every active connection
```

Restart the AI tool after connecting. JSAT's MCP tools are immediately available.

### Files written per tool

Each connect command writes both an MCP config **and** a guidance file so the AI knows what JSAT tools exist and when to use them — without being asked.

| Tool | MCP config | Guidance file | Guidance format |
|---|---|---|---|
| Claude Code (project) | `.claude/settings.json` | `.claude/commands/jsat-*.md` (31 files) | Slash commands |
| Claude Code (global) | `~/.claude/settings.json` | `~/.claude/commands/jsat-*.md` | Slash commands |
| Codex (project) | `.codex/config.json` | `.codex/instructions.md` | Agent instructions |
| Codex (global) | `~/.codex/config.json` | `~/.codex/instructions.md` | Agent instructions |
| Bob Shell (project) | `.bob/settings.json` | `BOB.md` + `.bob/commands/jsat-*.md` | Slash commands |
| Bob Shell (global) | `~/.bob/settings.json` | `BOB.md` + `~/.bob/commands/jsat-*.md` | Slash commands |
| Cursor | `~/.cursor/mcp.json` | — | — |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `.windsurfrules` | Rules file |
| Continue | `~/.continue/config.json` | `/jsat-*` custom commands | Slash commands |
| Zed | `~/.config/zed/settings.json` | `.zed/JSAT.md` | Project context |
| Gemini CLI | `~/.gemini/settings.json` | `GEMINI.md` | Project instructions |

Pass `--global` (claude/codex/bob) or check the tool's docs for global scope on others.

Pass `--no-instructions` to skip writing the guidance file (MCP only).

### `/jsat` dispatcher

`jsat connect claude` installs a single `/jsat` command rather than 34 individual `/jsat-*` commands. All skills are accessible as subcommands:

```bash
/jsat help               # list all 34 subcommands
/jsat query <question>   # answer codebase questions (Discuss→Verify pipeline)
/jsat crack <task>       # multi-agent war room with artifact carry-forward
/jsat aw <task>          # workflow advisor
/jsat lazy <task>        # reuse-first planning
/jsat smart <question>   # terse compressed answers
```

Skill files are bundled inside the JSAT package at `jsat/commands/` and sourced directly when `jsat connect claude` runs.

### Disconnect

```bash
jsat disconnect claude                     # Claude Code project scope
jsat disconnect claude --scope all         # Claude Code everywhere
jsat disconnect codex                      # Codex
jsat disconnect cursor                     # Cursor
jsat disconnect windsurf                   # Windsurf
jsat disconnect continue                   # Continue
jsat disconnect zed                        # Zed
jsat disconnect gemini                     # Gemini CLI
jsat disconnect all                        # every tool at once
```

### Claude Code — slash commands (34 total)

`jsat connect claude` installs a single `/jsat` dispatcher with 34 subcommands, organized by category:

**Graph exploration**
| Command | What it does |
|---|---|
| `/jsat query <question>` | Natural language query over the indexed graph |
| `/jsat find-function <name>` | Look up a function — file, params, return type, complexity |
| `/jsat find-class <name>` | Look up a class — file, bases, method count |
| `/jsat list-services` | List all indexed services |
| `/jsat list-endpoints` | List all API endpoints with method, route, auth |
| `/jsat trace <symbol>` | Trace a call chain from a symbol |
| `/jsat index [path]` | Rebuild the codebase graph (incremental) |
| `/jsat status` | Node/edge counts |
| `/jsat doctor` | Full system health check |

**Impact & safety**
| Command | What it does |
|---|---|
| `/jsat blast-radius <file or symbol>` | Downstream impact grouped by severity |
| `/jsat security [path]` | OWASP scan — Critical and High first |
| `/jsat migration <file>` | DB migration safety — lock type, duration estimate |
| `/jsat contract <diff>` | API contract compatibility check |

**Code quality**
| Command | What it does |
|---|---|
| `/jsat review <diff>` | Multi-model parallel code review |
| `/jsat test-gaps [path]` | Find untested paths, generate tests |
| `/jsat coverage [path]` | Behavioral coverage estimate |

**Knowledge & investigation**
| Command | What it does |
|---|---|
| `/jsat knowledge <query>` | Search the knowledge base |
| `/jsat knowledge-add <text>` | Add an ADR / runbook / decision |
| `/jsat runbook <target>` | Generate an incident runbook |
| `/jsat incident <description>` | Root-cause hypotheses ranked by confidence |
| `/jsat recent [path]` | Recent changes in an area |

**Prompt & token tools**
| Command | What it does |
|---|---|
| `/jsat prompt <query>` | Optimize a prompt through the full pipeline |
| `/jsat prompt-diff <query>` | Show raw input vs what the AI actually received |
| `/jsat tokens <text>` | Count tokens; compress to fit context limit |
| `/jsat token-budget <text>` | Check budget against the active model's context window |

**IThinking**
| Command | What it does |
|---|---|
| `/jsat ithinking <task>` | Full IThinking: plan → assumptions → decompose → confirm |
| `/jsat think <task>` | Quick shortcut — think before any task |
| `/jsat reflect <outcome>` | Record what was done (phase 6 log) |

**Analysis & planning**
| Command | What it does |
|---|---|
| `/jsat crack <task>` | Multi-agent war room with artifact carry-forward |
| `/jsat short <question>` | Minimum-word answer (≤3 sentences) |
| `/jsat smart <question>` | Terse compressed answer, filler stripped |
| `/jsat lazy <task>` | Reuse-first planning — 5-rung ladder before suggesting new code |
| `/jsat aw <task>` | Workflow advisor — classify task, run optimal tool sequence |

### Open Claude with JSAT context pre-loaded

```bash
jsat claude
```

---

## JSAT Crack — Multi-Agent War Room

Run a complex engineering decision past a panel of six specialist AI agents that argue, challenge, and respond to each other — like a real architecture meeting.

```bash
jsat crack "redesign payment retry system"
jsat crack --roles architect,security "migrate users table to UUID"
jsat crack --rounds 2 --file design.md "sync vs async webhooks"
```

**Agents (all run in parallel per round, then respond to each other):**

| Agent | Focus |
|---|---|
| 🏛 `architect` | System design, scalability, patterns |
| 🔒 `security` | Threat model, auth, idempotency |
| ⚙️ `implementer` | Current code analysis, effort estimate |
| 🧪 `tester` | Edge cases, coverage gaps |
| 😈 `skeptic` | Devil's advocate — challenges everything |
| 🎯 `moderator` | Synthesises consensus and action plan |

**Phased mode (v0.4.0+):** By default, each agent runs in its own phase (N=6) so you see results after every agent instead of waiting for all 6. Each agent receives all prior findings as context — the architect's conclusions inform the security analysis, and the skeptic specifically challenges the architect's and implementer's proposals.

| Flag | Effect |
|---|---|
| `--phases N` | Override phase count (2–6, default 6) |
| `--single` | One-shot: all 6 agents at once (may timeout) |

```bash
jsat crack "redesign the payment retry system"
jsat crack --phases 4 "add idempotency to the charge endpoint"  
jsat crack --single "should we use Redis or Postgres for sessions?"
```

**Output:** A Markdown document saved to `.jsat/crack/<slug>.md` with each round's discussion and a final synthesis:

```
✅ Agreed:        Use exponential backoff with tenacity
⚠️ Disputed:      Redis vs in-process lock for idempotency
❓ Open questions: What's the SLA for retry exhaustion?
🎯 Action:        1. Extract retry logic, 2. Add idempotency key, 3. Write tests
```

**In Claude Code:** `/jsat crack redesign the payment retry system`

**In the JSAT shell:** `crack should we use async or sync for webhook processing`

**MCP tool:** `jsat__crack`

**Live progress** — while the war room runs you see real-time updates in Claude Code:
```
⚡ Loading codebase context…
⚡ Round 1/3: Opening statements…
⚡ Round 1/3: Moderator synthesising…
⚡ Round 2/3: Cross-examination…
⚡ Round 3/3: Consensus…
⚡ Writing discussion document…
[result]
```

---

## JSAT Short — Minimum-Word Answers

Get the shortest possible correct answer to any question.

```bash
jsat short "what does process_refund do"
jsat short --one-line "is PaymentService.process async"
jsat short --words 20 "explain the retry logic"
```

**In Claude Code:** `/jsat short what does process_refund do`

**In the JSAT shell:** `short is the checkout flow async`

---

## Prompt Optimizer

JSAT optimizes every query through a two-phase pipeline before sending to the AI.

### Phase 1 — Offline pipeline (always runs, zero LLM calls)

```bash
jsat prompt "improve the retry logic"              # inspect optimized prompt
jsat prompt --send "improve the retry logic"       # optimize + send
jsat prompt --diff "improve the retry logic"       # see raw vs optimized side by side
jsat prompt --send --format code --ai claude "write a test for refund()"
```

| Stage | What it does |
|---|---|
| Classify | Keyword-match task type: code_gen / refactor / debug / test / security / … |
| Context | BFS graph traversal — injects relevant function signatures and call chains |
| Constraints | KB lookup — injects project ADRs and coding standards (top-3 only) |
| Few-shot | kNN over prompt history — injects the most similar past examples |
| Format | Provider-aware: XML for Claude, Markdown for GPT, plain for Ollama |
| Compress | Token pruning when prompt exceeds 4000 tokens |

### Phase 2 — LLM rewriting (optional, activated with a flag)

After the offline pipeline structures the prompt, 1–3 specialist LLM agents rewrite the task description from different angles, then the best result is selected by a coverage + specificity scorer.

```bash
# 1 agent — fastest, rewrites for clarity and precision
jsat prompt --rewrite "fix logger in this branch"

# 3 agents in parallel — picks the best rewrite
jsat prompt --agents "fix logger in this branch"

# Combine with --send to optimize + rewrite + send in one step
jsat prompt --agents --send "fix logger in ValidateVPAHandler.post"
```

**The 3 LLM agents:**

| Agent | Temperature | Focus |
|---|---|---|
| `rewrite` | 0.2 | Replaces vague words with specific identifiers from context |
| `context_expand` | 0.3 | Fills missing technical detail (function names, error messages, paths) |
| `constraint_harden` | 0.1 | Makes success criteria measurable ("ensure X returns Y when Z") |

Agents run in parallel. Winner is chosen by: `coverage × 0.45 + specificity × 0.40 + efficiency × 0.15`.

**Discuss → Verify pipeline (v0.4.0+):** Before optimizing, the skill classifies the query type and selects the right primary tool — structural questions use `jsat__trace_call_chain`, lookup questions use `jsat__get_function`, security questions use `jsat__security_review`, etc. After executing, Phase 5 spot-checks concrete claims from the answers against the graph, marking each as ✅ verified or ⚠️ unverified before synthesis.

**Example output with `--agents --verbose`:**
```
┌─────────────────────┬──────────────────────────────┐
│ Task type           │ debug                        │
│ Context nodes       │ 3                            │
│ Tokens before       │ 6                            │
│ Tokens after        │ 847                          │
│ Rewrite agents run  │ 3                            │
│ Winner              │ context_expand               │
│ Rewrite time        │ 1843ms                       │
└─────────────────────┴──────────────────────────────┘

✦ 6→847 tokens | Task: debug | 3 agents → context_expand won
```

**In the shell** — every message is auto-optimized through Phase 1:
```
jsat [Claude Code (CLI)]> improve the retry logic

✦ Optimized refactor | 6→847 tokens (35% saved) | 3 ctx nodes | opt show to see diff

Claude: Here's the improved retry using tenacity...
```

**Shell commands:**
```
opt on        # enable auto-optimization (default)
opt off       # disable for the current session
opt show      # show raw input vs full optimized prompt side by side
opt history   # browse past optimization diffs
```

**MCP tools:**
- `jsat__prompt_optimize` — offline pipeline only
- `jsat__prompt_rewrite` — offline + 1 LLM rewrite agent
- `jsat__prompt_multi_agent` — offline + up to 3 parallel LLM agents

**Claude Code slash command:**
```
/jsat prompt-rewrite fix the logger missing extra= dict in ValidateVPAHandler.post
```

### Disconnect or remove

```bash
jsat disconnect claude --scope all            # Claude Code everywhere
jsat disconnect all                           # every connected tool at once
jsat remove                                   # remove all JSAT artifacts from this repo
```

---

## JSAT Smart — Terse Mode

Get compressed, fragment-based answers with filler stripped. Preserves code, function names, file paths, and data byte-for-byte.

Three compression levels:

| Level | Flag | Reduction | What it does |
|---|---|---|---|
| lite | `--lite` | ~30% | Strips filler phrases only ("In order to", "It's worth noting", etc.) |
| full | *(default)* | ~55% | Fragments + no explanatory preamble |
| ultra | `--ultra` | ~70% | One bullet per fact, ≤8 words each |

```bash
jsat smart "what does the payment service do?"
jsat smart --ultra "what does process_refund return?"
jsat smart --lite "explain the checkout flow"
```

Use as a fast fallback when `/jsat query` times out on large contexts.

---

## JSAT Lazy — Reuse-First Planning

Before writing new code, runs a 5-rung reuse ladder against the indexed codebase graph. Stops at the first match.

| Rung | What it checks | Tool used |
|---|---|---|
| 1 | Exact function/class already exists? | `jsat__get_function` / `jsat__get_class` |
| 2 | Similar pattern in codebase? | `jsat__query` |
| 3 | Existing service handles this domain? | `jsat__list_services` |
| 4 | Existing endpoint already exposes this? | `jsat__list_endpoints` |
| 5 | Nothing found → minimum viable code | (suggest only) |

```bash
# Check before building new retry logic
/jsat lazy add exponential backoff to the payment service

# Scan a diff for code that reimplements existing things
/jsat lazy --audit src/payments/retry.py

# Check if a proposed implementation duplicates existing code
/jsat lazy --review "def process_refund(order_id, amount)..."
```

---

## JSAT Aw — Workflow Advisor

Classifies your task type and runs the optimal JSAT tool sequence end-to-end — no more guessing which tool to use or in what order.

| Task type | Recommended workflow |
|---|---|
| feature | lazy → find-function → blast-radius → crack → test-gaps |
| bugfix | recent → incident → find-function → blast-radius |
| security | security → blast-radius `--severity breaking` → crack `--phases 3` → knowledge-add |
| understand | smart → trace → find-function → query |
| incident | incident → recent → blast-radius → runbook |
| refactor | lazy → blast-radius → test-gaps → crack → review |
| review | review → blast-radius `--severity breaking` → test-gaps `--untested` |

```bash
# Classify automatically and run the full workflow
/jsat aw add idempotency keys to the payment mutation endpoint

# Skip classification, force a specific workflow type
/jsat aw --type security src/auth/

# Show the recommended workflow without running it
/jsat aw --dry investigate the checkout 500 errors from this morning
```

---

## CLI Reference

### Core commands

| Command | Description |
|---|---|
| `jsat index [path]` | Build or update the codebase graph (incremental, parallel) |
| `jsat index . --force` | Full re-index — ignore incremental manifest |
| `jsat index . --watch` | Re-index on file change (requires `brew install entr`) |
| `jsat index . --languages python,go` | Index specific languages only |
| `jsat shell` | Start the interactive JSAT REPL |
| `jsat claude` | Open Claude Code with JSAT MCP tools loaded |
| `jsat codex` | Open Codex CLI with JSAT pre-loaded |
| `jsat cursor` | Open Cursor IDE with JSAT pre-loaded |
| `jsat windsurf` | Open Windsurf with JSAT pre-loaded |
| `jsat gemini` | Open Gemini CLI with JSAT pre-loaded |
| `jsat zed` | Open Zed editor with JSAT pre-loaded |
| `jsat gpt` | Open a GPT session with JSAT tools |
| `jsat ollama [--model llama3.2]` | Open a local Ollama session |
| `jsat crack <task>` | Multi-agent war room discussion (6 AI specialists) |
| `jsat crack --roles architect,security <task>` | War room with specific roles only |
| `jsat crack --rounds 2 --file out.md <task>` | 2 rounds, save output to file |
| `jsat short <question>` | Get the shortest possible correct answer |
| `jsat short --one-line <question>` | Exactly one-sentence answer |
| `jsat prompt <query>` | Print the optimized prompt (inspect without sending) |
| `jsat prompt --send <query>` | Optimize prompt and send to the configured AI |
| `jsat prompt --rewrite <query>` | Run 1 LLM rewrite agent after offline pipeline |
| `jsat prompt --agents <query>` | Run 3 parallel LLM rewrite agents, pick best |
| `jsat prompt --diff <query>` | Show raw input vs optimized prompt side by side |
| `jsat doctor` | System health check (graph, AI, services, connected tools) |
| `jsat doctor --json` | Health check as raw JSON |
| `jsat version` | Print JSAT version |

### Configuration

| Command | Description |
|---|---|
| `jsat init` | Generate `.jsat/config.yaml` for this repo (default: `solo` profile) |
| `jsat init --global` | Generate `~/.jsat/config.yaml` — applies to all projects |
| `jsat init --profile team` | Team profile (Neo4j, Qdrant, Redis, Claude API) |
| `jsat init --profile ci` | CI profile (SQLite, no AI, JSON logs) |
| `jsat init --profile raspberry-pi` | Low-RAM profile (SQLite, phi3:mini, batch size 8) |

### AI provider management

| Command | Description |
|---|---|
| `jsat ai status` | Show all providers: available, active, free/paid |
| `jsat ai use <provider>` | Configure a provider and write to `.jsat/config.yaml` |
| `jsat ai use <provider> --global` | Configure provider globally in `~/.jsat/config.yaml` |
| `jsat ai use ollama --model phi3:mini` | Use a specific Ollama model |
| `jsat ai test` | Send a test prompt and verify the provider works |
| `jsat ai models` | List models available from the configured provider |

### Claude Code integration

| Command | Description |
|---|---|
| `jsat connect claude` | Wire JSAT into Claude Code (project scope) + install 31 slash commands |
| `jsat connect claude --global` | Wire JSAT into Claude Code globally (all projects) |
| `jsat connect claude --no-skills` | MCP only — skip slash command installation |
| `jsat connect codex` | Wire JSAT into OpenAI Codex CLI (project scope) |
| `jsat connect codex --global` | Wire JSAT into Codex globally |
| `jsat connect bob` | Wire JSAT into Bob Shell (project scope) |
| `jsat connect bob --global` | Wire JSAT into Bob Shell globally |
| `jsat connect cursor` | Wire JSAT into Cursor |
| `jsat connect windsurf` | Wire JSAT into Windsurf |
| `jsat connect continue` | Wire JSAT into Continue.dev |
| `jsat connect zed` | Wire JSAT into Zed editor |
| `jsat connect gemini` | Wire JSAT into Google Gemini CLI |
| `jsat connect list` | Show all active JSAT MCP connections |
| `jsat disconnect <tool>` | Remove JSAT from a specific tool |
| `jsat disconnect all` | Remove JSAT from every tool at once |

### Token analysis

| Command | Description |
|---|---|
| `jsat tokens "text"` | Count tokens in inline text |
| `jsat tokens --file README.md` | Count tokens in a file |
| `jsat tokens --file ctx.py --model gpt-4o` | Show budget bar vs model limit |
| `jsat tokens --file ctx.py --compress` | Compress and show savings |
| `jsat tokens --target 4000 --compress` | Compress to explicit token ceiling |
| `cat file.py \| jsat tokens --model claude-cli` | Pipe stdin |

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
| `jsat ci-setup` | Write a GitHub Actions workflow for JSAT |
| `jsat ci-setup --provider gitlab` | Write a GitLab CI pipeline for JSAT |

---

## Python SDK

```python
from jsat import JSAT

# Instantiate — auto-detects AI provider, loads config
js = JSAT(repo=".")

# Build the graph — parallel parsing, incremental by default
result = js.index()
print(f"Indexed {result.nodes_indexed} nodes in {result.duration_ms}ms")
print(f"Workers: {result.parallel_workers} | Incremental: {result.incremental}")
print(f"Skipped: {result.files_skipped} unchanged | Resolved: {result.resolved_edges} edges")
if result.complexity_hotspots:
    print("Hotspots:", [(h["name"], h["complexity"]) for h in result.complexity_hotspots])

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

# Token analysis (offline, no LLM)
count = js.token_count("explain the payment service")
report = js.token_compress(large_prompt, model="gpt-4o")
print(f"Saved {report.savings_pct:.1f}% via: {report.strategies_applied}")
budget = js.token_budget(my_context, "claude-cli")
print(f"{budget['budget_pct']:.2f}% of context used ({budget['status']})")

# Switch AI provider mid-session
js.switch_ai("ollama", model="qwen2.5-coder:7b")
js.switch_ai("anthropic")
js.switch_ai("gpt", model="gpt-4o-mini")

# Health check
health = js.doctor()
print(health["profile"], health["graph"]["backend"])
```

---

## Tools Overview (20 tools)

| # | Tool | Description |
|---|---|---|
| 0 | **JSAT Shell** | Interactive REPL — run any tool directly, switch AI mid-session, no AI required |
| 1 | **Directory Indexer** | Parallel tree-sitter parsing (4–8× faster), true incremental mode, rich metadata (parameters, return types, decorators, docstrings, complexity), symbol resolution, inheritance/raises edges |
| 2 | **Test Intelligence Helper** | Finds test gaps, maps behaviors to coverage, generates unit/integration/contract tests |
| 3 | **Feature Helper** | Answers "how do I add X?" using graph context — finds relevant files and patterns |
| 4 | **Blast Radius Analyzer** | BFS over the graph to trace downstream impact; classifies edges as breaking/degraded/warning/safe |
| 5 | **API Contract Validator** | Diffs OpenAPI/AsyncAPI specs, classifies breaking changes, scores backward compatibility (0–100) |
| 6 | **Security Review Agent** | OWASP pattern scan, auth coverage gaps, hardcoded secret detection, dependency CVE lookup |
| 7 | **Incident Investigation Helper** | Correlates an incident description against recent commits and graph topology; ranks root-cause hypotheses |
| 8 | **Migration Safety Validator** | Validates migration files, estimates lock duration, generates zero-downtime migration plans |
| 9 | **Multi-Model Code Review (true parallel dispatch)** | Dispatches a diff to multiple AI models simultaneously via `ThreadPoolExecutor`; surfaces only bugs confirmed by two or more models |
| 10 | **Knowledge Base Builder** | Persistent searchable store of architectural decisions, runbooks, and tribal knowledge |
| 11 | **Multi-Agent Orchestrator** | Decomposes a task and runs specialized sub-agents (understanding, generation, review, test, security, docs) |
| 12 | **Export / Import System** | Portable zip snapshots of the full graph — share between machines, cache in CI, restore in seconds |
| 13 | **Python SDK** | Programmatic access to every tool via `from jsat import JSAT` |
| 14 | **IThinking Meta-Cognitive Layer** | Structured seven-phase reasoning: clarify, plan, context, assumptions, execute, reflect — with human approval gates |
| 15 | **Token Optimizer** | Offline token analysis and multi-strategy compression (whitespace, stopphrase, dedup, import collapse, recency pin) |
| 16 | **JSAT Crack** | Multi-agent war room — 6 specialists discuss complex decisions in rounds, responding to each other; moderator synthesises consensus |
| 17 | **JSAT Short** | Minimum-word answers — prepends brevity constraint so AI responds in ≤3 sentences or less |
| 18 | **JSAT Smart** | Terse compression mode — fragment-based answers with filler stripped, code preserved |
| 19 | **JSAT Lazy** | Reuse-first planning — 5-rung ladder against the graph before suggesting new code |
| 20 | **JSAT Aw** | Workflow advisor — classifies task type, runs optimal JSAT tool sequence end-to-end |

### Multi-Model Review

Tool 9 dispatches the diff to all configured models in parallel, collects findings, and surfaces only those confirmed by two or more models. Configure the model list and timeout in `.jsat/config.yaml`:

```yaml
review:
  models:
    - {provider: claude_cli, model: claude-sonnet-4-6}
    - {provider: ollama, model: qwen2.5-coder:7b}
  parallel_timeout_seconds: 90
  min_confidence: medium
```

- `parallel_timeout_seconds` — per-review wall-clock deadline; any model that exceeds this is skipped and its absence is logged.
- `min_confidence` — minimum agreement level to surface a finding: `low` (any model), `medium` (2+ models), `high` (all models).

---

## Graph Schema

JSAT indexes these node types and relationship edges:

**Nodes:** `Function`, `Class`, `File`, `Service`, `Endpoint`, `Table`, `Topic`, `KnowledgeEntry`

**Node properties (v0.2.0+):**

| Property | On | Example |
|---|---|---|
| `name`, `file`, `language`, `line_start`, `line_end`, `line` | Function, Class | `"PaymentService.refund"` |
| `parameters` | Function | `[{"name":"order_id","type":"str"}]` |
| `return_type` | Function | `"bool"`, `"list[Payment]"` |
| `decorators` | Function, Class | `["staticmethod","login_required"]` |
| `docstring` | Function, Class | first line, max 200 chars |
| `complexity` | Function | cyclomatic (1 + branch count) |
| `loc` | Function | `line_end - line_start + 1` |
| `bases` | Class | `["BaseModel","Serializable"]` |
| `method_count` | Class | number of methods in class body |

**Edges:**

| Edge | Meaning |
|---|---|
| `CALLS` | Function A calls function B (resolved to node ID post-parse) |
| `IMPORTS` | File A imports module B |
| `INHERITS` | Class inherits from parent (all 6 languages) |
| `IMPLEMENTS` | Class implements interface/trait (Java, Go, Rust) |
| `RAISES` | Function can raise exception type (Python) |
| `READS_FROM` | Code reads from a table or topic |
| `WRITES_TO` | Code writes to a table or topic |
| `PRODUCES` | Service produces a Kafka message |
| `CONSUMES` | Service consumes a Kafka topic |
| `DEPENDS_ON` | Service depends on another service |

---

## Configuration

### Data storage

By default JSAT stores runtime state (graph, cache, vectors, prompt history) in **`~/.jsat/<hash12>/`** — a global per-repo directory that never appears inside your git working tree. No `.gitignore` entry needed.

| Priority | Location | When |
|---|---|---|
| 1 | `$JSAT_DATA_DIR` | env var set (CI, Docker) |
| 2 | `{repo}/.jsat/` | already exists (backward compat) |
| 3 | `~/.jsat/<sha1_12>/` | **default** |

The config file (`.jsat/config.yaml`) is separate and optional — it holds project-specific settings, not runtime data.

### One-time global setup

```bash
jsat init --global --profile solo      # write ~/.jsat/config.yaml
jsat ai use claude_cli --global        # set AI provider globally
jsat connect claude --global           # install to ~/.claude/ for all projects
```

After this, every project on the machine has JSAT available with no per-repo steps.

### Per-repo config

```bash
jsat init                        # write .jsat/config.yaml (solo profile)
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

JSAT finds its config file by checking these locations in order (first found wins):

1. Explicit path passed to `JSAT(config=...)` or `--config` flag
2. `$JSAT_CONFIG` environment variable
3. `{repo}/.jsat/config.yaml` (repo-local canonical)
4. `{repo}/.jsat.yaml` (legacy)
5. `./.jsat/config.yaml` (CWD)
6. `~/.jsat/config.yaml` ← **global user config** (`jsat init --global`)
7. `~/.config/jsat/config.yaml`
8. `/etc/jsat/config.yaml`

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
