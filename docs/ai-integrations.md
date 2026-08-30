# JSAT — AI Tool Integrations

JSAT works as an MCP server with every major AI coding tool. Each integration gives you the same
depth of codebase intelligence: a launcher command, auto-connection on first use, a full set of
MCP tools, and shell `switch` support.

For native Codex, native Claude, native OpenCode, direct Ollama, or a coding client launched
through Ollama, start with the [tabbed integration chooser](integrations/index.md). Those guides
keep model ownership, local pulls, cloud sign-in, and managed lifecycle commands separate.

---

## Feature Matrix

| Feature | Claude Code | Codex | OpenCode | Cursor | Windsurf | Continue | Zed | Gemini CLI | Bob Shell |
|---|---|---|---|---|---|---|---|---|---|
| `jsat <tool>` launcher | ✅ | ✅ | via `jsat ollama --tool opencode` | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| Auto-connect on launch | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| `jsat connect <tool>` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `--scope project/global` | ✅ | Global only | Global only | ✅ | — (global) | — (global) | — (global) | — (global) | ✅ |
| Skills / custom commands | 41 slash cmds | `$jsat` dispatcher | `/jsat` + `/jsat-help` | .cursorrules | .windsurfrules | 10 custom cmds | .zed/JSAT.md | GEMINI.md | 41 slash cmds + BOB.md |
| `switch <tool>` in shell | ✅ | ✅ | — | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| `--keep-guidance` on disconnect | ✅ | ✅ | n/a | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Tool type | CLI | CLI | CLI | GUI | GUI | IDE ext | GUI | CLI | CLI |

---

## Quick Start (any tool)

```bash
# 1. Index your codebase
jsat index .

# 2. Open your AI tool with JSAT pre-loaded
jsat claude      # Claude Code
jsat codex       # OpenAI Codex CLI
jsat ollama --tool opencode  # OpenCode through Ollama; auto-connects JSAT
jsat cursor      # Cursor IDE
jsat windsurf    # Windsurf
jsat gemini      # Gemini CLI
jsat zed         # Zed editor
jsat bob         # Bob Shell
```

Each launcher auto-connects JSAT if not already wired and opens the tool with 69 MCP tools ready.

### Managed lifecycle

```bash
jsat start                           # Claude + Codex + OpenCode, one terminal each
jsat start opencode --via ollama     # one client, Ollama selector
jsat start --model gemma4:31b-cloud # all three through one Ollama model
jsat ps
jsat restart                         # Claude + Codex + OpenCode
jsat stop                            # every running managed client
jsat resume                          # Claude + Codex + OpenCode
jsat resume codex --session ID       # one named Codex session
```

`all` is the default target. Since interactive TUIs cannot share one terminal,
multi-client start, restart, and resume open a separate terminal window for each
client. Supported terminal launchers are `x-terminal-emulator`, GNOME Terminal,
Konsole, and Xfce Terminal. An explicit target runs in the current terminal.

JSAT stores a minimal process record under `~/.jsat/runtime/`. `stop` validates the
recorded process-start identity before sending a signal, then stops that process and
its current descendants. It never kills processes merely because their executable is
named `claude`, `codex`, or `opencode`. Use `--force` only when graceful shutdown
times out.

`jsat resume` resumes AI-client conversation history. `jsat session resume` remains
the separate command for interrupted JSAT skills such as `magic` and `crack`.

---

## Per-Tool Details

### OpenCode through Ollama

```bash
jsat index .
jsat connect ollama tool=opencode           # configure only OpenCode
jsat ollama --tool opencode                  # choose local or cloud interactively
jsat ollama --tool opencode -m qwen3.5       # local
ollama signin
jsat ollama --tool opencode -m gemma4:31b-cloud  # cloud
```

The launcher writes JSAT's MCP entry to `~/.config/opencode/opencode.json` before
running `ollama launch opencode`. It also installs `/jsat` and `/jsat-help` under
`~/.config/opencode/commands/`. Ollama's inline model configuration is deep-merged
with that file. A standalone OpenCode installation is not required. For configuration
without launch, run `jsat connect opencode`, then run bare `ollama` and choose
OpenCode → sign in if prompted → choose a model.

`jsat connect ollama` configures every Ollama-launched client JSAT currently
supports: Claude, Codex, and OpenCode. Use `--tool opencode`, `opencode`, or
`tool=opencode` to configure only one. JSAT does not configure unknown menu entries
because each client has a different MCP configuration format.

Provider routing remains separate for every mode:

- Native Claude, Codex, and OpenCode use `claude_cli`, `codex_cli`, and
  `opencode_cli`, respectively.
- Ollama-launched OpenCode reads `OPENCODE_CONFIG_CONTENT`; Ollama-launched Claude
  reads the `ANTHROPIC_DEFAULT_*_MODEL` launch variables.
- The selected Ollama model can be local or cloud. It overrides `.jsat/config.yaml`
  only for that launched process and does not require another pull.

