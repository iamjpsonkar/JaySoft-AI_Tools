# Direct Ollama: local JSAT shell

Use this route when **JSAT itself** should send its LLM-backed tool requests to
an Ollama model. There is no Claude, Codex or OpenCode harness in this path —
JSAT talks to Ollama directly.

If you instead want to run a coding tool *against* an Ollama model with JSAT
wired in as MCP, that is a different route: see
[Ollama + Claude](ollama-claude.md), [Ollama + Codex](ollama-codex.md) or
[Ollama + OpenCode](ollama-opencode.md).

## Prerequisites and model setup

```bash
pip install jsat              # the [local] extra is optional — see below
ollama serve                  # keep running in another terminal
ollama pull qwen2.5:0.5b      # ~400 MB, enough to verify the wiring
ollama list                   # ALWAYS confirm what is installed
```

!!! warning "A running daemon is not a usable daemon"

    `ollama serve` answering on `:11434` says nothing about whether a model is
    available. With zero models pulled, JSAT reports Ollama as present but
    cannot complete a request — there is nothing to run. If `ollama list`
    prints only a header row, that is the problem, and it is by far the most
    common one on this route.

`pip install 'jsat[local]'` adds the official `ollama` Python SDK. It is
**not required**: JSAT falls back to a plain HTTP client, so the provider works
on a bare `pip install jsat`.

Model names are exact, including the tag. `qwen2.5` resolves to
`qwen2.5:latest` and does **not** match `qwen2.5:0.5b`. Choose a size that fits
your RAM — `jsat doctor` prints what it detected; a model larger than available
memory will refuse to load or swap badly enough to trip JSAT's tool timeouts.

## Configure, start, and verify

```bash
cd /path/to/project
jsat index .
jsat ai models ollama                       # what this server can offer
jsat ai use ollama --model qwen2.5:0.5b
jsat ai status                              # confirm it is the active provider
jsat ai test                                # a real completion, end to end
jsat ollama --model qwen2.5:0.5b            # open the JSAT shell
```

Sample shell queries:

```text
what does this project do?
blast-radius src/payments/service.py
security-review src/auth/
switch ollama <model>          # change model without leaving the shell
```

`jsat ai use ollama` persists the choice (add `--global` for every project on
the machine). `jsat ollama --model ...` opens a JSAT shell for that provider.
Neither command launches a coding client.

Since 0.4.17 an explicit choice in a config file wins over the profile JSAT
infers from running services — previously a Neo4j or Redis container up for an
unrelated project could move the whole config onto the `team` preset and
replace your provider.

## Local versus cloud

- **Local** (for example `qwen2.5:0.5b`): `ollama pull` it and keep
  `ollama serve` reachable. No account, no internet.
- **Cloud** (any `-cloud` / `:cloud` suffix): run `ollama signin`; do **not**
  pull it. JSAT detects the suffix and treats the model as cloud-routed.

```bash
ollama signin
jsat ai use ollama --model <name>-cloud
jsat ai test
```

## Which tools actually need the model

Most of JSAT is offline and unaffected by this route — indexing, blast radius,
contract diffing, migration analysis, incident ranking, token accounting and
the whole first phase of the prompt optimizer need no model at all. Ollama is
used by the LLM-backed tools: `query`, `crack`, `short`, review, runbook and
test generation. A small local model is usually fine for `short` and `query`,
and noticeably weak at `crack` and review, which reason over long context.

## From the Python SDK

```python
from jsat import JSAT

js = JSAT(repo=".")
js.switch_ai("ollama", model="qwen2.5:0.5b")
result = js.query("which function validates the payment amount?")
print(result.answer)
```

Building the provider directly needs the **full** config object; a bare
`AIConfig` raises `TypeError` rather than silently returning a no-op provider:

```python
from jsat._ai import get_ai_provider
from jsat._models import AIConfig, JSATConfig

cfg = JSATConfig()
cfg.ai = AIConfig(provider="ollama", model="qwen2.5:0.5b")
provider = get_ai_provider(cfg)
if provider.is_available():          # always check first
    print(provider.complete("Reply with one word: pong"))
```

When nothing is reachable JSAT substitutes a no-op provider whose `complete()`
raises `AIError`, so code that assumes success gets an exception rather than a
wrong answer.

## Lifecycle and isolation

`jsat start|stop|restart|resume` manage Claude, Codex and OpenCode processes.
They do **not** manage `ollama serve` or a direct JSAT shell — run the daemon
through your operating system's service manager and stop the shell normally.

To switch away without affecting any connected coding client:

```bash
jsat ai use claude_cli       # or codex_cli, opencode_cli, openai, anthropic
jsat ai test
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `jsat ai status` lists Ollama but `jsat ai test` fails | the daemon is up with **no models pulled** | `ollama pull qwen2.5:0.5b`, then `ollama list` |
| `model not found at http://localhost:11434` | the configured tag is not installed on that server | pull the exact tag, or pick one from `ollama list` — JSAT rewrites Ollama's bare 404 into a message naming what *is* installed |
| JSAT asks you to pick a model | several are installed and JSAT will not guess | `jsat ai use ollama --model <exact tag>` |
| a `-cloud` model starts downloading | it is being treated as local | `ollama signin` first; never `ollama pull` a cloud model |
| tool calls time out | the model is too large for available RAM, or loading for the first time | check RAM via `jsat doctor`, use a smaller tag, or raise the budget with `/jsat <cmd> timeout=300` |
| `ollama launch opencode` works but JSAT's own tools do not | those are two different routes | the launched route proves nothing about the direct provider — run `jsat ai status` and `jsat ai test` for this one |
| Ollama runs on another host or port | JSAT probes `localhost:11434` | set `OLLAMA_HOST` before starting JSAT |
