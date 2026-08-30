# Claude Code through Ollama

Use this route when Claude Code is the coding harness but Ollama supplies the selected local or
cloud model. This is separate from native Claude and from JSAT's direct Ollama provider.

## Prerequisites and connect

Install Ollama and sign in when using cloud models. Ollama's launcher owns any harness setup it
requires. Then connect JSAT to Claude's MCP configuration:

```bash
pip install jsat
cd /path/to/project
jsat index .
jsat connect ollama tool=claude
```

Bare `jsat connect ollama` connects every supported Ollama-launched harness. Naming `claude`
keeps this setup explicit.

## Select and launch a model

Interactive selector:

```bash
jsat ollama --tool claude
```

Exact local model:

```bash
ollama pull qwen3.5
jsat ollama --tool claude --model qwen3.5
```

Exact cloud model:

```bash
ollama signin
jsat ollama --tool claude --model gemma4:31b-cloud
```

Use `--yes` with `--model` to skip Ollama's selector. Arguments after `--` go to Claude:

```bash
jsat ollama --tool claude -m gemma4:31b-cloud --yes -- -p "summarize this repo"
```

The chosen model applies to this launched Claude process. It does not overwrite
`.jsat/config.yaml` and does not require a second pull. Local models must exist in Ollama;
cloud models require sign-in instead of a pull.

## Use and verify JSAT

Inside the launched Claude session:

```text
/jsat status
/jsat query what calls the payment adapter?
/jsat-help
```

Ask Claude to call `jsat__get_index_status`. Also check the Claude UI/status line to verify the
Ollama-selected model. Both checks are required: one proves MCP, the other proves model routing.

## Managed lifecycle

```bash
jsat start claude --via ollama --model qwen3.5
jsat ps
jsat restart claude
jsat stop claude
jsat resume claude
jsat resume claude --session SESSION_ID
```

The restart record preserves route, model, and repository. Pass new values explicitly to change
them. `jsat start` without a target starts all three managed clients, so name `claude` when you
want only this route.

## Troubleshooting

- If `/jsat` exists but MCP calls fail, reconnect and fully restart the launched Claude process.
- If Ollama reports a missing local model, pull the exact model/tag shown in the command.
- If a cloud model fails, run `ollama signin`; do not replace it with an unrelated local model.
- If errors mention the OpenAI provider with an Ollama model such as `llama3.2`, routing is
  mixed. Launch through this command or configure `jsat ai use ollama`, depending on which
  execution path you intended.

For Claude's own account models, use [native Claude](claude.md).