---

### Claude Code

```bash
jsat claude                              # open with JSAT tools
jsat connect claude --global             # global — all sessions (recommended)
jsat connect claude                      # project scope only
jsat connect claude --no-skills          # MCP only, skip slash commands
```

**What gets installed (global):**
- `~/.claude/settings.json` — MCP server config
- `~/.claude/commands/jsat-*.md` — 41 slash commands

**What gets installed (project):**
- `.claude/settings.json` — MCP server config
- `.claude/commands/jsat-*.md` — 41 slash commands

**Slash commands:** `/jsat-query`, `/jsat-blast-radius`, `/jsat-security`, `/jsat-review`,
`/jsat-test-gaps`, `/jsat-knowledge`, `/jsat-incident`, `/jsat-prompt`,
`/jsat-tokens`, `/jsat-ithinking`, and 21 more.

**In the JSAT shell:**
```
switch claude-cli    → launch full Claude Code session
```

---

### OpenAI Codex CLI

```bash
jsat codex                               # open with JSAT pre-loaded
jsat connect codex                       # global MCP config + $jsat skill
jsat codex --repo /path/to/repo           # launch Codex in a specific repo
jsat codex resume <session-id>            # resume an existing Codex session
```

**What gets installed:**
- `~/.codex/config.toml` — one `[mcp_servers.jsat]` entry
- `~/.codex/skills/jsat/SKILL.md` — one Codex skill dispatcher for `$jsat`

JSAT does **not** generate `.codex/`, `AGENTS.md`, or `.agents/skills` inside the
target repo for Codex. Run Codex from the repo you want to analyze, or use
`jsat codex --repo /path/to/repo`; JSAT resolves that working directory at runtime.
Any extra arguments after `jsat codex` are forwarded to the real Codex CLI.

**Use in Codex:** run `$jsat magic TASK`, `$jsat query QUESTION`, or ask naturally,
e.g. "use JSAT to trace the blast radius of `src/payment/service.py`". The
dispatcher also treats `@jsat magic TASK` as the same JSAT request when Codex
routes it to the skill. Direct MCP tools such as `jsat__query`,
`jsat__blast_radius`, `jsat__security_review`, `jsat__get_test_gaps`, and
`jsat__submit_for_review` remain available.

**In the JSAT shell:**
```
switch codex    → launch Codex CLI session
```

**Install Codex:** `curl -fsSL https://chatgpt.com/codex/install.sh | sh`

---

### Cursor

```bash
jsat cursor                              # open Cursor with JSAT pre-loaded
jsat connect cursor                      # global scope (default)
jsat connect cursor --scope project      # project scope (.cursor/mcp.json)
```

**What gets installed:**
- `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project) — MCP server
- `.cursorrules` — JSAT tool guidance (Cursor reads from project root)

**In the JSAT shell:**
```
switch cursor    → open Cursor in background
```

**Install Cursor:** macOS: `brew install --cask cursor` · Linux/Windows: [cursor.com/download](https://cursor.com/download)

---

### Windsurf

```bash
jsat windsurf                            # open Windsurf with JSAT pre-loaded
jsat connect windsurf                    # wire JSAT in
```

**What gets installed:**
- `~/.codeium/windsurf/mcp_config.json` — MCP server
- `.windsurfrules` — JSAT tool guidance (Windsurf reads from project root)

**In the JSAT shell:**
```
switch windsurf    → open Windsurf in background
```

**Install Windsurf:** macOS: `brew install --cask windsurf` · Linux/Windows: [windsurf.ai/download](https://windsurf.ai/download)

---

### Continue.dev

Continue is an IDE extension (VS Code, JetBrains). There's no `jsat continue` launcher since it
runs inside your IDE.

```bash
jsat connect continue                    # wire JSAT in + install 10 /jsat-* commands
```

**What gets installed:**
- `~/.continue/config.json` — MCP server + 10 `customCommands`

**Custom commands (curated subset):**
`/jsat-query`, `/jsat-blast-radius`, `/jsat-security`, `/jsat-review`, `/jsat-test-gaps`,
`/jsat-knowledge`, `/jsat-incident`, `/jsat-prompt-rewrite`, `/jsat-tokens`, `/jsat-ithinking`.

After connecting, reload Continue: `Cmd/Ctrl+Shift+P → Continue: Reload`.

---

### Zed

```bash
jsat zed                                 # open Zed with JSAT pre-loaded
jsat connect zed                         # wire JSAT in
```

**What gets installed:**
- `~/.config/zed/settings.json` — context server config
- `.zed/JSAT.md` — JSAT tool guidance as project context

**In the JSAT shell:**
```
switch zed    → open Zed in background
```

**Install Zed:** macOS: `brew install --cask zed` · Linux: `curl -f https://zed.dev/install.sh | sh` · Windows: not yet available

---

### Google Gemini CLI

