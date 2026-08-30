# Direct Ollama: local JSAT shell

Use this route when JSAT itself should send LLM-backed tool requests to an Ollama model. There
is no Claude, Codex, or OpenCode harness in this path.

## Prerequisites and model setup

```bash
pip install 'jsat[local]'
ollama serve                  # keep running in another terminal
ollama pull qwen3.5           # local models only, once per model/tag
ollama list
```

Model names are exact. `qwen3.5` matches `qwen3.5:latest`, but it does not match another tag.

## Configure, start, and verify

```bash
cd /path/to/project
jsat index .
jsat ai use ollama --model qwen3.5
jsat ai status
jsat ai test
jsat ollama --model qwen3.5
```

Sample shell queries:

```text
what does this project do?
blast-radius src/payments/service.py
security-review src/auth/
```

`jsat ai use ollama` persists the direct provider choice. `jsat ollama --model ...` opens a
JSAT shell for that provider. Neither command launches a coding client.

## Local versus cloud

- Local model such as `qwen3.5`: run `ollama pull` and keep `ollama serve` reachable.
- Cloud model such as `gemma4:31b-cloud`: run `ollama signin`; do not pull it.

For a cloud model used directly by JSAT:

```bash
ollama signin
jsat ai use ollama --model gemma4:31b-cloud
jsat ai test
```

## Lifecycle and isolation

The top-level `jsat start|stop|restart|resume` commands manage Claude, Codex, and OpenCode
processes; they do not manage `ollama serve` or a direct JSAT shell. Stop the shell normally and
manage the Ollama service using the mechanism provided by your operating system.

To switch away without affecting any connected coding client:

```bash
jsat ai use claude_cli       # or codex-cli, opencode, openai, anthropic
jsat ai test
```

## Troubleshooting

- `model not found at http://localhost:11434`: the configured local model is not installed in
  the Ollama instance at that URL. Pull the exact tag or select a model shown by `ollama list`.
- A cloud-suffixed model should prompt for/sign in to Ollama Cloud, not be downloaded locally.
- If `ollama launch opencode` already uses a model successfully, that proves the launched
  OpenCode route works; it does not prove JSAT's direct Ollama provider has the same model
  configured. Run `jsat ai status` and `jsat ai test` for this route.
