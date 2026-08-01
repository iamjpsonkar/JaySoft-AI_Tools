# Claude Integration

JSAT integrates with Claude Code as an MCP (Model Context Protocol) server. After connecting, Claude can call JSAT tools automatically during a conversation, and you get the `/jsat` slash command with 39 subcommands.

## How It Works

```
Claude Code  ←→  MCP (stdin/stdout JSON-RPC)  ←→  jsat mcp-server  ←→  Graph DB
```

When you run `jsat connect claude`, JSAT:

1. Writes an MCP server entry into `.claude/settings.json` (or `~/.claude/settings.json` for global scope)
2. Installs the `/jsat` dispatcher skill file (`~/.claude/commands/jsat.md`) containing all 39 subcommands
3. Installs `/jsat-help` as a standalone skill file (`~/.claude/commands/jsat-help.md`)

Claude Code reads these on startup, starts the `jsat mcp-server` process, and makes all JSAT tools available during your session.

---

## Connecting

### Project scope (default)

Applies only to the current repository. The MCP config goes into `.claude/settings.json`:

```bash
jsat connect claude
```

### Global scope

Applies to every Claude Code session on your machine. The MCP config goes into `~/.claude/settings.json`:

```bash
jsat connect claude --scope global
```

### Without slash commands

Connect the MCP server only, skip installing `/jsat` and `/jsat-help` skill files:

```bash
jsat connect claude --no-skills
```

### Show the written config

Print the MCP entry that was written:

```bash
jsat connect claude --show
```

### List active connections

```bash
jsat connect list
```

**After any connect command, restart Claude Code to activate the tools.**

---

## Slash Commands

A single `/jsat` dispatcher is installed into Claude Code when you run `jsat connect claude`. It routes to 39 subcommands, organized into layers:

```
/jsat <subcommand> [args]
```

### Quick reference

| Layer | Commands |
|-------|----------|
| **Context** | `status`, `list-services`, `list-endpoints`, `doctor` |
| **Discover** | `query`, `find-function`, `find-class`, `trace`, `smart`, `short`, `recent` |
| **Analyze** | `blast-radius`, `security`, `test-gaps`, `coverage`, `contract`, `cohesion`, `migration`, `incident` |
| **Plan** | `lazy`, `plan`, `think`, `crack`, `decide`, `knowledge` |
| **Execute** | `review`, `prompt`, `sprint` |
| **Orchestrate** | `magic`, `aw` |
| **Record** | `decide log`, `reflect`, `knowledge-add`, `runbook` |
| **Tokens** | `tokens`, `token-budget`, `prompt-diff`, `prompt-rewrite` |
| **Index** | `index`, `ithinking` |

> **`/jsat-help`** is a separate command (not a subcommand of `/jsat`): `/jsat-help` lists all 39 with one-liners; `/jsat-help <command>` shows full flags and examples for that command.

### Common examples

```bash
# Understand
/jsat query what does the payment service do?
/jsat find-function process_refund
/jsat trace PaymentService.charge --depth 3
/jsat short what does validate_cart return?

# Analyze
/jsat blast-radius src/payment/service.py
/jsat security src/auth/
/jsat test-gaps src/payment/
/jsat cohesion --threshold 600

# Plan & decide
/jsat plan add idempotency keys to the payment mutation
/jsat lazy add a retry wrapper for HTTP calls
/jsat decide log --impact h Chose PostgreSQL for ACID compliance on payments

# Deep analysis
/jsat crack redesign the payment retry system
/jsat crack --phases 3 add rate limiting to checkout
/jsat crack --continue          # resume interrupted session

# Full pipeline
/jsat prompt what calls process_refund and what do they pass?
/jsat sprint add rate limiting to the checkout API
/jsat magic --depth deep investigate and fix the auth flow

# Orchestrate everything
/jsat magic update and improve this project
/jsat magic --preview find all security issues    # plan only, no execution
/jsat magic --continue                            # resume interrupted session
```

