# JSAT — JaySoft AI Tools

<!-- Logo placeholder -->
<!-- ![JSAT Logo](docs/logo.png) -->

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/jsat.svg)](https://pypi.org/project/jsat/)

**Codebase intelligence for AI sessions — index once, query forever, works with any AI.**

---

## 🧠 What is JSAT?

Every AI session starts with the same problem: you spend the first ten minutes re-explaining your architecture, re-pasting function signatures, and re-describing how services talk to each other. JSAT solves this by building a persistent graph of your codebase once — functions, classes, files, services, API endpoints, database tables, Kafka topics, and every relationship between them — and making that context instantly available to any AI you use.

JSAT works as a CLI, a Python SDK, and an MCP server that plugs into Claude Code, Codex, Cursor, Bob Shell, Gemini CLI, and other MCP-capable tools. If a supported local CLI is installed, JSAT can use it as the AI provider with no API key required. For hosted APIs and local servers — Anthropic API, OpenAI, Gemini, Ollama, LM Studio — one command switches the provider.

Long-running tools stream **live progress notifications** to Claude Code — and with `dashboard=true` on any command, a real-time browser dashboard opens automatically: a live waterfall timeline, full request/response panes, per-tool aggregate stats, and session history that you can replay or diff against any earlier run.

---

## 🌟 Key Features

| Feature | What it does |
|---------|-------------|
| **Persistent graph** | Index once, query forever — functions, classes, services, endpoints, Kafka topics, DB tables |
| **51 slash commands** | `/jsat magic`, `/jsat crack`, `/jsat improve`, `/jsat security` and 47 more |
| **Universal flags** | `timeout=<N>` sets a soft budget on any call; `dashboard=true` opens a live browser dashboard |
| **Smart budgets** | Over-budget → AI gets notified (call keeps running). Force-kill only at 5× the budget |
| **Session files** | All major skills write resumable session files — `--continue` picks up where it left off |
| **Zero-dep dashboard** | Stdlib-only SSE server — live waterfall timeline, request/response panes, aggregate stats, replayable session history in a dark-terminal browser view |
| **Multi-provider** | Claude Code CLI, OpenCode CLI, Bob Shell CLI, Codex CLI, Anthropic API, OpenAI, Gemini, DeepSeek, Ollama, LM Studio — one command switches |
| **SDK + CLI + MCP** | Use as a shell, Python SDK, or MCP server — same graph, same tools |

---

## ⚡ Quick Start

```bash
pip install jsat

# Index your project
cd your-project/
jsat index .

# Open your AI tool with JSAT pre-loaded (auto-connects on first use)
jsat claude      # Claude Code
jsat codex       # OpenAI Codex CLI
jsat codex resume <session-id>
jsat opencode    # OpenCode (project scope)
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

**Codex skill commands:**
```
$jsat magic add retry logic to the payment service
$jsat query what does the payment service do?
@jsat magic investigate the checkout flow
```

`$jsat` is the preferred Codex skill invocation. JSAT's Codex dispatcher also
treats `@jsat` as the same request when Codex routes it to the skill.

**All tools** have all JSAT MCP tools the AI can call automatically.

---

## 📦 Installation

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

## 🤖 AI Providers

JSAT auto-detects available providers at startup and picks the best one in priority order:

1. **Claude Code CLI** — detected via `which claude`; no API key, no extra SDK
2. **Bob Shell CLI** — detected via `which bob`; no API key, IBM AI assistant with multiple modes
3. **OpenAI Codex CLI** — detected via `which codex`; no API key after Codex sign-in
4. **Anthropic API** — if `ANTHROPIC_API_KEY` is set and `jsat[anthropic]` is installed
5. **OpenAI** — if `OPENAI_API_KEY` is set and `jsat[openai]` is installed
6. **Ollama** — if `ollama serve` is running at `localhost:11434` *and at least one model is pulled* (a running daemon with zero models cannot complete a request — check `ollama list` first)
7. **LM Studio** — if an OpenAI-compatible server is running at `localhost:1234`
8. **No AI** — tools that don't need AI (indexing, blast radius, export) still work

### Check what's available

```bash
jsat ai status        # shows all providers, which is active, and switch commands
```

### Switch providers

```bash
jsat ai models ollama                     # discover registered local/cloud models
jsat ai use ollama --model qwen2.5:0.5b    # exact tag; see `ollama list`
jsat ai use anthropic --model <model>     # needs ANTHROPIC_API_KEY
jsat ai use openai --model gpt-4o-mini    # needs OPENAI_API_KEY
jsat ai use claude_cli                    # Claude chooses its configured/default model
jsat ai use opencode                      # OpenCode CLI (uses its selected provider/model)
jsat ai use codex-cli                     # Codex chooses its configured/default model
jsat ai use deepseek --model deepseek-chat  # needs DEEPSEEK_API_KEY
jsat ai use lmstudio --model <model>      # OpenAI-compat server at localhost:1234
jsat ai test                              # verify the configured provider works

# Apply globally (all projects on this machine):
jsat ai use claude_cli --global
```

### Switch inside the JSAT shell

```
switch claude    → Claude Code CLI (no key) or Claude API
switch bob       → Bob Shell (no key)
switch codex     → OpenAI Codex CLI
switch gpt <model>       → OpenAI API with an explicit model
switch ollama <model>    → Ollama with a registered local/cloud model
switch haiku <model>     → Anthropic API; alias never pins a model version
switch phi <model>       → Ollama; choose an installed Phi-family model
switch lmstudio <model>  → LM Studio with its loaded model ID
switch deepseek <model>  → DeepSeek API (needs DEEPSEEK_API_KEY)
```

---

## 🔌 AI Tool Integration

JSAT works as an MCP server with any AI tool that supports the Model Context Protocol. One command wires it in — the tool picks up all JSAT MCP tools automatically.

### Choose your execution path

The coding client and the model provider are separate choices. Use the guide for the process
you actually want to run; this prevents native Codex/Claude from being confused with a client
that Ollama launched.

| Setup | Who owns the model? | Start command | Complete guide |
|---|---|---|---|
| Native Codex | Codex account/config | `jsat start codex --via native` | [Codex](docs/integrations/codex.md) |
| Native Claude | Claude account/model selector | `jsat start claude --via native` | [Claude](docs/integrations/claude.md) |
| Native OpenCode | OpenCode provider/config | `jsat start opencode --via native` | [OpenCode](docs/integrations/opencode.md) |
| Direct Ollama | JSAT's configured Ollama model | `jsat ollama --model MODEL` | [Ollama local](docs/integrations/ollama-local.md) |
| Claude through Ollama | Ollama selector or `--model` | `jsat start claude --via ollama` | [Ollama + Claude](docs/integrations/ollama-claude.md) |
| OpenCode through Ollama | Ollama selector or `--model` | `jsat start opencode --via ollama` | [Ollama + OpenCode](docs/integrations/ollama-opencode.md) |
| Codex through Ollama | Ollama selector or `--model` | `jsat start codex --via ollama` | [Ollama + Codex](docs/integrations/ollama-codex.md) |

Local Ollama models require one `ollama pull MODEL`. Ollama Cloud models require
`ollama signin` and no pull. A model selected by `ollama launch` applies to that launched
client; it does not silently become the provider in `.jsat/config.yaml`.

[Open the tabbed integration chooser](docs/integrations/index.md).

### ⏱ Universal Flags

Two flags work on **every** `/jsat` command — strip them from ARGS before routing, pass as tool args:

```bash
# Set a custom soft time budget (notification-only; hard kill at 5×N)
/jsat blast-radius timeout=60 src/payment/
  → jsat__blast_radius(target='src/payment/', _budget=60)

# Open a live browser dashboard for this call
/jsat crack dashboard=true redesign the auth flow
  → jsat__crack(task='redesign the auth flow', _dashboard=True)

# Combine both
/jsat magic timeout=180 dashboard=true --service payments investigate the auth flow
```

| Flag | Soft budget behavior | Hard kill |
|------|----------------------|-----------|
| `timeout=<N>` | After N s: ⏱ AI notified with last steps, call keeps running | At 5×N s |
| *(default)* | Per-tool budget (blast_radius: 30s, crack: 55s, query: 45s) | At 5× budget |

### ✏️ Universal Input Correction & Learning Module

Every `/jsat <command>` invocation runs two extra passes by default, before and after the
subcommand itself:

**Before routing** — free-form ARGS are cleaned up (typos, run-on phrasing, ambiguous
pronouns tightened) via `jsat__prompt_rewrite` before being handed to the subcommand.
Literal payloads are never touched: file paths, diffs/patches, code blocks, git refs/SHAs,
and URLs are passed through verbatim even when they sit next to prose that gets corrected.
If the rewrite meaningfully changes ARGS, the AI reports what changed with a one-line
`📝 Interpreted as: <rewritten>` before proceeding, so a bad guess is visible and
correctable rather than silently substituted. Add `raw=true` to any command to skip this
step entirely and route ARGS exactly as typed (e.g. `/jsat query raw=true find PaymnetService`).

**After completion** — a short pass checks whether the command surfaced anything worth
remembering beyond this conversation. Most invocations produce nothing durable and this
runs silently with no output. When something concrete is learned, it's classified and
saved via `jsat__knowledge_add`:
- **Project-specific** facts (a gotcha, a non-obvious dependency, a false-positive pattern
  to exclude next time) are saved to this project's knowledge base (`category="project-learning"`) — searchable later with `/jsat knowledge`.
- **JSAT-specific** facts (a tool misbehaving, a missing capability, a stale parameter)
  are saved to JSAT's own improvement backlog (`category="jsat-improvement"`), which
  `/jsat improve` reads from later — this is feedback about JSAT itself, not the user's repo.

### 📊 Live Dashboard

Add `dashboard=true` to any `/jsat` command and a real-time browser dashboard opens automatically. Each `/jsat` command gets **one persistent tab** — all tool calls in that session stream into the same collapsible tree, not separate tabs.

```bash
/jsat magic dashboard=true investigate the checkout flow
/jsat crack dashboard=true redesign the payment retry system
/jsat blast-radius dashboard=true timeout=60 src/payment/
```

**URL**: `http://localhost:7432/jsat/dashboard/<command>` — e.g., `/jsat crack ...` opens `localhost:7432/jsat/dashboard/crack`.

**What the tree shows:**
- Session header with live elapsed timer and status badge (● RUNNING → ✓ DONE)
- Each tool call as a collapsible section with its name and elapsed time
- Sub-calls nested under their parent (e.g., crack phases under a parent crack call)
- Every checkpoint, result, and event streamed in real-time, color-coded by type:
  - 🟡 Amber — checkpoints (substep progress)
  - 🟢 Green — results (completed)
  - 🔵 Blue — agent full responses (crack war room agents)
  - 🔴 Red — errors
  - 🟠 Orange — over-budget warnings
- **Copy logs** button to capture the full session

**Session lifecycle:**
- Tab opens on the first tool call; subsequent calls in the same `/jsat` session stream into the same tab.
- Tab stays open until the entire `/jsat` command finishes. An idle watcher fires `session_done` automatically after 30 s with no active calls.
- After session done the tree dims (✓ DONE) — the tab stays open indefinitely for reading.

For multi-tool sessions (magic, crack, sprint) the skill files automatically pass `_dashboard_session=<command>` in every tool call so all calls share one tab — no manual action needed.

The dashboard runs on `localhost:7432` (override with `JSAT_DASHBOARD_PORT`), served by a pure stdlib SSE server — no extra dependencies.

### 🎨 JSAT Studio

A browser/TUI face for all of JSAT. `jsat ui` starts a zero-dependency browser app
(**port 7433**, pure stdlib HTTP server) with a prompt bar, a command palette
(Ctrl+P), and 17 screens covering every tool family — Overview, Ask, Graph, Blast,
Security, Test Gaps, API Diff, Consumers, Data Flow, Incident, Review, Knowledge,
Improve, Prompt Lab, Tools, Sessions, Plans. Type an intent in natural language
(e.g. *"what breaks if I change token_compress?"*) and the offline intent router maps
it to the right tool; every screen is also reachable from the palette.

```bash
jsat ui                                # start the web app, open the browser
jsat ui --no-open                      # print the URL, don't open a browser
jsat ui --tui                          # terminal UI instead (needs the `studio` extra)
pip install 'jsat[studio]'             # optional: Textual for the TUI
```

The TUI degrades gracefully: without Textual it prints the install hint and exits 2.
The HTTP API (`/api/status`, `/api/index`, `/api/nodes`, `/api/tools/<name>`,
`/api/prompt`) is the same surface the app uses, so `curl` against `localhost:7433`
works for scripting too.

### Connect

```bash
# Recommended: one-time global setup (works in every project)
jsat connect claude --global               # Claude Code — all sessions
jsat connect codex                        # OpenAI Codex CLI — global MCP + $jsat skill
jsat connect opencode                     # OpenCode — MCP + /jsat commands (project scope)
jsat connect opencode --global            # OpenCode — all projects (recommended one-time)
jsat connect ollama                       # Claude + Codex + OpenCode Ollama integrations
jsat connect ollama tool=opencode         # only OpenCode (also accepts --tool opencode)
jsat connect ollama opencode --model <model>  # + remember this model for `jsat ollama opencode`
jsat connect bob --global                 # Bob Shell — all sessions

# If Ollama manages OpenCode, connect once and use Ollama's normal menu:
ollama                                    # OpenCode → sign in → choose model

# Managed lifecycle (defaults to all: Claude + Codex + OpenCode)
jsat start                                # one terminal per interactive client
jsat ps                                   # show JSAT-managed clients
jsat restart                              # restart all three clients
jsat stop                                 # stop all running managed clients
jsat resume                               # resume all three clients
jsat restart opencode                     # target one client

# Per-project (this repo only)
jsat connect claude                        # Claude Code
jsat connect bob                           # Bob Shell (+ /jsat-* slash commands)
jsat connect cursor                        # Cursor
jsat connect windsurf                      # Windsurf (Codeium)
jsat connect continue                      # Continue.dev
jsat connect zed                           # Zed editor
jsat connect gemini                        # Google Gemini CLI

jsat connect github                        # GitHub MCP server, beside JSAT
jsat connect list                          # show every active connection
```

Restart the AI tool after connecting. JSAT's MCP tools are immediately available.

**Claude reaches for JSAT on its own.** `jsat connect claude` also writes a marked block
into `CLAUDE.md`, which Claude Code loads every session. Slash commands only fire when you
type one; the `CLAUDE.md` block is what makes Claude *proactively* run `jsat__blast_radius`
before an edit, `jsat__get_test_gaps` before writing tests, and say in one line what each
tool actually found. Skip it with `--no-claude-md`; `jsat disconnect claude` removes the
block and leaves the rest of your `CLAUDE.md` untouched.

### Files written per tool

Most connect commands write both an MCP config **and** a guidance file so the AI knows what JSAT tools exist and when to use them — without being asked. Codex stays global-only: JSAT writes one global MCP entry plus one global Codex skill dispatcher, without generating project files.

| Tool | MCP config | Guidance file | Guidance format |
|---|---|---|---|
| Claude Code (project) | `.claude/settings.json` | `.claude/commands/jsat-*.md` (51 files) + `CLAUDE.md` | Slash commands + always-on guidance |
| Claude Code (global) | `~/.claude/settings.json` | `~/.claude/commands/jsat-*.md` + `~/CLAUDE.md` | Slash commands + always-on guidance |
| Codex | `~/.codex/config.toml` | `~/.codex/skills/jsat/SKILL.md` | `$jsat` dispatcher + MCP tools; no project files |
| Bob Shell (project) | `.bob/settings.json` | `BOB.md` + `.bob/commands/jsat-*.md` | Slash commands |
| Bob Shell (global) | `~/.bob/settings.json` | `BOB.md` + `~/.bob/commands/jsat-*.md` | Slash commands |
| Cursor | `~/.cursor/mcp.json` | — | — |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `.windsurfrules` | Rules file |
| Continue | `~/.continue/config.json` | `/jsat-*` custom commands | Slash commands |
| Zed | `~/.config/zed/settings.json` | `.zed/JSAT.md` | Project context |
| Gemini CLI | `~/.gemini/settings.json` | `GEMINI.md` | Project instructions |

Pass `--global` (claude/bob) or check the tool's docs for global scope on others.

Pass `--no-instructions` to skip writing guidance files on integrations that support them.

### `/jsat` dispatcher

`jsat connect claude` installs a single `/jsat` command rather than 51 individual `/jsat-*` commands. All skills are accessible as subcommands:

```bash
/jsat help               # list all 50 subcommands
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

### Claude Code — slash commands (50 subcommands + `/jsat-help`)

`jsat connect claude` installs two slash commands:
- `/jsat <subcommand>` — 50 subcommands organized by category (see table below)
- `/jsat-help [command]` — no args lists all commands; `/jsat-help magic` shows full flags and examples for that command

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
| `/jsat improve` | Diagnose problems JSAT hit in itself and draft a patch for JSAT |

**Impact & safety**
| Command | What it does |
|---|---|
| `/jsat blast-radius <file or symbol>` | Downstream impact grouped by severity |
| `/jsat security [path]` | OWASP scan — Critical and High first |
| `/jsat migration <file>` | DB migration safety — lock type, duration estimate |
| `/jsat contract <diff>` | API contract compatibility check |
| `/jsat service-health-check <service>` | Validate one service's readiness — CLAUDE.md completeness, catalog registration, auth coverage, test gaps, index freshness |
| `/jsat upgrade-impact <dependency>` | Blast radius of bumping a dependency — importers, criticality, known CVEs |

**Code quality**
| Command | What it does |
|---|---|
| `/jsat review <diff>` | Multi-model parallel code review |
| `/jsat test-gaps [path]` | Find untested paths, generate tests |
| `/jsat coverage [path]` | Behavioral coverage estimate |
| `/jsat dead-code [path]` | Find functions/classes with no callers (blast-radius inversion) |
| `/jsat verify <change>` | Prove a change works end-to-end, prioritized by graph impact |

**Git workflow**
| Command | What it does |
|---|---|
| `/jsat changelog <ref1>..<ref2>` | Changelog between two refs, grouped by service and impact |
| `/jsat cherry-pick <commit>` | Cherry-pick a commit with graph-aware impact analysis and semantic conflict resolution |
| `/jsat merge <branch>` | Merge a branch with graph-aware impact analysis, semantic conflict resolution, post-merge verification |
| `/jsat rebase <target>` | Rebase onto a target using the same graph-aware conflict resolution engine as `/jsat merge` |
| `/jsat pr-describe` | Compose a PR description from review findings, contract diff, and test coverage |

**Knowledge & investigation**
| Command | What it does |
|---|---|
| `/jsat knowledge <query>` | Search the knowledge base |
| `/jsat knowledge-add <text>` | Add an ADR / runbook / decision |
| `/jsat runbook <target>` | Generate an incident runbook |
| `/jsat incident <description>` | Root-cause hypotheses ranked by confidence |
| `/jsat recent [path]` | Recent changes in an area |
| `/jsat internet <question>` | Query the live internet for up-to-date facts (docs, versions, CVEs, best practices), optionally grounded in this codebase — a skill, not a `jsat__*` MCP tool or bare CLI command; the one sanctioned way to reach outside the graph |

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

**Help**
| Command | What it does |
|---|---|
| `/jsat-help` | List all 50 commands with one-liner descriptions |
| `/jsat-help <command>` | Full description, flags, and examples for a specific command (e.g. `/jsat-help magic`) |

### Open Claude with JSAT context pre-loaded

```bash
jsat claude
```

---

## ⚔️ JSAT Crack — Multi-Agent War Room

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

## 💬 JSAT Short — Minimum-Word Answers

Get the shortest possible correct answer to any question.

```bash
jsat short "what does process_refund do"
jsat short --one-line "is PaymentService.process async"
jsat short --words 20 "explain the retry logic"
```

**In Claude Code:** `/jsat short what does process_refund do`

**In the JSAT shell:** `short is the checkout flow async`

---

## 🔧 Prompt Optimizer

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

## 🧩 JSAT Smart — Terse Mode

Get compressed, fragment-based answers with filler stripped. Preserves code, function names, file paths, and data byte-for-byte.

Three compression levels:

| Level | Flag | Reduction | What it does |
|---|---|---|---|
| lite | `--lite` | ~30% | Strips filler phrases only ("In order to", "It's worth noting", etc.) |
| full | *(default)* | ~55% | Fragments + no explanatory preamble |
| ultra | `--ultra` | ~70% | One bullet per fact, ≤8 words each |

```
/jsat smart what does the payment service do?
/jsat smart --ultra what does process_refund return?
/jsat smart --lite explain the checkout flow
```

Use as a fast fallback when `/jsat query` times out on large contexts.

---

## ♻️ JSAT Lazy — Reuse-First Planning

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

## 🗺️ JSAT Aw — Workflow Advisor

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

## ✨ JSAT Magic — AI-Orchestrated Skill Composer

The only JSAT skill with no fixed template. Given any task, it:

1. **Analyzes** the task to understand what information is needed
2. **Composes** a minimal effective skill sequence from all 40 skills, organized in layers
3. **Executes** each skill with task-specific parameters, adapting based on findings
4. **Converges** when the task is answerable — skips remaining skills once sufficient data exists

| Layer | Skills | Purpose |
|---|---|---|
| 0 — Context | status, list-services | Always run |
| 1 — Discover | find-function, trace, query, recent… | Locate relevant code |
| 2 — Analyze | blast-radius, security, test-gaps, cohesion… | Assess risk and quality |
| 3 — Plan | lazy, plan, think, crack, decide… | Design the solution |
| 4 — Execute | review, prompt, sprint | Guide implementation |
| 5 — Verify | test-gaps --generate, blast-radius --severity breaking | Validate before shipping |
| 6 — Record | decide log, reflect, knowledge-add | Preserve decisions |

```bash
/jsat magic add retry logic to the payment service
/jsat magic --depth deep redesign the authentication flow
/jsat magic --preview investigate the checkout 500 errors   # plan only, no execution
/jsat magic --service PaymentService what are the test gaps?
```

Depth flags: `--depth quick` (4 skills), `--depth standard` (8, default), `--depth deep` (15).
`--preview` shows the composed plan without running anything.

---

## 📋 JSAT Plan — Pre-Implementation Planning Gate

Runs before writing any code. Surfaces assumptions, scope risks, and architectural concerns
by answering six forcing questions, then reviewing from three perspectives.

**Six Forcing Questions:**
1. What is the exact problem?
2. Who experiences it and how often?
3. What is the cost of NOT solving it?
4. What already exists in the codebase that partially handles this?
5. What is the minimum change that solves it?
6. What is the hardest part — and what assumption am I making about it?

Three review perspectives: **Scope** (what to build and why), **Architecture** (how to build it),
**Security** (what can go wrong).

Output: a one-page planning brief with recommended decision, architecture approach, top risk, and first concrete step.

```bash
/jsat plan add idempotency keys to the payment mutation
/jsat plan --scope refactor the retry logic         # scope review only
/jsat plan --security add a new admin endpoint      # security review only
```

---

## 📓 JSAT Decide — Architectural Decision Journal

Log architectural decisions into the knowledge base and retrieve them by file, topic,
or blast-radius context — so past decisions inform future changes.

```bash
/jsat decide log --impact h Chose PostgreSQL over MongoDB for ACID compliance on payment records
/jsat decide log Switched caching from Redis to in-memory — cost $500/month, latency acceptable
/jsat decide context src/payments/service.py     # decisions relevant to this file
/jsat decide search caching strategy
/jsat decide list adr                            # list all ADR-category decisions
```

Subcommands: `log [--impact h|m|l]`, `list [<category>]`, `search <query>`, `context <file_or_symbol>`

---

## 🚀 JSAT Sprint — Seven-Stage Delivery Workflow

Structured end-to-end delivery. Each stage runs focused JSAT tools and passes its
findings forward to the next.

| Stage | Tool | Purpose |
|---|---|---|
| 1. Think | ithinking plan | Clarify intent and surface assumptions |
| 2. Plan | ithinking audit + query | Surface risks before coding |
| 3. Build | find-function + blast-radius | Locate code and map impact scope |
| 4. Review | review findings | Multi-model code review of affected areas |
| 5. Test | test-gaps | Find coverage gaps |
| 6. Ship | blast-radius --severity breaking | Breaking impact check before release |
| 7. Reflect | ithinking reflect | Log outcomes and decisions |

```bash
/jsat sprint "add rate limiting to the checkout API"
/jsat sprint --stage 4 "add rate limiting"    # resume from Review
/jsat sprint --dry "redesign auth flow"       # show plan without running
```

---

## 🏥 JSAT Cohesion — Code Health Analysis

Flags files and functions that have grown beyond healthy boundaries, then cross-references
with blast-radius to prioritize the most urgent refactoring targets.

- Files > 800 lines (adjustable with `--threshold N`)
- Functions with cyclomatic complexity > 10
- Classes with > 15 methods

Output: RED / YELLOW / GREEN priority report with specific extraction suggestions.

```bash
/jsat cohesion src/
/jsat cohesion --threshold 600 --service PaymentService
/jsat cohesion --functions jsat/cli.py    # function-level analysis only
```

---

## 🐙 GitHub MCP — turn errors into resolved issues

JSAT knows what broke *in your codebase*. GitHub knows whether anyone has hit it
before. `jsat connect github` wires GitHub's MCP server in beside JSAT so an AI has
both.

```bash
jsat connect github                  # Docker image, Claude Code, this repo
jsat connect github cursor --global  # Cursor, all projects
jsat connect github --remote         # GitHub's hosted endpoint (no Docker)

export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...   # `repo` scope; `read:org` to search orgs
```

**Your token never touches disk.** Only the environment variable *name* is written
into the config (`${GITHUB_PERSONAL_ACCESS_TOKEN}`); the MCP client expands it at run
time.

With both connected, the guidance JSAT writes tells the AI to work in this order:

| Step | Tool |
|---|---|
| 1. Locate the failure in your code | `jsat__query`, `jsat__get_function`, `jsat__blast_radius` |
| 2. Check whether it is already known | GitHub MCP issue/PR search |
| 3. Find what changed | `jsat__get_recent_changes` + the PR via GitHub MCP |
| 4. Report only if genuinely new | `jsat improve` bundle → issue body |

Raw tracebacks are never pasted into GitHub — a `jsat improve` bundle is
privacy-filtered, a traceback is not. Reading is unprompted; **creating an issue,
comment, or PR asks you first.**

---

## 📝 Notes & Knowledge

Capture something worth remembering without leaving the terminal. Notes are stored as
knowledge entries (`category: note`), so they are searchable alongside your ADRs and
runbooks — and visible to every connected AI tool through the MCP knowledge tools.

```bash
jsat note add "retry logic uses tenacity per ADR-007"
jsat note add -c adr "all payment mutations require idempotency keys"
jsat note list                    # notes only
jsat note list -c all             # every knowledge entry
jsat note search retry            # semantic search across notes + ADRs + runbooks
```

There is no second store to keep in sync: `jsat note` is a thin CLI over the same
`KnowledgeTool` that backs `jsat__knowledge_query`, `/jsat knowledge`, and
`/jsat decide`.

---

## 🔁 JSAT Improve — Self-Improvement

JSAT watches for friction in **itself** — crashes, capability gaps, unhelpful errors, tools that
blow their time budget — and can turn what it finds into a fix proposal for JSAT.

```bash
jsat improve --list      # what JSAT has recorded about itself
jsat improve             # diagnose the top issue, draft a patch → bundle on disk
jsat improve --report    # open a pre-filled GitHub issue for you to review and submit
```

When one issue recurs, JSAT tells you:

```
💡 JSAT hit IndexNotFound 3x and may be able to fix itself — run: jsat improve
```

`jsat improve` reads the recorded issue, pulls the relevant JSAT source, asks **your configured AI
provider** to diagnose it and produce a unified diff, validates that diff in a throwaway sandbox,
and writes a bundle to `~/.jsat/improve/bundles/`:

| File | Contents |
|---|---|
| `manifest.json` | version, install kind, cluster, pre-patch file hashes, patch status |
| `analysis.md` | root cause and the reasoning behind the fix |
| `patch.diff` | the candidate unified diff |
| `issue.md` | ready-to-post issue body |

### What is collected — and what is not

| Recorded | Never recorded |
|---|---|
| JSAT's own stack frames, as paths relative to the package | Your file paths, code, or identifiers |
| Exception **type** names (`IndexNotFound`) | Exception message bodies (they embed your paths) |
| Tool/command names, JSAT version, Python version, OS | Your queries, graph contents, or repo name |
| Config **keys** and a finite allowlist of JSAT-owned values | Config **values** you supplied |

Anything that cannot be proven JSAT-internal is **dropped, not redacted** — a record that trips the
filter is discarded whole, and `jsat improve --list` tells you how many were dropped. Capture writes
to a local file only; **nothing leaves your machine** unless you run `--report`, which opens a
pre-filled issue in your browser for you to read and submit yourself.

**JSAT never modifies its own installed files.** A generated patch is inert data — it is validated
against a temporary copy and only becomes code after a human reviews it in a pull request.

### Turning it off

```bash
export JSAT_NO_IMPROVE=1              # this shell
```
```yaml
improve:
  enabled: false                      # or nudge: false to keep capture, drop the hint
privacy:
  no_telemetry: true                  # also disables capture
```
Capture is automatically disabled in CI.

**In Claude Code:** `/jsat improve` · **MCP tool:** `jsat__improve_status` (read-only)

---

## 💾 Session Files & Auto-Execute

Every major skill (`magic`, `crack`, `sprint`, `prompt`) writes two files automatically:

### Session file — resume interrupted runs

`~/.jsat/sessions/<skill>-<slug>-<YYYYMMDD-HHMM>.md`

Tracks which steps completed. Inspect and resume sessions from the shell:

```bash
jsat session save payments --task "fix the payment retry" --step "reproduce" --step "trace the payment path"
jsat session list                 # every session, newest first, with progress
jsat session show                 # steps and findings of the newest session
jsat session load payments        # load a saved session by its identifier
jsat session continue             # resume the newest in-progress session
jsat session rm <fragment>        # delete one
jsat session prune --keep 20      # tidy up (unfinished ones are kept)
```

The format is implemented in `jsat/_sessions.py`, so skills, `--continue`, and the
CLI all read and write the same thing. Files stay plain markdown — tick a checkbox
in your editor and JSAT honours it. Override the location with `JSAT_SESSIONS_DIR`.

You don't need a running skill to start a session: `jsat session save <identifier>`
captures whatever you are in the middle of from anywhere, auto-recording the
repo path and git branch/commit as context (unless `--no-context`). The identifier
is your handle — `jsat session load <identifier>` finds it again even days later,
and `--task` describes it for the list view. A plain `jsat session continue`
(or `/jsat <skill> --continue`) picks the newest one straight back up.

Inside an AI tool, pass `--continue` to pick up where a run left off:

```bash
/jsat magic --continue        # resume most recent interrupted magic session
/jsat crack --continue        # resume most recent interrupted crack session
/jsat sprint --continue       # resume most recent interrupted sprint
/jsat prompt --continue       # resume most recent interrupted prompt pipeline
```

The session file uses YAML frontmatter (`status: in_progress` / `completed`) and markdown checkboxes (`- [ ]` / `- [x]`) so it's human-readable.

### Actions file — auto-execute synthesis recommendations

`~/.jsat/sessions/<skill>-actions-<slug>-<YYYYMMDD-HHMM>.md`

After each skill finishes its analysis and writes its synthesis, it extracts the concrete recommended actions (commands to run, files to edit with line numbers, tests to write, commits to make) and writes them to an actions file. The AI then **immediately executes** each action in sequence, marking `[x]` as it goes:

```
📋 Actions: ~/.jsat/sessions/crack-actions-redesign-payment-20260731-1430.md
  ✅ Fix entropy threshold security.py line 112: done
  ✅ Add .claude to IndexerConfig exclude_patterns: done
  ✅ python -m pytest tests/ -q → 356 passed, 9 skipped: done
✅ All actions complete: ~/.jsat/sessions/crack-actions-redesign-payment-20260731-1430.md
```

The skill recommends **and** acts — nothing falls through the cracks.

---

## 📖 CLI Reference

### Core commands

| Command | Description |
|---|---|
| `jsat index [path]` | Build or update the codebase graph (incremental, parallel) |
| `jsat index . --force` | Full re-index — ignore incremental manifest |
| `jsat index . --watch` | Re-index on file change (requires `brew install entr`) |
| `jsat index . --languages python,go` | Index specific languages only |
| `jsat blast-radius <target>` | Trace downstream impact of a change (offline) |
| `jsat blast-radius --diff origin/main...HEAD` | Impact of a git range; `--output` writes Markdown |
| `jsat contract-check --base origin/main` | API contract compatibility between two refs; exits non-zero on breaking changes |
| `jsat security-review . --sarif security.sarif` | OWASP + secrets + dependency CVEs, with SARIF for CI |
| `jsat shell` | Start the interactive JSAT REPL |
| `jsat claude` | Open Claude Code with JSAT MCP tools loaded |
| `jsat codex [CODEX_ARGS...]` | Open Codex CLI with JSAT pre-loaded; forwards args such as `resume <session-id>` |
| `jsat opencode [OPENCODE_ARGS...]` | Open OpenCode with JSAT pre-loaded (project scope); forwards args such as `resume <session-id>` |
| `jsat cursor` | Open Cursor IDE with JSAT pre-loaded |
| `jsat windsurf` | Open Windsurf with JSAT pre-loaded |
| `jsat gemini` | Open Gemini CLI with JSAT pre-loaded |
| `jsat zed` | Open Zed editor with JSAT pre-loaded |
| `jsat gpt` | Open a GPT session with JSAT tools |
| `jsat ollama --model MODEL` (or `jsat ollama MODEL`) | Open the JSAT shell with `MODEL`; without one, reuses a model set via `jsat ai use ollama --model`, else auto-selects only when Ollama reports exactly one model |
| `jsat ollama --tool opencode [--model MODEL]` (or `jsat ollama opencode`) | Auto-connect JSAT, then launch OpenCode through Ollama with a local/cloud model; without `--model`, reuses the model saved by `jsat connect ollama opencode --model MODEL`, else shows Ollama's selector |
| `jsat start [TOOL] [--via auto\|native\|ollama]` | Start managed AI clients; TOOL defaults to `all` |
| `jsat stop [TOOL] [--force]` | Stop only validated JSAT-managed processes; defaults to `all` |
| `jsat restart [TOOL]` | Restart previous route/model/repo; defaults to all three clients |
| `jsat resume [TOOL] [--session ID]` | Resume AI-client sessions; defaults to all three clients |
| `jsat ps` | Show JSAT-managed AI-client processes and last launch settings |
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
| `jsat ui` | Start JSAT Studio — browser app on `localhost:7433` with a prompt bar and command palette |
| `jsat ui --tui` | Terminal UI instead of the browser (needs `pip install 'jsat[studio]'`) |
| `jsat session save <name> [--task <text>]` | Capture current working context under a named identifier (from anywhere) |
| `jsat session list` | List skill sessions with progress and status |
| `jsat session load <name>` | Load a saved session by its identifier |
| `jsat session continue` | Resume the newest in-progress session (alias for resume) |
| `jsat session prune --keep 20` | Delete old session files (unfinished kept) |
| `jsat note add "<text>"` | Save a note into the knowledge base |
| `jsat note search <query>` | Search notes, ADRs, and runbooks |
| `jsat improve --list` | Show friction JSAT has recorded in itself |
| `jsat improve` | Diagnose the top issue and draft a patch for JSAT |
| `jsat improve --report` | Open a pre-filled GitHub issue to review and submit |
| `jsat version` | Print JSAT version |

### Configuration

| Command | Description |
|---|---|
| `jsat init` | Generate `.jsat/config.yaml` for this repo (default: `solo` profile) |
| `jsat init --global` | Generate `~/.jsat/config.yaml` — applies to all projects |
| `jsat init --profile team` | Team profile (Neo4j, Qdrant, Redis, Claude API) |
| `jsat init --profile ci` | CI profile (SQLite, no AI, JSON logs) |
| `jsat init --profile raspberry-pi` | Low-RAM profile (SQLite, Ollama, batch size 8, 100 KB file cap) |

### AI provider management

| Command | Description |
|---|---|
| `jsat ai status` | Show all providers: available, active, free/paid |
| `jsat ai use <provider>` | Configure a provider and write to `.jsat/config.yaml` |
| `jsat ai use <provider> --global` | Configure provider globally in `~/.jsat/config.yaml` |
| `jsat ai use ollama --model qwen2.5:0.5b` | Use a specific Ollama model (exact tag) |
| `jsat ai test` | Send a test prompt and verify the provider works |
| `jsat ai models` | List models available from the configured provider |

### AI tool integrations

| Command | Description |
|---|---|
| `jsat connect claude` | Wire JSAT into Claude Code (project scope) + install 51 slash commands |
| `jsat connect claude --global` | Wire JSAT into Claude Code globally (all projects) |
| `jsat connect claude --no-skills` | MCP only — skip slash command installation |
| `jsat connect codex` | Wire JSAT into OpenAI Codex CLI via `~/.codex/config.toml` + `~/.codex/skills/jsat/SKILL.md` |
| `jsat connect codex --global` | Compatibility alias; writes the same global Codex MCP and skill files |
| `jsat connect opencode` | Wire JSAT into OpenCode for this repo (`.opencode/opencode.json` + `/jsat` commands + AGENTS.md block) |
| `jsat connect opencode --global` | Wire JSAT into OpenCode globally (`~/.config/opencode/opencode.json` + `/jsat` + `/jsat-help`); also works with `ollama launch` |
| `jsat connect ollama [TOOL]` | Wire JSAT into every supported Ollama-launched client, or one of `claude`, `codex`, `opencode` |
| `jsat connect ollama TOOL --model MODEL` | Also remember `MODEL` as `TOOL`'s default for `jsat ollama --tool TOOL` (single TOOL only) |
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

### Maintenance

| Command | Description |
|---|---|
| `jsat clean` | Remove cached data from `.jsat/` — flags: `--cache`, `--graph`, `--vectors`, `--history` |
| `jsat clean --all` | Full reset — delete cache, graph, vectors, and prompt history |
| `jsat update` | Self-upgrade JSAT via pip |
| `jsat update --pre` | Include pre-release versions |
| `jsat knowledge-ingest <path>` | Bulk-ingest markdown files (CLAUDE.md, ADRs, runbooks) into the knowledge base |
| `jsat knowledge-ingest . --pattern "**/*.md" --dry-run` | Preview what would be ingested without writing |
| `jsat mcp-server` | Start the JSAT MCP server on stdin/stdout — invoked automatically by Claude Code/Cursor; rarely run directly |
| `jsat mcp-server --repo /path --verbose` | Run manually against a specific repo with debug logging |

---

## 🐍 Python SDK

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
js.switch_ai("ollama", model="qwen2.5:0.5b")
js.switch_ai("anthropic", model="<model>")
js.switch_ai("gpt", model="gpt-4o-mini")

# Health check
health = js.doctor()
print(health["profile"], health["graph"]["backend"])
```

---

## Tools Overview (26 tools)

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
| 21 | **JSAT Magic** | AI-orchestrated skill composer — dynamically selects and runs the right skills for any task |
| 22 | **JSAT Plan** | Pre-implementation planning gate — six forcing questions + scope/architecture/security review |
| 23 | **JSAT Decide** | Architectural decision journal — log decisions and surface them by file or blast-radius context |
| 24 | **JSAT Sprint** | Seven-stage delivery workflow — Think → Plan → Build → Review → Test → Ship → Reflect |
| 25 | **JSAT Cohesion** | Code health analysis — flags oversized files, high complexity, and mixed responsibilities |
| 26 | **JSAT Improve** | Self-improvement — records friction JSAT hits in itself, then diagnoses it and drafts a patch to JSAT's own source (privacy-filtered, local-only) |

### Multi-Model Review

Tool 9 dispatches the diff to all configured models in parallel, collects findings, and surfaces only those confirmed by two or more models. Configure the model list and timeout in `.jsat/config.yaml`:

```yaml
review:
  models:
    - {provider: claude_cli, model: claude-sonnet-4-6}
    - {provider: ollama, model: qwen2.5:0.5b}
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
  provider: ollama         # also: anthropic, openai, openai_compat, claude_cli, opencode_cli, bob_cli, codex_cli, none
  model: qwen2.5:0.5b
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

improve:
  enabled: true            # record friction JSAT hits in itself (local file only)
  nudge: true              # hint to run `jsat improve` when an issue recurs
  nudge_threshold: 3       # occurrences before the hint appears
  nudge_cooldown_s: 86400  # min seconds between hints
  github_repo: iamjpsonkar/JaySoft-AI_Tools
```

### Profiles at a glance

| Profile | Graph | AI | Cache | Use case |
|---|---|---|---|---|
| `solo` | SQLite | Ollama *(no model preselected)* | Memory | Individual developer, no external services |
| `team` | Neo4j | Claude API | Redis | Shared graph, team-wide knowledge base |
| `ci` | SQLite | None | Memory | GitHub Actions, no API keys, JSON logs |
| `raspberry-pi` | SQLite | Ollama *(no model preselected)* | Disk | Low-RAM devices, batch size 8 |

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

All seven are in the default `indexer.languages` list, so installing the
grammar is all it takes — no config change. A language whose optional grammar
is absent contributes no nodes for those files rather than failing the index.

| Language | Parser | Grammar ships with |
|---|---|---|
| Python | tree-sitter-python | core |
| JavaScript / JSX | tree-sitter-javascript | core |
| TypeScript / TSX | tree-sitter-javascript | core |
| Go | tree-sitter-go | core |
| Java | tree-sitter-java | `jsat[standard]` |
| Ruby | tree-sitter-ruby | `jsat[standard]` |
| Rust | tree-sitter-rust | `jsat[standard]` |

Extracted per language: functions (parameters with types and defaults, return
type, decorators/annotations, first doc line, cyclomatic complexity), classes
(bases, interfaces, method count), and `CALLS` / `IMPORTS` / `INHERITS` /
`IMPLEMENTS` / `RAISES` edges. Files over `indexer.max_file_size_kb`
(default 500 KB) are skipped.

---

## Contributing

Contributions are welcome. Please open an issue or pull request on GitHub.

### Developing JSAT with an AI agent

**[`AGENTS.md`](AGENTS.md)** is the complete context file: repo map, call flow, an
extension cookbook for each surface (CLI / MCP tool / slash command / config /
provider), enforced conventions, testing, the environment traps that actually cost
time, the privacy and safety invariants, known debt, and a pre-flight checklist.
Point any AI agent at it before it touches the code.

### Running the tests

```bash
./local_test.sh --install    # editable install + dev deps in every venv it finds
./local_test.sh              # lint (identical command to CI) + CI-safe tests
./local_test.sh --doctor     # environment check, no tests
./local_test.sh --all        # everything (needs Neo4j, Qdrant, Redis)
./local_test.sh --both       # run the suite in every venv that has jsat
./local_test.sh --fix        # auto-fix lint
```

`--doctor` is worth running first. It catches the two environment problems that waste the
most time: a **stale non-editable install shadowing your checkout** (so your edits do
nothing), and **typer/click drift between venvs** — typer ≥0.27 vendors its own click, so
the CLI can behave differently in two environments while the test suite stays green in both.

### End-to-end self-test (no mocking)

`local_test.sh` runs the pytest suite — unit-level, with mocks where the code under
test expects them. `scripts/jsat-selftest.sh` is a different, complementary check: it
exercises the **currently installed `jsat` binary** as a real black box — real CLI
subprocess calls, a real scratch repo indexed for real, the real MCP server driven
over real stdio JSON-RPC, and (opt-in) a real headless `claude -p` agent driving the
real `/jsat` dispatcher. Any external dependency that isn't present (Ollama, Neo4j,
Qdrant, a CLI, an API key) is reported as **unavailable**, never silently skipped and
never counted as a failure. Emits a JSON + Markdown report any AI agent can read to
triage.

