# Native Codex

Use this route when the `codex` executable is installed and you want Codex—not Ollama—to own
authentication, the conversation, and model selection. JSAT adds its MCP server and global
`$jsat` skill; it does not create project-local Codex files.

## Prerequisites and connect

```bash
pip install jsat
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex                         # complete sign-in, then exit
cd /path/to/project
jsat index .
jsat connect codex
```

The connection writes `~/.codex/config.toml` and `~/.codex/skills/jsat/SKILL.md`. Restart a
Codex process that was already open.

## Start and select a model

```bash
jsat codex --repo .
# equivalent managed route
jsat start codex --via native --repo .
```

Codex selects its model using its own UI/configuration. Do not pass an Ollama model to this
route. If JSAT's internal LLM-backed tools should also call native Codex, configure that
separately:

```bash
jsat ai use codex-cli
jsat ai test
```

## Use and verify JSAT

Inside Codex:

```text
$jsat status
$jsat query what is the request path for checkout?
$jsat blast-radius src/payments/service.py
```

Or ask: `Use jsat__get_index_status and tell me the node and edge counts.` A successful call
proves MCP is active. On the host, `jsat connect list` confirms the saved connection.

## Lifecycle

```bash
jsat ps
jsat restart codex
jsat stop codex
jsat resume codex
jsat resume codex --session SESSION_ID
```

`jsat codex resume SESSION_ID` is also forwarded directly to Codex. `jsat session resume` is
different: it resumes an interrupted JSAT workflow such as `crack` or `magic`.

## Troubleshooting and removal

- If `$jsat` is missing, rerun `jsat connect codex`, then restart Codex completely.
- If MCP is missing, inspect `~/.codex/config.toml` and run `jsat doctor`.
- If an error shows `model: llama3.2` with `provider: openai`, the model/provider pair is
  misrouted. Select `codex-cli` for native Codex or `ollama` for `llama3.2`; do not combine
  an Ollama model name with the OpenAI provider.
- If Codex is not installed, use an [Ollama-launched client](ollama-codex.md) or install Codex.

```bash
jsat disconnect codex
```