### Big skills: session files and auto-execute

`magic`, `crack`, `sprint`, and `prompt` write session files to `~/.jsat/sessions/` and execute their recommendations automatically after synthesis. Pass `--continue` to resume any interrupted session. See [Session Files & Auto-Execute](../README.md#session-files--auto-execute) for details.

### `/jsat-prompt-diff`

Show the raw input you typed next to the full optimized prompt that was actually sent to the AI:

```
/jsat prompt-diff improve the retry logic
/jsat prompt-diff what does the checkout service do?
```

Claude calls `jsat__prompt_diff`. Output is two labelled panels: **Raw** and **Optimized**.

---

## Prompt Optimizer

Every `jsat__query` call — and every message you type in the JSAT shell — is passed through the 7-stage prompt optimization pipeline before reaching the AI. The pipeline classifies the task, injects codebase context from the graph, pulls constraints from the knowledge base, selects few-shot examples from prompt history, applies output formatting, adds model-specific wrappers (XML for Claude, Markdown for GPT), and compresses to fit within the token budget.

You do not need to do anything to enable this. Auto-optimization is on by default.

To see what was sent to the AI after the last message:
```
/jsat-prompt-diff <your query>
```

To pre-inspect before sending:
```bash
jsat prompt --diff "your query"
```

MCP tools for programmatic use:

| Tool | Description |
|------|-------------|
| `jsat__prompt_optimize` | Return the optimized prompt for a query without sending it |
| `jsat__prompt_diff` | Return raw input and optimized prompt as a structured diff |

---

## MCP Server Authentication

The MCP server runs locally over stdin/stdout and defaults to **open access with a startup warning** when no auth env vars are set. `jsat connect claude` automatically sets `JSAT_MCP_ALLOW_INSECURE=1` in the server environment to silence the warning for local dev.

| Env var | Effect |
|---------|--------|
| *(none)* | Open access — all tools available, warning logged at startup |
| `JSAT_MCP_ALLOW_INSECURE=1` | Open access, warning silenced (set automatically by `jsat connect claude`) |
| `JSAT_MCP_TOKEN=<secret>` | Enforce single-token auth — callers must pass this token |
| `JSAT_MCP_TOKEN_ROLES=<json>` | RBAC: `{"token": "role"}` — roles are `admin`, `developer`, `viewer` |

To enforce auth, export `JSAT_MCP_TOKEN` or `JSAT_MCP_TOKEN_ROLES` in your shell before starting Claude Code.

---

## MCP Tools

In addition to the slash commands, Claude can call JSAT tools directly during a conversation whenever the context suggests they would be useful. The tools are namespaced `jsat__*`.

### Index and graph tools

| Tool | Description |
|------|-------------|
| `jsat__index_repo` | Build or refresh the codebase graph |
| `jsat__get_function` | Get details of a function by name or `file:line` |
| `jsat__get_class` | Get details of a class |
| `jsat__list_services` | List all services in the indexed repo |
| `jsat__list_endpoints` | List API endpoints, optionally filtered by service or HTTP method |
| `jsat__list_tables` | List database tables |
| `jsat__trace_call_chain` | Trace the call chain from one symbol to another |
| `jsat__get_data_flow` | Trace how data flows through the system |

### Blast radius tools

| Tool | Description |
|------|-------------|
| `jsat__blast_radius_file` | Blast radius for a file |
| `jsat__blast_radius_diff` | Blast radius from a raw git diff |
| `jsat__blast_radius_symbol` | Blast radius for a single symbol |
| `jsat__blast_radius_topic` | Blast radius of a Kafka topic change |
| `jsat__get_consumers` | List consumers of an endpoint or topic |

### Test tools

| Tool | Description |
|------|-------------|
| `jsat__get_test_gaps` | Find uncovered code paths |
| `jsat__get_behavioral_coverage` | Map behaviors to test coverage |
| `jsat__list_untested_paths` | Top-N highest-risk untested paths |
| `jsat__generate_unit_test` | Generate a unit test for a function |
| `jsat__generate_integration_test` | Generate an integration test for an endpoint |
| `jsat__generate_contract_test` | Generate a contract test between two services |

### Security tools

| Tool | Description |
|------|-------------|
| `jsat__security_scan_file` | OWASP scan a single file |
| `jsat__get_auth_coverage` | Endpoints missing auth middleware |
| `jsat__list_secrets` | Find hardcoded secrets (key names only, values redacted) |
| `jsat__get_dependency_cves` | CVEs in dependencies above a CVSS threshold |
| `jsat__trace_data_flow` | Trace user input for injection risks |

### API contract tools

| Tool | Description |
|------|-------------|
| `jsat__get_api_diff` | Diff OpenAPI/AsyncAPI specs between branches |
| `jsat__check_breaking_changes` | Classify API changes as breaking or non-breaking |
| `jsat__get_consumers_of_endpoint` | All callers of a specific endpoint |
| `jsat__get_compat_score` | 0-100 backward compatibility score |

### Incident tools

| Tool | Description |
|------|-------------|
| `jsat__investigate_incident` | Ranked root-cause hypotheses for an incident |
| `jsat__get_hypotheses` | Get current ranked hypotheses |
| `jsat__get_recent_changes` | Recent commits for affected services |
| `jsat__generate_runbook` | Generate a runbook from a hypothesis |

### Knowledge tools

| Tool | Description |
|------|-------------|
| `jsat__knowledge_query` | Answer a question from the knowledge base |
| `jsat__knowledge_add` | Add a note to the knowledge base |
| `jsat__knowledge_search` | Semantic search over knowledge base |
| `jsat__knowledge_list` | List knowledge base entries |
| `jsat__knowledge_flag_stale` | Mark an entry as potentially outdated |

### Meta tools

| Tool | Description |
|------|-------------|
| `jsat__get_index_status` | Index node/edge counts and freshness |
| `jsat__get_jsat_version` | JSAT version, schema version, active AI provider |

---

## Disconnecting

Remove JSAT from the current project's Claude Code config:

```bash
jsat disconnect claude
```

Remove from global config:

```bash
jsat disconnect claude --scope global
```

Remove from both:

```bash
jsat disconnect claude --scope all
```

Keep the skill files but remove the MCP server entry:

```bash
jsat disconnect claude --keep-skills
```

Restart Claude Code after disconnecting.

---

## Troubleshooting

### Tools show "not available" or MCP error

1. Run `jsat connect list` to verify the config was written.
2. Check that the `jsat` binary is on PATH: `which jsat`
3. Restart Claude Code completely (not just a new tab).
4. Run `jsat doctor` to check the graph and AI provider health.

### Slash commands not appearing

The skill files must exist in `.claude/commands/` (project scope) or `~/.claude/commands/` (global scope). Check:

```bash
ls .claude/commands/jsat-*.md
```

If missing, re-run `jsat connect claude`.

### MCP server starts slowly

The MCP server is designed to start immediately and load JSAT lazily. If Claude Code times out, your system may be extremely slow on startup. Run `jsat doctor --json` and look at service ping times. Disable unused services in `.jsat/config.yaml` (set `neo4j.remote_uri: null`, etc.).

### Config path reference

| Scope | Settings file | Commands directory |
|-------|--------------|-------------------|
| project | `.claude/settings.json` | `.claude/commands/` |
| global | `~/.claude/settings.json` | `~/.claude/commands/` |

The MCP entry written into settings looks like:

```json
{
  "mcpServers": {
    "jsat": {
      "command": "/path/to/jsat",
      "args": ["mcp-server", "--repo", "/absolute/path/to/project"],
      "env": {}
    }
  }
}
```