Suites run **in parallel by default**: each suite gets its own subprocess and a
private workspace (`JSAT_DATA_DIR` / sessions / improve / runtime all isolated),
so suites that mutate `os.environ` for in-process SDK calls or bind a fixed
port cannot interfere. The report is still deterministic (merged in suite
order). On a 4-core box `--ci-safe` dropped from ~5½ min to ~2¾ min with
identical results.

```bash
./scripts/jsat-selftest.sh              # full run — suites in parallel (default 4 jobs)
./scripts/jsat-selftest.sh --ci-safe    # no docker, no LLM, no external services
./scripts/jsat-selftest.sh --jobs 8     # bump concurrency on big machines
./scripts/jsat-selftest.sh --quick      # skip local_test.sh
./scripts/jsat-selftest.sh --sequential # debug one suite: in-process, one at a time
./scripts/jsat-selftest.sh --live-agent # + a real headless claude agent driving jsat
                                         # claude's real MCP config and a curated set of
                                         # /jsat skills end-to-end — costs real API
                                         # tokens (~$4-5, ~2 min for the full set)
```

- Repository: [github.com/iamjpsonkar/JaySoft-AI_Tools](https://github.com/iamjpsonkar/JaySoft-AI_Tools)
- Bug reports: open an issue on GitHub
- Author: Jay Prakash Sonkar — [iamjpsonkar@gmail.com](mailto:iamjpsonkar@gmail.com)
- License: MIT

---

## License

MIT License. Copyright (c) Jay Prakash Sonkar.
