# Codex through Ollama

Use this route when Codex is the coding harness and Ollama supplies its local or cloud model.
It is distinct from native Codex authentication/model selection.

## Connect and launch

```bash
pip install jsat
cd /path/to/project
jsat index .
jsat connect ollama tool=codex
jsat ollama --tool codex                 # interactive selector
```

Choose an exact local or cloud model when needed:

```bash
ollama pull qwen3.5
jsat ollama --tool codex -m qwen3.5

ollama signin
jsat ollama --tool codex -m gemma4:31b-cloud
```

The chosen model belongs to the launched process and does not change JSAT's direct provider.
Local models need one pull for the exact tag; cloud models need sign-in and no pull.

## Use and verify

Inside Codex:

```text
$jsat status
$jsat query find the checkout entry point
```

Ask Codex to call `jsat__get_index_status`, then verify its displayed model. This checks MCP and
model routing independently.

## Managed lifecycle

```bash
jsat start codex --via ollama --model qwen3.5
jsat ps
jsat restart codex
jsat stop codex
jsat resume codex
jsat resume codex --session SESSION_ID
```

## Troubleshooting

If an error reports an Ollama model with `provider: openai`, the provider/model pair is mixed.
Use this launcher for Ollama-supplied Codex, [native Codex](codex.md) for Codex-owned models, or
`jsat ai use ollama --model MODEL` for direct JSAT calls.
