# DeepSeek API

DeepSeek is a **hosted AI provider**, not a coding-agent CLI — there is nothing to launch and
no `jsat connect deepseek`/`jsat deepseek` command. It configures the AI backend JSAT's own
LLM-backed tools use (`crack`, `prompt_optimize`, `security_review`, and so on), the same way
`anthropic`/`openai`/`gemini` do.

DeepSeek's API is OpenAI-compatible, so JSAT reaches it through the same `openai_compat`
backend used for Gemini and LM Studio — `jsat ai use deepseek` just presets the base URL and
key environment variable for you.

## Set API key

Get a key from [platform.deepseek.com](https://platform.deepseek.com):

```bash
export DEEPSEEK_API_KEY=...
```

## Activate

DeepSeek needs an explicit model — JSAT never guesses one:

```bash
jsat ai use deepseek --model deepseek-chat
# or the reasoning-focused model:
jsat ai use deepseek --model deepseek-reasoner
```

This sets the provider to `openai_compat` with `base_url` pointed at:

```
https://api.deepseek.com/v1
```

and `api_key_env: DEEPSEEK_API_KEY`, so `DeepSeekProvider`-style calls read the right key
automatically — no manual `api_key_env` edit needed in `.jsat/config.yaml`.

```bash
# Apply globally (all projects on this machine):
jsat ai use deepseek --model deepseek-chat --global
```

## Verify

```bash
jsat ai test "what is 2 + 2?"
```

## Inside the shell

```
> switch deepseek <model>
```

## Troubleshooting

- A `404`/model-not-found style error from `jsat ai test` means the model name is wrong —
  DeepSeek's own docs list the current model IDs; `deepseek-chat` and `deepseek-reasoner` are
  the two general-purpose options at time of writing.
- If `DEEPSEEK_API_KEY` is unset, `jsat ai use deepseek` prints a warning at setup time; a
  missing/invalid key surfaces as an authentication error from `jsat ai test`.
- This is unrelated to "DeepSeek Harness" (`dsh`), a separate open-source coding-agent CLI
  launchable via `ollama launch dsh` — JSAT does not currently wire MCP tools into that harness.
