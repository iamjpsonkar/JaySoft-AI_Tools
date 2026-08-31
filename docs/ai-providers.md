# AI Providers

This page configures the provider used by JSAT's own LLM-backed tools. To connect and launch a
coding client, use the [AI integration chooser](integrations/index.md). In particular,
`jsat ai use ollama` and `jsat ollama --tool TOOL` are intentionally different routes.

JSAT supports local CLI providers, hosted APIs, and local OpenAI-compatible servers. The right one is selected automatically based on what is available, but you can override it at any time.

## Provider Overview



| Provider | Switch command | Cost | Needs |
|----------|---------------|------|-------|
| Claude Code CLI | `jsat ai use claude_cli` | Free tier | `claude` binary |
| Bob Shell CLI | `jsat ai use bob_cli` | Free tier | `bob` binary |
| OpenAI Codex CLI | `jsat ai use codex-cli` | Paid/free by account | `codex` binary + Codex sign-in |
| OpenCode CLI | `jsat ai use opencode` | Depends on selected model | `opencode` binary/config |
| Anthropic API | `jsat ai use anthropic` | Paid | `ANTHROPIC_API_KEY` |
| OpenAI | `jsat ai use openai` | Paid | `OPENAI_API_KEY` |
| Google Gemini | `jsat ai use gemini` | Paid | `GEMINI_API_KEY` |
| DeepSeek API | `jsat ai use deepseek` | Paid | `DEEPSEEK_API_KEY` |
| Ollama (local/cloud) | `jsat ai use ollama` | Depends on model | `ollama serve` + model/sign-in |
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
│ bob                  │ ✓ available  │ no   │ bob binary found        │
│ codex-cli            │ ✓ available  │ no   │ codex binary found      │
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

---

## OpenAI Codex CLI

The Codex CLI provider lets JSAT MCP tools that need an LLM reuse the local
`codex` binary. JSAT calls `codex exec` in read-only, ephemeral mode and runs it
from the active repo directory, so it can answer from project context without
writing Codex instruction or skill files into that repo. JSAT applies the
non-interactive approval policy through Codex's stable `approval_policy` config
override and sends prompts through stdin, keeping the provider compatible with
Codex releases that do not expose the `--ask-for-approval` CLI flag.

### Install

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
# Verify:
which codex
codex --version
```

Run `codex` once from any project directory and sign in before using it as a JSAT
provider.

### Activate

```bash
jsat ai use codex-cli
```

This sets:

```yaml
ai:
  provider: codex_cli
  model: gpt-5.6-sol
```

### Verify

```bash
jsat ai test
```

### Inside the shell

```
> switch codex
```

---

## OpenCode CLI

Native OpenCode can provide JSAT's LLM calls through its configured provider and
model. The adapter uses `opencode run` and disables JSAT MCP only in that nested
call, preventing recursive self-invocation.

```bash
jsat connect opencode
jsat ai use opencode              # optional for non-MCP JSAT commands
```

When OpenCode itself was started by Ollama, JSAT does not start a nested OpenCode
provider. It reads Ollama's inherited inline configuration and sends requests to the
exact selected model instead.

---

## Anthropic API

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
> switch haiku <model>    # no model version is pinned by the alias
> switch opus <model>
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
jsat ai models openai
jsat ai use openai --model gpt-4o-mini   # cheaper
jsat ai use openai --model <model> --global  # all projects on this machine
```

JSAT does not choose an OpenAI model. Select one explicitly from the models available to your
account.

### Verify

```bash
jsat ai test
```

### Inside the shell

```
> switch gpt <model>
> switch gpt4mini <model>
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
> switch gemini-pro <model>
```

---

## DeepSeek API

A hosted provider, not a coding-agent CLI — there is nothing to launch or `jsat connect`. It
configures the backend JSAT's own LLM-backed tools use, reached through the same
`openai_compat` client as Gemini/LM Studio.

### Set API key

