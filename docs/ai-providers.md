# AI Providers

JSAT supports six AI backends. The right one is selected automatically based on what is available, but you can override it at any time.

## Provider Overview



| Provider | Switch command | Cost | Needs |
|----------|---------------|------|-------|
| Claude Code CLI | `jsat ai use claude_cli` | Free tier | `claude` binary |
| Bob Shell CLI | `jsat ai use bob_cli` | Free tier | `bob` binary |
| Anthropic API | `jsat ai use anthropic` | Paid | `ANTHROPIC_API_KEY` |
| OpenAI | `jsat ai use openai` | Paid | `OPENAI_API_KEY` |
| Google Gemini | `jsat ai use gemini` | Paid | `GEMINI_API_KEY` |
| Ollama (local) | `jsat ai use ollama` | Free | `ollama serve` + model |
| LM Studio (local) | `jsat ai use lmstudio` | Free | LM Studio running |

Add `--global` to any `jsat ai use` command to write the setting to `~/.jsat/config.yaml` (applies to all projects on this machine) instead of the per-repo `.jsat/config.yaml`.

---

## Check What Is Available

```bash
jsat ai status
```

Example output:

```
        JSAT AI Providers
┌──────────────────────┬──────────────┬──────┬────────────────────────┐
│ Provider             │ Status       │ Free │ Notes / Models         │
├──────────────────────┼──────────────┼──────┼────────────────────────┤
│ claude (active)      │ ✓ available  │ yes  │ claude binary found     │
│ anthropic            │ ✓ key set    │ no   │ claude-sonnet-4-6      │
│ ollama               │ ✓ running    │ yes  │ llama3.2, phi3:mini    │
│ openai               │ ✗ no key     │ no   │ set OPENAI_API_KEY     │
│ lmstudio             │ ✗ not running│ yes  │ not running            │
└──────────────────────┴──────────────┴──────┴────────────────────────┘

Currently configured: claude_cli / claude-sonnet-4-6
```

---

## Claude Code CLI (Recommended)

The Claude Code CLI (`claude` binary) is the default provider when it is installed. No API key is required — JSAT calls `claude` as a subprocess.

### Install

```bash
# Follow instructions at claude.ai/code
# Verify:
which claude
claude --version
```

### Activate

JSAT auto-detects the `claude` binary. No configuration needed. To set it explicitly:

```bash
jsat ai use claude_cli           # per-repo
jsat ai use claude_cli --global  # all projects on this machine
```

This sets:

```yaml
ai:
  provider: claude_cli
  model: claude-sonnet-4-6
```

### Verify

```bash
jsat ai test
```

### Inside the shell

```
> switch claude-cli
```

---

## Anthropic API


---

## Bob Shell CLI

Bob Shell is an IBM AI-powered terminal assistant that provides interactive coding assistance with multiple modes.

### Install

```bash
npm install -g @ibm/bob-shell
# Verify:
which bob
bob --version
```

### Activate

JSAT auto-detects the `bob` binary. No configuration needed. To set it explicitly:

```bash
jsat ai use bob
```

This sets:

```yaml
ai:
  provider: bob_cli
  model: premium
  chat_mode: advanced
```

### Available Modes

Bob Shell supports four interaction modes:

- `plan` — Planning and design mode
- `code` — Code implementation mode  
- `advanced` — Advanced code mode with more tools (default)
- `ask` — Question and answer mode

### Verify

```bash
jsat ai test
```

### Inside the shell

```
> switch bob
> switch bob-cli
```

### Open a Bob Shell session directly

```bash
jsat bob
jsat bob --mode advanced
jsat bob --resume <session-id>
```



Use the Anthropic API directly (requires a paid API key).

### Install

```bash
pip install jsat[anthropic]
# or: pip install anthropic
```

