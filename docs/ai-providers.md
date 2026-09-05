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
│ ollama               │ ✓ running    │ yes  │ (your `ollama list`)   │
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
jsat connect opencode               # wires this repo (.opencode/) … 
jsat connect opencode --global      # … or every project (~/.config/opencode/opencode.json)
jsat ai use opencode                # optional for non-MCP JSAT commands
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

Ollama runs open-weight models on your own machine, and routes `-cloud`-suffixed
models through Ollama Cloud. It is the only provider that needs no account at
all for local models, which makes it the usual choice for air-gapped work and
for keeping proprietary code off third-party servers.

There are **two different ways** JSAT and Ollama combine, and mixing them up is
the most common source of confusion:

| Route | Who owns the model | Use it for |
|---|---|---|
| **Direct provider** — `jsat ai use ollama` | JSAT | JSAT's own LLM-backed tools (`query`, `crack`, `short`, review, test generation) |
| **Launched coding tool** — `jsat ollama --tool <tool>` | Ollama | Running Claude/Codex/OpenCode against an Ollama model, with JSAT wired in as MCP |

On the second route JSAT deliberately **inherits** whatever model Ollama's own
selector chose and ignores the project's `ai.model`. That is not a bug: a model
name is meaningful only to the provider that owns it, and forwarding one across
providers is what previously caused Codex to be handed Ollama model names.

!!! warning "A running server is not a usable server"

    `ollama serve` responding on `:11434` tells you nothing about whether a
    **model** is available. With the daemon up and zero models pulled,
    `jsat ai status` reports Ollama as present but `jsat ai test` cannot
    complete, because there is nothing to run. This is the single most common
    Ollama problem and it looks like a JSAT fault. Check with `ollama list`
    before anything else — if it prints only a header row, pull a model.

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

The optional extra is **not required**:

```bash
pip install 'jsat[local]'   # installs the official `ollama` Python SDK
```

JSAT falls back to a plain HTTP client when that package is absent, so the
provider works on a bare `pip install jsat`. Install the extra only if you
want the SDK's own behaviour.

### Pull a model