```bash
jsat gemini                              # open Gemini CLI with JSAT pre-loaded
jsat connect gemini                      # wire JSAT in
```

**What gets installed:**
- `~/.gemini/settings.json` — MCP server config
- `GEMINI.md` — JSAT tool guidance (Gemini CLI reads from project root automatically)

**In the JSAT shell:**
```
switch gemini    → launch Gemini CLI session
```

**Install Gemini CLI** (all platforms): `npm install -g @google/gemini-cli`


### Bob Shell

```bash
jsat bob                                 # open Bob Shell with JSAT pre-loaded
jsat bob --mode advanced                 # open in specific mode (plan, code, advanced, ask)
jsat connect bob --global                # global — all sessions (recommended)
jsat connect bob                         # project scope only
jsat connect bob --no-commands           # MCP + BOB.md only, skip slash commands
```

`jsat bob` opens a clean **interactive** Bob session; JSAT tools and guidance are
loaded from `.bob/` and `BOB.md`, so nothing is injected as a throwaway prompt.

**What gets installed:**
- `.bob/settings.json` (project) or `~/.bob/settings.json` (global) — MCP server config
- `.bob/commands/jsat-*.md` (or `~/.bob/commands/`) — 41 `/jsat-*` slash commands
- `BOB.md` — JSAT tool guidance (Bob Shell reads from project root)

**Slash commands:** type `/` in Bob Shell to browse them — `/jsat-query`,
`/jsat-blast-radius`, `/jsat-security`, `/jsat-review`, `/jsat-test-gaps`,
`/jsat-prompt`, `/jsat-ithinking`, and 24 more. `/jsat-prompt` optimizes your
query and then answers it (use `--optimize-only` to just see the rewrite).

**In the JSAT shell:**
```
switch bob    → launch Bob Shell session
```

**Install Bob Shell** (all platforms): `npm install -g @ibm/bob-shell`

**Bob Shell modes:**
- `plan` — Planning and design mode
- `code` — Code implementation mode
- `advanced` — Advanced code mode with more tools
- `ask` — Question and answer mode

---



---

## JSAT Shell — `switch` Reference

From inside `jsat shell`, you can switch to any tool:

```
switch claude-cli   → full Claude Code + JSAT MCP (recommended for Claude)
switch codex        → Codex CLI (reads ~/.codex/config.toml)
switch gemini       → Gemini CLI (reads ~/.gemini/settings.json + GEMINI.md)
switch cursor       → open Cursor IDE in background
switch windsurf     → open Windsurf IDE in background
switch zed          → open Zed in background
switch bob          → Bob Shell session
switch gpt <model>  → OpenAI API in JSAT shell (needs OPENAI_API_KEY)
switch ollama <model>    → Ollama in JSAT shell
switch anthropic <model> → Claude API in JSAT shell (needs ANTHROPIC_API_KEY)
```

---

## Disconnect

```bash
jsat disconnect claude                   # Claude project scope
jsat disconnect claude --scope all       # Claude everywhere
jsat disconnect codex                    # Codex
jsat disconnect opencode                 # OpenCode global MCP entry
jsat disconnect cursor                   # Cursor (global + project)
jsat disconnect windsurf                 # Windsurf
jsat disconnect continue                 # Continue (removes commands too)
jsat disconnect zed                      # Zed
jsat disconnect gemini                   # Gemini
jsat disconnect bob                      # Bob Shell
jsat disconnect all                      # every tool at once

# Keep guidance files for integrations that generate them (.cursorrules, etc.)
jsat disconnect cursor --keep-guidance
```

---

## List Active Connections

```bash
jsat connect list       # show every tool that has JSAT wired
jsat doctor             # full health check including connected tools
```

---

## MCP Tools Available in Every Tool

All 69 JSAT MCP tools are available to every connected AI tool:

| Category | Key tools |
|---|---|
| Graph exploration | `jsat__query`, `jsat__get_function`, `jsat__get_class`, `jsat__trace_call_chain` |
| Impact analysis | `jsat__blast_radius`, `jsat__blast_radius_diff`, `jsat__blast_radius_file` |
| Security | `jsat__security_review`, `jsat__list_secrets`, `jsat__get_auth_coverage` |
| Code quality | `jsat__submit_for_review`, `jsat__get_test_gaps`, `jsat__generate_unit_test` |
| Knowledge | `jsat__knowledge_query`, `jsat__knowledge_add`, `jsat__generate_runbook` |
| Investigation | `jsat__investigate_incident`, `jsat__get_recent_changes` |
| Prompt tools | `jsat__prompt_optimize`, `jsat__prompt_multi_agent`, `jsat__prompt_diff` |
| Token tools | `jsat__token_count`, `jsat__token_compress`, `jsat__token_budget` |
| Migration | `jsat__validate_migration`, `jsat__suggest_zero_downtime` |
| IThinking | `jsat__ithinking_plan`, `jsat__ithinking_reflect` |