### Set API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Add to ~/.zshrc or ~/.bashrc to persist
```

### Activate

```bash
jsat ai use anthropic           # per-repo
jsat ai use anthropic --global  # all projects on this machine
```

Available models: `claude-sonnet-4-6` (default), `claude-haiku-4-5-20251001`, `claude-opus-4-8`.

Use a specific model:

```bash
jsat ai use anthropic --model claude-haiku-4-5-20251001
```

### Verify

```bash
jsat ai test "say hello"
```

### Inside the shell

```
> switch claude-api
> switch haiku    # shorthand for claude-haiku
> switch opus
```

---

## OpenAI

Use GPT-4o or GPT-4o Mini.

### Install

```bash
pip install jsat[openai]
# or: pip install openai
```

### Set API key

```bash
export OPENAI_API_KEY=sk-...
```

### Activate

```bash
jsat ai use openai
jsat ai use openai --model gpt-4o-mini   # cheaper
jsat ai use openai --global              # all projects on this machine
```

Default model: `gpt-4o-mini`.

### Verify

```bash
jsat ai test
```

### Inside the shell

```
> switch gpt
> switch gpt4mini
```

### Open a GPT session directly

```bash
jsat gpt
```

---

## Google Gemini

JSAT connects to Gemini via its OpenAI-compatible endpoint.

### Set API key

Get a key from [aistudio.google.com](https://aistudio.google.com):

```bash
export GEMINI_API_KEY=...
# Also accepted: GOOGLE_API_KEY
```

### Activate

```bash
jsat ai use gemini
```

This sets the provider to `openai_compat` with `base_url` pointed at:

```
https://generativelanguage.googleapis.com/v1beta/openai
```

Available models: `gemini-1.5-flash` (default, fast), `gemini-1.5-pro` (higher quality).

```bash
jsat ai use gemini --model gemini-1.5-pro
```

### Verify

```bash
jsat ai test "what is 2 + 2?"
```

### Inside the shell

```
> switch gemini
> switch gemini-pro
```

---

## Ollama (Local, Free)

Ollama runs open-weight models locally. No API key, no data sent externally.

### Install

=== "macOS"

    ```bash
    brew install ollama
    ```

=== "Linux"

    ```bash
    curl -fsSL https://ollama.ai/install.sh | sh
    ```

=== "Windows"

    Download the installer from [ollama.ai](https://ollama.ai).

### Pull a model

```bash
ollama pull llama3.2       # 4 GB — good general quality
ollama pull phi3:mini      # 2 GB — fast, lower RAM usage
ollama pull qwen2.5-coder:7b  # 4 GB — code-focused
```

### Start the server

```bash
ollama serve
```

JSAT checks `http://localhost:11434` on startup. If Ollama is running, it is auto-selected when no cloud provider is configured.

### Activate

```bash
jsat ai use ollama
jsat ai use ollama --model phi3:mini
jsat ai use ollama --global             # all projects on this machine
```

### List pulled models

```bash
jsat ai models
```

### Verify

```bash
jsat ai test
```

### Open an Ollama session

```bash
jsat ollama
jsat ollama --model phi3:mini
```

### Inside the shell

```
> switch ollama
> switch phi    # shorthand for phi3:mini
> switch llama  # shorthand for llama3.2
```

---

## LM Studio (Local, Free)

LM Studio lets you download and run models from Hugging Face with a local OpenAI-compatible API.

### Install

Download from [lmstudio.ai](https://lmstudio.ai).

Load a model in LM Studio, then start the local server (usually at `http://localhost:1234`).

### Activate

```bash
jsat ai use lmstudio
```

This sets the provider to `openai_compat` with `base_url: http://localhost:1234/v1`. JSAT will use whatever model LM Studio has loaded.

### List loaded models

```bash
jsat ai models
```

### Verify

```bash
jsat ai test
```

### Inside the shell

```
> switch lmstudio
```

---

## Auto-Detection Priority

When no provider is explicitly configured, JSAT probes all backends on startup and picks the best available one in this priority order:

1. Claude Code CLI (`claude` binary found on PATH)
2. Bob Shell CLI (`bob` binary found on PATH)
3. Anthropic API (`ANTHROPIC_API_KEY` set)
4. OpenAI API (`OPENAI_API_KEY` set)
5. Google Gemini (`GEMINI_API_KEY` or `GOOGLE_API_KEY` set)
6. Ollama (reachable at `localhost:11434`)
7. LM Studio (reachable at `localhost:1234`)

If none are reachable, JSAT runs without AI (graph queries only, no natural language).

---

## Switching Providers

### From the CLI

Update `.jsat/config.yaml` and test:

```bash
jsat ai use ollama
jsat ai test
```

### From inside the JSAT shell

```
> switch claude
> switch claude-api
> switch claude-cli
> switch bob
> switch bob-cli
> switch gpt
> switch gpt4mini
> switch ollama
> switch phi
> switch llama
> switch gemini
> switch gemini-pro
> switch haiku
> switch opus
> switch lmstudio
```

### With the Python SDK

```python
from jsat import JSAT

js = JSAT(repo=".")
js.switch_ai("ollama", model="phi3:mini")

# Or set at construction
js = JSAT(repo=".", ai_provider="anthropic", model="claude-haiku-4-5-20251001")
```

---

## Provider Configuration Reference

All AI settings live under the `ai:` key in `.jsat/config.yaml`:

```yaml
ai:
  provider: ollama          # ollama | anthropic | openai | openai_compat | none
  model: llama3.2
  base_url: null            # set for lmstudio / gemini / custom endpoints
  max_tokens: 8192
  temperature: 0.1
  timeout_seconds: 120
  retry_attempts: 3
```

For Gemini:

```yaml
ai:
  provider: openai_compat
  model: gemini-1.5-flash
  base_url: https://generativelanguage.googleapis.com/v1beta/openai
```

For LM Studio:

```yaml
ai:
  provider: openai_compat
  model: local-model
  base_url: http://localhost:1234/v1
```

The `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` environment variables are read at runtime. Do not put API keys in `config.yaml`.