Sizes and names change, so discover them rather than trusting a list in
documentation — browse [ollama.com/library](https://ollama.com/library) or run
`ollama list` after pulling:

```bash
ollama pull qwen2.5:0.5b      # ~400 MB — small enough to verify the wiring
ollama list                   # confirm what is actually installed
```

Model names are exact, including the tag. `qwen2.5` resolves to
`qwen2.5:latest`; it does **not** match `qwen2.5:0.5b`. If `jsat ai test`
reports a missing model, the tag is almost always the reason.

Pick a size that fits your RAM. A model larger than available memory will
either refuse to load or swap so heavily that JSAT's tool timeouts fire —
`jsat doctor` prints the RAM it detected.

### Start the server

```bash
ollama serve                  # keep running; JSAT probes http://localhost:11434
```

JSAT checks that URL at startup and auto-selects Ollama when no cloud provider
is configured.

### Activate

```bash
jsat ai models ollama                        # what this server can offer
jsat ai use ollama --model qwen2.5:0.5b      # this project
jsat ai use ollama --model qwen2.5:0.5b --global   # every project on this machine
jsat ai test                                 # a real completion, end to end
```

**JSAT never guesses a model.** It auto-selects only when the server reports
exactly one; with zero or several it prints `ollama list` plus the explicit
selection command rather than picking for you. The same rule applies to the
Claude, Codex and OpenCode CLIs, which use their own configured model unless
you pass `--model`.

Your explicit choice also survives auto-detection: since 0.4.17, anything
written in a config file wins over the profile JSAT infers from the services it
finds running. Previously, having a Neo4j or Redis container up for an
unrelated project could pull the whole config onto the `team` preset and
replace an explicit provider or graph backend.

### Local versus cloud

```bash
# Local: pull it, keep `ollama serve` reachable
ollama pull qwen2.5:0.5b
jsat ai use ollama --model qwen2.5:0.5b

# Cloud: sign in, do NOT pull
ollama signin
jsat ai use ollama --model <name>-cloud
```

JSAT detects the `:cloud` / `-cloud` suffix and treats the model as
cloud-routed. Cloud models need internet and an Ollama account; local models
need neither.

### Open an Ollama session

```bash
jsat ollama                        # JSAT shell on the configured model
jsat ollama --model qwen2.5:0.5b   # JSAT shell on a specific model
```

Inside the shell:

```text
what does this project do?
blast-radius src/payments/service.py
security-review src/auth/
switch ollama <model>              # change model mid-session
```

Neither `jsat ai use ollama` nor `jsat ollama` launches a coding client — both
stay on the direct-provider route.

### Launch a coding tool through Ollama

```bash
jsat ollama --tool claude                    # interactive model selector
jsat ollama --tool opencode -m <model>       # local model
ollama signin && jsat ollama --tool opencode -m <model>-cloud
```

The OpenCode route auto-connects JSAT as a global MCP server and installs the
`/jsat` dispatcher before Ollama launches it; OpenCode does not need to be
installed separately. To configure without launching:

```bash
jsat connect ollama tool=opencode
ollama                             # choose OpenCode → sign in → choose a model
```

`jsat connect opencode` writes the same OpenCode MCP config — by default in the
current repo's `.opencode/`, or machine-wide with `--global`. Bare
`jsat connect ollama` configures Claude, Codex and OpenCode together. Ollama
owns the installation, the sign-in prompt and the model selector; JSAT inherits
that selection for its own MCP tools, so no second `ollama pull` is needed and
a project-level `ai.model` is ignored for that session.

### Using Ollama from the Python SDK

```python
from jsat import JSAT

js = JSAT(repo=".")
js.switch_ai("ollama", model="qwen2.5:0.5b")
print(js.query("which function validates the payment amount?").answer)
```

Reaching for the provider directly requires the **full** config object, not a
bare `AIConfig` — since 0.4.17 the wrong type raises `TypeError` instead of
silently handing back a no-op provider:

```python
from jsat._ai import get_ai_provider
from jsat._models import AIConfig, JSATConfig

cfg = JSATConfig()
cfg.ai = AIConfig(provider="ollama", model="qwen2.5:0.5b")
provider = get_ai_provider(cfg)          # correct
if provider.is_available():
    print(provider.complete("Reply with one word: pong"))
```

Always check `is_available()` first. When no provider can be reached JSAT
substitutes a no-op provider whose `complete()` raises `AIError`, so code that
assumes success will get an exception rather than a wrong answer.

### Lifecycle

`jsat start|stop|restart|resume` manage Claude, Codex and OpenCode processes.
They do **not** manage `ollama serve` or a direct JSAT shell — run the daemon
through your operating system's service manager and stop the shell normally.

To move off Ollama without touching any connected coding client:

```bash
jsat ai use claude_cli     # or codex_cli, opencode_cli, openai, anthropic
jsat ai test
```

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `jsat ai status` shows Ollama, `jsat ai test` fails | the daemon is up with **no models pulled** | `ollama pull qwen2.5:0.5b`, then `ollama list` |
| `model not found at http://localhost:11434` | the configured tag is not installed on that server | pull the exact tag, or pick one from `ollama list` — JSAT turns Ollama's bare 404 into a message naming what *is* installed |
| JSAT asks you to choose a model | more than one is installed and JSAT will not guess | `jsat ai use ollama --model <exact tag>` |
| a `-cloud` model tries to download | it is being treated as local | `ollama signin` first; never `ollama pull` a cloud model |
| tool calls time out | the model is too large for available RAM, or is loading for the first time | check RAM with `jsat doctor`, use a smaller tag, or raise the budget with `/jsat <cmd> timeout=300` |
| `ollama launch opencode` works but JSAT's own tools do not | those are the two different routes above | the launched route proves nothing about the direct provider — run `jsat ai status` and `jsat ai test` |
| Ollama is unreachable at a custom host | JSAT probes `localhost:11434` | point `OLLAMA_HOST` at your server before starting JSAT |

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
js.switch_ai("ollama", model="qwen2.5:0.5b")

# Or set at construction
js = JSAT(repo=".", ai_provider="anthropic", model="claude-haiku-4-5-20251001")
```

---

## Provider Configuration Reference

All AI settings live under the `ai:` key in `.jsat/config.yaml`:

```yaml
ai:
  provider: ollama          # also: anthropic, openai, openai_compat, claude_cli, opencode_cli, bob_cli, codex_cli, none
  model: qwen2.5:0.5b
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
