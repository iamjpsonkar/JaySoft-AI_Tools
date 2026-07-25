# Claude Integration

JSAT integrates with Claude Code as an MCP (Model Context Protocol) server. After connecting, Claude can call JSAT tools automatically during a conversation, and you get seven `/jsat-*` slash commands.

## How It Works

```
Claude Code  ←→  MCP (stdin/stdout JSON-RPC)  ←→  jsat mcp-server  ←→  Graph DB
```

When you run `jsat connect claude`, JSAT:

1. Writes an MCP server entry into `.claude/settings.json` (or `~/.claude/settings.json` for global scope)
2. Installs seven `/jsat-*` slash command skill files in `.claude/commands/`

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

Connect the MCP server only, skip installing `/jsat-*` skill files:

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

Seven `/jsat-*` slash commands are installed into Claude Code when you run `jsat connect claude`.

### `/jsat-query`

Ask any natural language question about the indexed codebase.

```
/jsat-query what does this project do?
/jsat-query which services call the payments endpoint?
/jsat-query where is user authentication handled?
/jsat-query what writes to the orders table?
```

Claude calls the `jsat__query` MCP tool, which searches the codebase graph and returns a sourced answer.

### `/jsat-blast-radius`

Trace the downstream impact of changing a file or symbol. Groups results by severity.

```
/jsat-blast-radius src/payment/refund.py
/jsat-blast-radius checkout_service.process_order
/jsat-blast-radius
```

Claude calls `jsat__blast_radius`. Results are grouped as:

- **breaking** — callers that will fail if the interface changes
- **degraded** — callers that may silently misbehave
- **warning** — indirect dependencies worth checking
- **safe** — no meaningful coupling

### `/jsat-security`

Run an OWASP-style security scan on the codebase. Pass a path to scope the scan.

```
/jsat-security
/jsat-security src/api/
/jsat-security src/auth/login.py
```

Claude calls `jsat__security_review`. Findings are ranked Critical → High → Medium → Low.

Requires `pip install jsat[standard]` for the full Semgrep-backed scan. Without it, the graph-based scan runs (checks auth coverage, secret detection, data flow).

### `/jsat-incident`

Investigate a production incident. JSAT searches recent git history, correlates commits to the affected services, and returns ranked root-cause hypotheses.

```
/jsat-incident 500 errors on checkout since 14:00
/jsat-incident payment gateway timeouts starting after the 3pm deploy
/jsat-incident OOM on worker-3 pods since yesterday
```

Claude calls `jsat__investigate_incident`. Output includes hypotheses with scores, commit evidence, and recommended actions.

### `/jsat-index`

Build or refresh the JSAT codebase graph from inside Claude Code.

```
/jsat-index
/jsat-index src/new-service/
```

Claude calls `jsat__index_repo` and reports the node and edge counts.

### `/jsat-status`

Show current graph statistics: node count, edge count, and index freshness.

```
/jsat-status
```

Claude calls `jsat__get_index_status`.

### `/jsat-doctor`

Run a system health check without leaving Claude Code.

```
/jsat-doctor
```

Claude calls `jsat__get_jsat_version` and `jsat__get_index_status` and shows version, system profile, and index health.

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
