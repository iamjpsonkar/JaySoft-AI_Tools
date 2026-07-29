# JSAT — AI Tool Integrations

JSAT works as an MCP server with every major AI coding tool. Each integration gives you the same
depth of codebase intelligence: a launcher command, auto-connection on first use, a full set of
skills or custom commands, and shell `switch` support.

---

## Feature Matrix

| Feature | Claude Code | Codex | Cursor | Windsurf | Continue | Zed | Gemini CLI | Bob Shell |
|---|---|---|---|---|---|---|---|---|
| `jsat <tool>` launcher | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| Auto-connect on launch | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| `jsat connect <tool>` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `--scope project/global` | ✅ | ✅ | ✅ | — (global) | — (global) | — (global) | — (global) | ✅ |
| Skills / custom commands | 31 slash cmds | instructions.md | .cursorrules | .windsurfrules | 31 slash cmds | .zed/JSAT.md | GEMINI.md | 31 slash cmds + BOB.md |
| `switch <tool>` in shell | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| `--keep-guidance` on disconnect | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Tool type | CLI | CLI | GUI | GUI | IDE ext | GUI | CLI | CLI |

---

## Quick Start (any tool)

```bash
# 1. Index your codebase
jsat index .

# 2. Open your AI tool with JSAT pre-loaded
jsat claude      # Claude Code
jsat codex       # OpenAI Codex CLI
jsat cursor      # Cursor IDE
jsat windsurf    # Windsurf
jsat gemini      # Gemini CLI
jsat zed         # Zed editor
jsat bob         # Bob Shell
```

Each launcher auto-connects JSAT if not already wired and opens the tool with 55 MCP tools ready.

---

## Per-Tool Details

### Claude Code

```bash
jsat claude                              # open with JSAT tools
jsat connect claude --global             # global — all sessions (recommended)
jsat connect claude                      # project scope only
jsat connect claude --no-skills          # MCP only, skip slash commands
```

**What gets installed (global):**
- `~/.claude/settings.json` — MCP server config
- `~/.claude/commands/jsat-*.md` — 31 slash commands

**What gets installed (project):**
- `.claude/settings.json` — MCP server config
- `.claude/commands/jsat-*.md` — 31 slash commands

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
jsat connect codex --global              # global — all sessions (recommended)
jsat connect codex                       # project scope only
```

**What gets installed:**
- `.codex/config.json` — MCP server config
- `.codex/instructions.md` — JSAT tool guidance (Codex reads at startup)

**In the JSAT shell:**
```
switch codex    → launch Codex CLI session
```

**Install Codex** (all platforms): `npm install -g @openai/codex`

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
jsat connect continue                    # wire JSAT in + install 31 /jsat-* commands
```

**What gets installed:**
- `~/.continue/config.json` — MCP server + 31 `customCommands`

**Custom commands (same 31 as Claude's slash commands):**
`/jsat-query`, `/jsat-blast-radius`, `/jsat-security`, `/jsat-review`, `/jsat-test-gaps`,
`/jsat-knowledge`, `/jsat-incident`, `/jsat-prompt`, `/jsat-tokens`, `/jsat-ithinking`,
and 21 more.

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
- `.bob/commands/jsat-*.md` (or `~/.bob/commands/`) — 31 `/jsat-*` slash commands
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
switch codex        → Codex CLI (reads .codex/config.json)
switch gemini       → Gemini CLI (reads ~/.gemini/settings.json + GEMINI.md)
switch cursor       → open Cursor IDE in background
switch windsurf     → open Windsurf IDE in background
switch zed          → open Zed in background
switch bob          → Bob Shell session
switch gpt          → GPT-4o in JSAT shell (needs OPENAI_API_KEY)
switch ollama       → local Ollama in JSAT shell
switch anthropic    → Claude API in JSAT shell (needs ANTHROPIC_API_KEY)
```

---

## Disconnect

```bash
jsat disconnect claude                   # Claude project scope
jsat disconnect claude --scope all       # Claude everywhere
jsat disconnect codex                    # Codex
jsat disconnect cursor                   # Cursor (global + project)
jsat disconnect windsurf                 # Windsurf
jsat disconnect continue                 # Continue (removes commands too)
jsat disconnect zed                      # Zed
jsat disconnect gemini                   # Gemini
jsat disconnect bob                      # Bob Shell
jsat disconnect all                      # every tool at once

# Keep guidance files (instructions.md, .cursorrules, etc.)
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

All 55 JSAT MCP tools are available to every connected AI tool:

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