Get a key from [platform.deepseek.com](https://platform.deepseek.com):

```bash
export DEEPSEEK_API_KEY=...
```

### Activate

DeepSeek needs an explicit model — JSAT never guesses one:

```bash
jsat ai use deepseek --model deepseek-chat
jsat ai use deepseek --model deepseek-reasoner
```

This sets the provider to `openai_compat` with `base_url` pointed at
`https://api.deepseek.com/v1` and `api_key_env: DEEPSEEK_API_KEY`.

### Verify

```bash
jsat ai test "what is 2 + 2?"
```

### Inside the shell

```
> switch deepseek <model>
```

See [DeepSeek](integrations/deepseek.md) for the full standalone guide, including the
distinction from "DeepSeek Harness" (`dsh`), a separate Ollama-launchable coding-agent CLI that
JSAT does not currently integrate with.

---

## Ollama (Local or Cloud)

Ollama runs open-weight models locally and can route cloud-suffixed models through
Ollama Cloud (for example, `gemma4:31b-cloud`).
Local models keep inference on the machine; cloud models require `ollama signin` and internet.

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
jsat ai models ollama
jsat ai use ollama --model phi3:mini
jsat ai use ollama --model phi3:mini --global  # all projects on this machine
```

JSAT never guesses an Ollama model. It auto-selects only when the server reports exactly one;
with zero or multiple models it prints `ollama list`, local pull/cloud sign-in, and explicit
selection commands. Native Claude, Codex, and OpenCode similarly use their own configured model
unless you explicitly pass `--model`.

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

### Launch a coding tool through Ollama

```bash
jsat ollama --tool claude                  # interactive local/cloud selector
jsat ollama --tool opencode -m qwen3.5     # local model
ollama signin
jsat ollama --tool opencode -m gemma4:31b-cloud
```

The OpenCode route auto-connects JSAT as a global MCP server and installs `/jsat`
plus `/jsat-help` before Ollama launches it.
OpenCode does not need to be installed independently. To configure only:

```bash
jsat connect ollama tool=opencode
ollama  # choose OpenCode → sign in if prompted → choose a model
```

The direct-install equivalent is `jsat connect opencode`; both commands write the
same OpenCode MCP config. Bare `jsat connect ollama` configures Claude, Codex, and
OpenCode. The equivalent connect-and-launch route is `jsat ollama --tool opencode`.
Ollama still owns the OpenCode installation, sign-in prompt, and model selector.
JSAT inherits that exact selection for its own MCP tools, so a project-level
`ai.model` such as `llama3.2` is ignored for this launched session and no second
`ollama pull` is required.

### Inside the shell

```
> switch ollama <model>
> switch phi <model>    # explicit installed Phi-family model
> switch llama <model>  # explicit installed Llama-family model
```

---

## LM Studio (Local, Free)

LM Studio lets you download and run models from Hugging Face with a local OpenAI-compatible API.

### Install

Download from [lmstudio.ai](https://lmstudio.ai).

Load a model in LM Studio, then start the local server (usually at `http://localhost:1234`).

### Activate

```bash
jsat ai models lmstudio
jsat ai use lmstudio --model <loaded-model-id>
```

This sets the provider to `openai_compat` with `base_url: http://localhost:1234/v1` and the
model you selected from LM Studio's `/models` response.

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
> switch lmstudio <loaded-model-id>
```

---

## Auto-Detection Priority

When no provider is explicitly configured, JSAT probes all backends on startup and picks the best available one in this priority order:

1. Claude Code CLI (`claude` binary found on PATH)
2. Bob Shell CLI (`bob` binary found on PATH)
3. OpenAI Codex CLI (`codex` binary found on PATH)
4. Anthropic API (`ANTHROPIC_API_KEY` set)
5. OpenAI API (`OPENAI_API_KEY` set)
6. Google Gemini (`GEMINI_API_KEY` or `GOOGLE_API_KEY` set)
7. Ollama (reachable at `localhost:11434`)
8. LM Studio (reachable at `localhost:1234`)

If none are reachable, JSAT runs without AI (graph queries only, no natural language).

---

## Switching Providers

### From the CLI

Update `.jsat/config.yaml` and test:

```bash
jsat ai models ollama
jsat ai use ollama --model <model>
jsat ai test
```

### From inside the JSAT shell

```
> switch claude
> switch claude-api
> switch claude-cli
> switch bob
> switch bob-cli
> switch codex
> switch codex-cli
> switch gpt <model>
> switch gpt4mini <model>
> switch ollama <model>
> switch phi <model>
> switch llama <model>
> switch gemini
> switch gemini-pro <model>
> switch haiku <model>
> switch opus <model>
> switch lmstudio <loaded-model-id>
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
  provider: ollama          # also: anthropic, openai, openai_compat, claude_cli, opencode_cli, bob_cli, codex_cli, none
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
  model: <loaded-model-id>
  base_url: http://localhost:1234/v1
```

The `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` environment variables are read at runtime. Do not put API keys in `config.yaml`.
