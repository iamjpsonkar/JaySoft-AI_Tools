# Native Claude Code

Use this route when the `claude` executable is installed and Claude Code should own sign-in,
the conversation, and model selection. JSAT supplies MCP tools plus `/jsat` and `/jsat-help`.

## Prerequisites and connect

Install Claude Code using Anthropic's supported installer, complete its sign-in, then:

```bash
pip install jsat
cd /path/to/project
jsat index .
jsat connect claude --global
```

Use `jsat connect claude` instead for project scope. Global setup writes under `~/.claude/`;
project setup writes `.claude/settings.json`, `.claude/commands/`, and a marked guidance block
in `CLAUDE.md`. Use `--no-claude-md` to omit that block or `--no-skills` for MCP only.

## Start and select a model

```bash
jsat claude --repo .
# equivalent managed route
jsat start claude --via native --repo .
```

Claude Code selects its model through Claude's own model command/account. No Ollama model is
pulled or selected. To make JSAT's internal LLM-backed tools use the Claude CLI too:

```bash
jsat ai use claude_cli
jsat ai test
```

## Use and verify JSAT

Inside Claude Code:

```text
/jsat status
/jsat query what is the request path for checkout?
/jsat blast-radius src/payments/service.py
/jsat-help crack
```

You can also ask Claude to call `jsat__get_index_status`. If `/jsat` exists but the MCP call
does not, the command files loaded but the MCP server did not; reconnect and restart Claude.

## Lifecycle

```bash
jsat ps
jsat restart claude
jsat stop claude
jsat resume claude
jsat resume claude --session SESSION_ID
```

Direct launcher equivalents are `jsat claude --continue` and
`jsat claude --resume SESSION_ID`.

## Troubleshooting and removal

- After install or reconnect, close every existing Claude process and start a new one.
- Run `jsat connect list` and `jsat doctor` if MCP tools are absent.
- `/jsat` and MCP are separate surfaces. A visible slash command does not prove the MCP server
  started; verify with `jsat__get_index_status`.
- Do not put API keys in the generated MCP file. Native Claude uses its own sign-in.

```bash
jsat disconnect claude --scope all
```

For local or Ollama Cloud models inside Claude, use [Claude through Ollama](ollama-claude.md).
