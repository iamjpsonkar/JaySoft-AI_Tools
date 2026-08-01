# CLI Reference

All JSAT commands start with `jsat`. Run `jsat --help` or `jsat <command> --help` for any command.

---

## 1. Core Commands

### `jsat index`

Build or update the codebase graph.

```
jsat index [PATH] [OPTIONS]
```

| Argument / Flag | Default | Description |
|----------------|---------|-------------|
| `PATH` | repo root | Directory to index |
| `--branch`, `-b` | `HEAD` | Git branch to index |
| `--force`, `-f` | false | Full re-index — ignore incremental manifest |
| `--languages`, `-l` | auto | Comma-separated list, e.g. `python,go` |
| `--incremental/--full` | incremental | Use incremental or full index strategy |
| `--watch`, `-w` | false | Re-index on file change (requires `entr`: `brew install entr`) |

```bash
jsat index .                                  # incremental, parallel (4-8× faster)
jsat index src/payments/ --force             # full re-index
jsat index . --branch feature/new-api --languages python,go
jsat index . --watch                          # continuous re-index on save
```

**How incremental mode works:**

On the first run JSAT writes `index-manifest.json` in the data directory (see [Data Storage](configuration.md#data-storage-vs-config-file)) containing an `mtime + sha256` entry for every indexed file. On subsequent runs only files whose content actually changed are re-parsed; everything else is skipped. A 500-file repo with 5 changed files goes from ~3 s to ~100 ms.

**Rich metadata extracted (v0.2.0+):**

Every Function node now includes `parameters`, `return_type`, `decorators`, `docstring`, `complexity`, and `loc`. Every Class node includes `bases`, `decorators`, `docstring`, and `method_count`. New edge types `INHERITS`, `IMPLEMENTS`, and `RAISES` are also created.

---

### `jsat shell`

Start the JSAT interactive shell.

```
jsat shell [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repository root |
| `--verbose`, `-v` | false | Enable DEBUG logging |

```bash
jsat shell
jsat shell --repo /path/to/project
```

Inside the shell, type natural language questions or built-in commands:

```
> what does this project do?
> blast-radius src/payment/refund.py
> security-review
> incident "500 errors since 14:00"
> switch claude
> status
> help
```

---

### `jsat claude`

Open Claude Code with all JSAT MCP tools available.

```
jsat claude [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repository root |
| `--verbose`, `-v` | false | Enable DEBUG logging |

```bash
jsat claude
jsat claude --repo /path/to/project
```

Requires Claude Code CLI to be installed. JSAT must be connected first (`jsat connect claude`).

---

### `jsat gpt`

Open a GPT-4o session with JSAT tools.

```
jsat gpt [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repository root |
| `--verbose`, `-v` | false | Enable DEBUG logging |

```bash
export OPENAI_API_KEY=sk-...
jsat gpt
```

---

### `jsat ollama`

Open an Ollama-powered session (local, free, no API key).

```
jsat ollama [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repository root |
| `--model`, `-m` | `llama3.2` | Ollama model name |
| `--verbose`, `-v` | false | Enable DEBUG logging |

```bash
jsat ollama
jsat ollama --model phi3:mini
jsat ollama --model qwen2.5-coder:7b
```

---

### `jsat doctor`

Run a system health check. Shows system, services, AI providers, and index status.

```
jsat doctor [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--refresh` | false | Re-detect system (ignore cached profile) |
| `--json` | false | Output raw JSON |

```bash
jsat doctor
jsat doctor --refresh
jsat doctor --json | jq '.ai'
```

---

### `jsat version`

Print the installed JSAT version.

```bash
jsat version
# jsat 0.1.0
```

---

### `jsat crack`

Run a multi-agent war room on a complex engineering decision. Six agents run in
sequence — each receives all prior agents' findings as context.

**Agents:** architect → security → implementer → tester → skeptic → moderator

```bash
jsat crack "redesign the payment retry system"
jsat crack --phases 4 "add idempotency to the charge endpoint"
jsat crack --single "should we use Redis or Postgres for sessions?"
```

| Option | Description |
|---|---|
| `--phases N` | Number of phases (2–6, default 6 — one agent per phase) |
| `--single` | Run all 6 agents at once (may timeout on complex tasks) |
| `--continue` | Resume the most recent `in_progress` crack session from `~/.jsat/sessions/` |

Session file written to `~/.jsat/sessions/crack-<slug>-<ts>.md`; actions file auto-executed after synthesis.

### `jsat short`

Get the shortest possible correct answer (≤3 sentences, or one sentence with `--one-line`).

```bash
jsat short "what does process_refund do?"
jsat short --one-line "what's the auth pattern used here?"
```

### `jsat prompt`

Classify, optimize, execute, and verify a codebase question through 6 phases:
Discuss → Plan → Execute → Verify → Synthesize.

```bash
jsat prompt "what calls process_refund?"
jsat prompt --rewrite "fix the logger in PaymentService.charge"
jsat prompt --type structural "trace the checkout call chain"
jsat prompt --optimize-only "why is checkout slow?"
jsat prompt --single "what does the payment service do?"
```

| Option | Description |
|---|---|
| `--rewrite` / `--agent` | Phase 1: optimize with 1 LLM rewrite agent |
| `--agents` | Phase 1: optimize with 3 parallel LLM agents |
| `--type <type>` | Override query type classification (structural/lookup/security/incident/coverage/general) |
| `--service <name>` | Scope all query phases to one service |
| `--optimize-only` | Stop after Phase 1; show optimized prompt only |
| `--single` | Original one-shot flow (no phasing) |
| `--phases N` | Override phase count (2–6, default 6) |
| `--continue` | Resume the most recent `in_progress` prompt session from `~/.jsat/sessions/` |

Session file written to `~/.jsat/sessions/prompt-<slug>-<ts>.md`; actions file auto-executed after Phase 6.

### `jsat magic`

AI-orchestrated skill composer. Analyzes any task, selects the right skills from all 39,
and runs them in the optimal order.

```bash
/jsat magic add retry logic to the payment service
/jsat magic --depth deep redesign the authentication flow
/jsat magic --preview investigate the checkout 500 errors   # plan only
/jsat magic --service PaymentService what are the test gaps?
```

| Option | Description |
|---|---|
| `--depth quick\|standard\|deep` | Cap skills at 4/8/15 (default: standard) |
| `--budget N` | Explicit cap on skill invocations |
| `--service <name>` | Scope all skills to one service |
| `--preview` | Compose and show the plan; do not run |
| `--continue` | Resume the most recent `in_progress` magic session from `~/.jsat/sessions/` |

Session file written to `~/.jsat/sessions/magic-<slug>-<ts>.md`; actions file auto-executed after synthesis.

### `jsat plan`

Pre-implementation planning gate. Six forcing questions + scope, architecture, and security review.

```bash
/jsat plan add idempotency keys to the payment mutation
/jsat plan --scope refactor the retry logic
/jsat plan --security add a new admin endpoint
```

### `jsat decide`

Architectural decision journal. Log decisions; retrieve by file, topic, or blast-radius context.

```bash
/jsat decide log --impact h Chose PostgreSQL for ACID compliance
/jsat decide context src/payments/service.py
/jsat decide search caching strategy
/jsat decide list adr
```

### `jsat sprint`

Seven-stage delivery workflow: Think → Plan → Build → Review → Test → Ship → Reflect.

```bash
/jsat sprint add rate limiting to the checkout API
/jsat sprint --stage 4 add rate limiting    # resume from Review
/jsat sprint --dry redesign auth flow
/jsat sprint --continue                     # resume most recent interrupted sprint
```

| Option | Description |
|---|---|
| `--stage N` | Start from stage N (1–7), skipping earlier stages |
| `--dry` | Show the sprint plan without running any tools |
| `--continue` | Resume the most recent `in_progress` sprint session from `~/.jsat/sessions/` |

Session file written to `~/.jsat/sessions/sprint-<slug>-<ts>.md`; actions file auto-executed after Stage 7.

### `jsat cohesion`

Code health analysis — flags oversized files, high-complexity functions, and mixed responsibilities.

```bash
/jsat cohesion src/
/jsat cohesion --threshold 600 --service PaymentService
/jsat cohesion --functions jsat/cli.py
```

---

## 2. AI Commands (`jsat ai`)

### `jsat ai status`

Show which AI providers are available and which is currently configured.

```bash
jsat ai status
```

Output columns: Provider, Status, Free, Notes/Models.

---

### `jsat ai use`

Configure JSAT to use a specific AI provider.

```
jsat ai use PROVIDER [OPTIONS]
```

| Argument / Flag | Description |
|----------------|-------------|
| `PROVIDER` | `ollama`, `anthropic`, `openai`, `lmstudio`, `claude_cli`, `bob_cli` |
| `--model`, `-m` | Override the default model for this provider |
| `--config`, `-c` | Config file to write (default: `.jsat/config.yaml`, or `~/.jsat/config.yaml` with `--global`) |
| `--global`, `-g` | Write to `~/.jsat/config.yaml` — applies to all projects on this machine |

```bash
# Per-repo (writes .jsat/config.yaml)
jsat ai use ollama
jsat ai use ollama --model phi3:mini
jsat ai use anthropic
jsat ai use anthropic --model claude-haiku-4-5-20251001
jsat ai use openai --model gpt-4o-mini
jsat ai use claude_cli
jsat ai use lmstudio

# Global (writes ~/.jsat/config.yaml)
jsat ai use claude_cli --global
jsat ai use anthropic --global
```

Runs a connectivity test after writing and reports whether the AI is reachable.

---

### `jsat ai test`

Send a test prompt to the configured AI and print the response.

```
jsat ai test [PROMPT]
```

| Argument | Default | Description |
|---------|---------|-------------|
| `PROMPT` | `"Say hello in one sentence."` | Prompt to send |

```bash
jsat ai test
jsat ai test "what is 2 + 2?"
```

---

### `jsat ai models`

List available models for the configured provider.

- For **Ollama**: queries `http://localhost:11434/api/tags`
- For **LM Studio**: queries `http://localhost:1234/v1/models`
- For cloud providers: shows the currently configured model (no remote list)

```bash
jsat ai models
```

---

## 3. Connect Commands (`jsat connect`)

JSAT works as an MCP server with any AI tool that supports the Model Context Protocol. One command wires it in — all 55 JSAT tools are immediately available to the AI.

### `jsat connect claude`

Wire JSAT into Claude Code as an MCP server and install the `/jsat` dispatcher (39 subcommands) and `/jsat-help`.

```
jsat connect claude [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--scope`, `-s` | `project` | `project` → `.claude/settings.json` \| `global` → `~/.claude/settings.json` |
| `--global`, `-g` | false | Shorthand for `--scope global` — one-time setup for all Claude projects |
| `--repo`, `-r` | `.` | Repo path passed to the MCP server |
| `--install-skills/--no-skills` | `--install-skills` | Install `/jsat-*` slash commands |
| `--show` | false | Print the written config |

```bash
jsat connect claude                         # project scope
jsat connect claude --global                # global — all Claude Code sessions (recommended)
jsat connect claude --scope global          # same as --global
jsat connect claude --no-skills             # MCP only, no slash commands
jsat connect claude --show                  # print config after writing
```

Restart Claude Code after running.

### `/jsat` dispatcher

`jsat connect claude` installs two commands:

- **`/jsat <subcommand>`** — single dispatcher routing to all 39 skills
- **`/jsat-help [command]`** — standalone help command; no args lists all 39 commands with one-liners; `/jsat-help <command>` shows full flags and examples

```bash
/jsat-help               # list all 39 subcommands with descriptions
/jsat-help magic         # full flags and examples for /jsat magic
/jsat query <question>   # answer codebase questions (6-phase Discuss→Verify)
/jsat crack <task>       # multi-agent war room (artifact carry-forward)
/jsat aw <task>          # workflow advisor (classify + run optimal sequence)
/jsat lazy <task>        # reuse-first: check what exists before writing new code
/jsat smart <question>   # terse mode: compressed answers, no filler
/jsat security [path]    # OWASP scan + CVE check + secret detection
/jsat blast-radius <target>  # blast radius analysis
/jsat review <diff>      # multi-model code review
```

Skill files are bundled in the JSAT package at `jsat/commands/jsat-*.md` and read
directly by `_write_jsat_dispatcher()` when `jsat connect claude` runs. Updates to
skill files are picked up automatically on next `jsat connect claude`.

### MCP server authentication

The MCP server defaults to **open access with a startup warning** when no auth env vars are set. Auth is only enforced when explicitly configured.

| Env var | Effect |
|---------|--------|
| *(none)* | Open access — tools work, warning logged at startup |
| `JSAT_MCP_ALLOW_INSECURE=1` | Open access, warning silenced — written automatically by `jsat connect claude` |
| `JSAT_MCP_TOKEN=<secret>` | Legacy single-token auth — all callers must pass this token |
| `JSAT_MCP_TOKEN_ROLES=<json>` | RBAC map `{"token": "role"}` — roles: `admin`, `developer`, `viewer` |

`jsat connect claude` automatically sets `JSAT_MCP_ALLOW_INSECURE=1` in the MCP server environment so local dev works without additional config. To enforce auth, add `JSAT_MCP_TOKEN` or `JSAT_MCP_TOKEN_ROLES` to your shell environment before starting Claude Code.

---

### `jsat connect codex`

Wire JSAT into the OpenAI Codex CLI as an MCP server and write agent instructions.

```
jsat connect codex [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--scope`, `-s` | `project` | `project` → `.codex/` \| `global` → `~/.codex/` |
| `--global`, `-g` | false | Shorthand for `--scope global` — all Codex sessions |
| `--repo`, `-r` | `.` | Repo path passed to the MCP server |
| `--no-instructions` | false | MCP config only — skip instructions.md |

```bash
jsat connect codex                          # project scope
jsat connect codex --global                 # global — all Codex sessions (recommended)
jsat connect codex --scope global           # same as --global
```

Writes two files:
- `.codex/config.json` (or `~/.codex/config.json` with `--global`) — MCP server registration
- `.codex/instructions.md` (or `~/.codex/instructions.md`) — JSAT tool guidance

---

### `jsat connect cursor`

Wire JSAT into Cursor as an MCP server.

```
jsat connect cursor [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repo path for the MCP server |

```bash
jsat connect cursor
```

Writes to `~/.cursor/mcp.json`. Restart Cursor after running.

> **Note:** Cursor reads `.cursorrules` from the project root as agent instructions. You can copy the content from `.codex/instructions.md` or `.windsurfrules` if you want JSAT guidance in Cursor too.

---

### `jsat connect windsurf`

Wire JSAT into Windsurf (Codeium) as an MCP server and write `.windsurfrules`.

```
jsat connect windsurf [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repo path for the MCP server |
| `--no-instructions` | false | MCP config only — skip .windsurfrules |

```bash
jsat connect windsurf
```

Writes two files:
- `~/.codeium/windsurf/mcp_config.json` — MCP server registration
- `.windsurfrules` — JSAT tool guidance (Windsurf reads from project root automatically)

Restart Windsurf after running.

---

### `jsat connect continue`

Wire JSAT into Continue.dev as an MCP server and add 10 `/jsat-*` custom commands.

```
jsat connect continue [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repo path for the MCP server |
| `--no-instructions` | false | MCP config only — skip custom commands |

```bash
jsat connect continue
```

Writes to `~/.continue/config.json`:
- `mcpServers` array entry — MCP server registration
- `customCommands` entries — 10 `/jsat-*` slash commands:
  `/jsat-query`, `/jsat-blast-radius`, `/jsat-security`, `/jsat-review`,
  `/jsat-test-gaps`, `/jsat-knowledge`, `/jsat-incident`,
  `/jsat-prompt-rewrite`, `/jsat-tokens`, `/jsat-ithinking`

Reload Continue (Cmd/Ctrl+Shift+P → "Continue: Reload") to activate.

---

### `jsat connect zed`

Wire JSAT into Zed editor as a context server and write `.zed/JSAT.md`.

```
jsat connect zed [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repo path for the MCP server |
| `--no-instructions` | false | Context server only — skip .zed/JSAT.md |

```bash
jsat connect zed
```

Writes two files:
- `~/.config/zed/settings.json` — `context_servers` registration
- `.zed/JSAT.md` — JSAT tool guidance (project context for Zed)

Restart Zed after running.

---

### `jsat connect gemini`

Wire JSAT into the Google Gemini CLI as an MCP server and write `GEMINI.md`.

```
jsat connect gemini [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repo path for the MCP server |
| `--no-instructions` | false | MCP config only — skip GEMINI.md |

```bash
jsat connect gemini
```

Writes two files:
- `~/.gemini/settings.json` — MCP server registration
- `GEMINI.md` — JSAT tool guidance (Gemini CLI reads from project root automatically)

Restart Gemini CLI after running.

---

### `jsat connect bob`

Wire JSAT into Bob Shell (`@ibm/bob-shell`) as an MCP server, write BOB.md guidance, and install `/jsat-*` slash commands.

```
jsat connect bob [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--scope`, `-s` | `project` | `project` → `.bob/settings.json` \| `global` → `~/.bob/settings.json` |
| `--global`, `-g` | false | Shorthand for `--scope global` — all Bob sessions |
| `--repo`, `-r` | `.` | Repo path for the MCP server |
| `--no-instructions` | false | Skip writing BOB.md |
| `--install-commands/--no-commands` | `--install-commands` | Install `/jsat-*` slash commands |

```bash
jsat connect bob                            # project scope
jsat connect bob --global                   # global — all Bob sessions (recommended)
```

Writes:
- `.bob/settings.json` (or `~/.bob/settings.json`) — MCP server registration
- `.bob/commands/jsat-*.md` (or `~/.bob/commands/`) — 31 slash commands
- `BOB.md` — JSAT tool guidance (Bob Shell reads from project root automatically)

---

### `jsat connect list`

Show all AI tools that have JSAT wired as an MCP server.

```bash
jsat connect list
```

Checks all 9 known config locations:

| Tool | Config file |
|---|---|
| Claude Code (project) | `.claude/settings.json` |
| Claude Code (global) | `~/.claude/settings.json` |
| Codex (project) | `.codex/config.json` |
| Codex (global) | `~/.codex/config.json` |
| Cursor | `~/.cursor/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Continue | `~/.continue/config.json` |
| Zed | `~/.config/zed/settings.json` |
| Gemini CLI | `~/.gemini/settings.json` |

---

## 4. Disconnect Commands (`jsat disconnect`)

Remove JSAT from one or all AI tools.

```
jsat disconnect TOOL [OPTIONS]
```

| Argument | Default | Description |
|---------|---------|-------------|
| `TOOL` | `claude` | `claude` \| `codex` \| `cursor` \| `windsurf` \| `continue` \| `zed` \| `gemini` \| `all` |
| `--scope`, `-s` | `project` | `project`, `global`, or `all` (claude and codex only) |
| `--keep-skills` | false | Keep `/jsat-*` skill files when disconnecting from Claude Code |

```bash
jsat disconnect claude                       # Claude Code project scope
jsat disconnect claude --scope global        # Claude Code global
jsat disconnect claude --scope all           # Claude Code everywhere
jsat disconnect claude --keep-skills         # remove MCP entry, keep slash commands
jsat disconnect codex                        # Codex project scope
jsat disconnect codex --scope global         # Codex global
jsat disconnect cursor                       # Cursor
jsat disconnect windsurf                     # Windsurf
jsat disconnect continue                     # Continue.dev
jsat disconnect zed                          # Zed
jsat disconnect gemini                       # Gemini CLI
jsat disconnect all                          # every tool at once
```

Restart the relevant AI tool after disconnecting.

---

## 5. Init Command

### `jsat init`

Generate a starter JSAT config for a given profile.

```
jsat init [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--profile`, `-p` | `solo` | `solo`, `team`, `ci`, or `raspberry-pi` |
| `--output`, `-o` | `.jsat/config.yaml` | Output path (ignored when `--global` is set) |
| `--global`, `-g` | false | Write to `~/.jsat/config.yaml` — applies to all projects on this machine |

```bash
# Per-repo config
jsat init --profile solo
jsat init --profile team
jsat init --profile ci
jsat init --profile raspberry-pi

# Global config — one-time setup, applies to all projects
jsat init --global --profile solo
```

`--global` writes `~/.jsat/config.yaml`. Any repo that does not have its own `.jsat/config.yaml` automatically uses the global config.

---

## 6. CI Setup Command

### `jsat ci-setup`

Write a CI workflow file for JSAT. By default targets GitHub Actions; use `--provider gitlab` for GitLab CI.

```
jsat ci-setup [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--provider`, `-p` | `github` | CI provider: `github` or `gitlab` |
| `--output`, `-o` | provider default | Output path for the workflow file |

```bash
jsat ci-setup                        # writes .github/workflows/jsat.yml
jsat ci-setup --provider gitlab      # writes .gitlab-ci.yml
```

The generated workflow runs `jsat index` and `jsat doctor --json` on every push and pull request. It uses the `ci` profile automatically (no AI calls, JSON logs, memory cache).

---

## 7. Prompt Optimizer (`jsat prompt`)

Optimize any query through a 7-stage pipeline before sending it to the AI. Auto-optimization runs on every shell message by default.

### `jsat prompt <query>`

Print the optimized prompt without sending it to the AI. Use this to inspect what would be sent.

```bash
jsat prompt "improve the retry logic"
jsat prompt "explain the auth flow"
```

---

### `jsat prompt --send`

Optimize the query and send it to the configured AI provider.

```bash
jsat prompt --send "improve the retry logic"
jsat prompt --send "write a test for refund()"
```

---

### `jsat prompt --diff`

Show a side-by-side comparison of the raw input and the full optimized prompt (with injected context, constraints, few-shot examples, and model formatting).

```bash
jsat prompt --diff "improve the retry logic"
```

---

### Flags

| Flag | Values | Description |
|------|--------|-------------|
| `--send` | — | Optimize and send to the AI |
| `--diff` | — | Show raw input vs optimized prompt side by side |
| `--format`, `-f` | `code`, `plan`, `json`, `prose` | Override output format for this prompt |
| `--ai` | `claude`, `gpt`, `ollama` | Override AI provider for this prompt |
| `--cot` | — | Append chain-of-thought instructions to the prompt |
| `--verbose` | — | Print a stage-by-stage breakdown of the pipeline |
| `--dry-run` | — | Inspect the full optimized prompt without sending or printing the AI response |
| `--no-context` | — | Skip graph context injection (stages 2) |
| `--no-examples` | — | Skip few-shot example injection (stage 4) |

```bash
jsat prompt --send --format code --ai claude "write a test for refund()"
jsat prompt --send --cot --verbose "debug why checkout is returning 500"
jsat prompt --dry-run --no-context "what does the payment service do?"
```

---

### Shell commands (`opt`)

Inside the JSAT shell, use the `opt` command to control optimization:

```
opt on        # enable auto-optimization for all messages (default)
opt off       # disable for the current session
opt show      # show raw input vs full optimized prompt for the last message
opt history   # browse past optimization diffs
```

---

## 8. JSAT Crack (`jsat crack`)

Run a multi-agent war room on a complex engineering decision.

```
jsat crack TASK [OPTIONS]
```

| Argument / Flag | Default | Description |
|----------------|---------|-------------|
| `TASK` | (required) | The complex engineering question to discuss |
| `--roles`, `-r` | all 6 | Comma-separated subset: `architect,security,implementer,tester,skeptic` |
| `--rounds`, `-n` | `3` | Number of discussion rounds |
| `--file`, `-f` | auto | Write output to file (default: `.jsat/crack/<slug>.md`) |
| `--repo` | `.` | Repository root |

```bash
jsat crack "redesign payment retry system"
jsat crack --roles architect,security "migrate users table to UUID"
jsat crack --rounds 2 "sync vs async for webhook processing"
jsat crack --file design.md "how should we handle idempotency keys"
```

**Agents (run in parallel, respond to each other across rounds):**
- 🏛 `architect` — system design, patterns, scalability
- 🔒 `security` — threat model, auth, idempotency
- ⚙️ `implementer` — current code analysis, effort estimate
- 🧪 `tester` — edge cases, coverage gaps, testability
- 😈 `skeptic` — challenges every proposal
- 🎯 `moderator` — synthesises consensus and action plan (always last)

Output is saved to `.jsat/crack/<slug>.md`.

Works without AI configured (returns structural offline placeholders).

---

## 8b. JSAT Short (`jsat short`)

Get the shortest possible correct answer to any question.

```
jsat short QUESTION [OPTIONS]
```

| Argument / Flag | Default | Description |
|----------------|---------|-------------|
| `QUESTION` | (required) | Question to ask |
| `--words`, `-w` | `50` | Maximum word count |
| `--one-line`, `-1` | false | Exactly one sentence |
| `--repo`, `-r` | `.` | Repository root |

```bash
jsat short "what does process_refund do"
jsat short --one-line "is PaymentService.process async"
jsat short --words 10 "explain the retry logic"
```

In the JSAT shell: `short <question>`

---

## 10. Token Optimizer (`jsat tokens`)

Count tokens, check model budget, and compress text for AI prompts. All offline — zero LLM calls.

```
jsat tokens [TEXT] [OPTIONS]
```

| Argument / Flag | Default | Description |
|----------------|---------|-------------|
| `TEXT` | — | Inline text to analyze |
| `--file`, `-f` | — | Read from file instead |
| `--model`, `-m` | — | Model for budget check: `claude-cli`, `gpt-4o`, `llama3.2`, etc. |
| `--compress`, `-c` | false | Apply compression strategies and print savings |
| `--strip-comments` | false | Also remove code comment lines |
| `--no-dedup` | false | Skip semantic deduplication |
| `--target`, `-t` | — | Explicit token ceiling for compression |
| `--verbose`, `-v` | false | Show per-section token breakdown |

```bash
# Count tokens
jsat tokens "explain the payment service"
jsat tokens --file README.md

# Budget check
jsat tokens --file context.py --model gpt-4o
jsat tokens --file context.py --model claude-cli

# Compress
jsat tokens --file context.py --compress
jsat tokens --file context.py --compress --target 4000 --strip-comments

# Pipe stdin
cat big_file.py | jsat tokens --model claude-cli --compress
```

---

## 8b. Maintenance Commands

### `jsat clean`

Remove cached data from `.jsat/` to free disk space or force a fresh start.

```
jsat clean [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--cache` | Delete `.jsat/cache/` |
| `--graph` | Delete `.jsat/graph/` (destroys the index) |
| `--vectors` | Delete `.jsat/vectors/` |
| `--history` | Delete `.jsat/prompt-history.jsonl` |
| `--all` | Delete all of the above |

```bash
jsat clean --cache          # free cache only
jsat clean --all            # full reset
```

### `jsat update`

Self-upgrade JSAT via pip.

```
jsat update [--pre]
```

| Flag | Description |
|------|-------------|
| `--pre` | Include pre-release versions |

### `jsat knowledge-ingest`

Bulk-ingest markdown files (CLAUDE.md, ADRs, runbooks) into the knowledge base.

```
jsat knowledge-ingest PATH [OPTIONS]
```

| Argument / Flag | Default | Description |
|----------------|---------|-------------|
| `PATH` | (required) | Directory to scan |
| `--pattern` | `**/*.md` | Glob pattern for files to ingest |
| `--category` | auto | Override category (adr, runbook, readme) |
| `--dry-run` | false | Print what would be ingested, don't write |

```bash
jsat knowledge-ingest docs/             # ingest all .md files
jsat knowledge-ingest . --pattern "**/*.md" --dry-run
```

---

## 11. Export and Import

### `jsat export`

Export the current index to a portable zip archive.

```
jsat export OUTPUT [OPTIONS]
```

| Argument / Flag | Default | Description |
|----------------|---------|-------------|
| `OUTPUT` | (required) | Output path, e.g. `backup.jsat.zip` |
| `--compress`, `-z` | `6` | Compression level 0-9 (0 = no compression, 9 = max) |

```bash
jsat export backup.jsat.zip
jsat export backup.jsat.zip --compress 9
```

---

### `jsat import`

Restore an index from an exported archive.

```
jsat import ARCHIVE [OPTIONS]
```

| Argument / Flag | Default | Description |
|----------------|---------|-------------|
| `ARCHIVE` | (required) | Path to `.jsat.zip` archive |
| `--migrate` | false | Apply schema migrations if version differs |

```bash
jsat import backup.jsat.zip
```

---

## 12. Remove Command

### `jsat remove`

Remove all JSAT artifacts from the current repository. Interactive confirmation by default.

```
jsat remove [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--yes`, `-y` | false | Skip confirmation prompt |
| `--keep-config` | false | Keep `.jsat/config.yaml` (preserve settings) |

Removes:

- `.jsat/graph/` — codebase graph database
- `.jsat/vectors/` — embedding vectors
- `.jsat/cache/` — semantic cache
- `.jsat/system-profile.json`
- `.jsat/config.yaml` (unless `--keep-config`)
- `.claude/commands/jsat-*.md` — skill files
- `mcpServers.jsat` entry in `.claude/settings.json`

Does not touch your source code, git history, or other Claude configuration.

```bash
jsat remove
jsat remove --yes              # skip confirmation
jsat remove --keep-config      # preserve config.yaml
```

---

## 13. Skills Commands (`jsat skills`)

### `jsat skills list`

List installed JSAT skills (YAML manifests in the skills directory).

```bash
jsat skills list
```

---

### `jsat skills run`

Run a named skill.

```
jsat skills run NAME [OPTIONS]
```

| Argument / Flag | Description |
|----------------|-------------|
| `NAME` | Skill name |
| `--args`, `-a` | `key=val` pairs (repeatable) |

```bash
jsat skills run my-skill
jsat skills run my-skill --args target=src/api.py --args depth=3
```

---

## 14. MCP Server (Internal)

### `jsat mcp-server`

Start the JSAT MCP server on stdin/stdout. This is invoked automatically by Claude Code and Cursor when JSAT is connected. You do not normally run this directly.

```
jsat mcp-server [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repository root to serve |
| `--verbose`, `-v` | false | Enable debug logging |

If you need to test the MCP server manually:

```bash
jsat mcp-server --repo /path/to/project --verbose
```

The server speaks JSON-RPC 2.0 over stdin/stdout. It starts immediately and loads JSAT lazily to avoid startup timeout errors in Claude Code.

---

## Universal Flags (Claude Code slash commands)

Two flags work on every `/jsat` command — strip them before routing and pass to every tool call:

| Flag | Behavior | Passes to tool |
|------|----------|----------------|
| `timeout=<N>` | Soft budget N s; hard kill at 5×N s | `_budget=N` |
| `dashboard=true` | Open `localhost:7432/jsat/dashboard/<command>` — one persistent tab per command, collapsible tree of all tool calls. Tab stays open until session done. Browse all sessions at `localhost:7432/jsat/dashboard`. | `_dashboard=True` + `_dashboard_session=<command>` |

```bash
/jsat blast-radius timeout=120 src/payment/
/jsat crack dashboard=true redesign the auth flow
# → opens localhost:7432/jsat/dashboard/crack

/jsat magic timeout=180 dashboard=true investigate the auth flow
# → opens localhost:7432/jsat/dashboard/magic
```

---

## Environment Variables

| Variable | Used by |
|---------|---------|
| `JSAT_CONFIG` | Override config file path |
| `JSAT_DASHBOARD_PORT` | Override live dashboard port (default `7432`) |
| `ANTHROPIC_API_KEY` | Anthropic API provider |
| `OPENAI_API_KEY` | OpenAI provider |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini provider |
| `NEO4J_PASSWORD` | Neo4j graph backend |
| `QDRANT_API_KEY` | Qdrant vector store |
| `JSAT_MCP_TOKEN` | MCP server auth token (if `mcp.auth: true`) |
| `CI` | If `true`/`1`/`yes`, forces CI profile (no embeddings, memory cache) |
