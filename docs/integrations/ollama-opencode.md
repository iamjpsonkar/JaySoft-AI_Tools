# OpenCode through Ollama

Use this route when Ollama should install/launch OpenCode and supply a local or cloud model. A
standalone PATH installation of OpenCode is not required.

## Prerequisites and connect

```bash
pip install jsat
cd /path/to/project
jsat index .
jsat connect ollama tool=opencode
```

JSAT writes the same OpenCode MCP configuration used by a native installation and installs
`/jsat` plus `/jsat-help`. Ollama owns OpenCode installation, sign-in, and model selection.

You can also preserve Ollama's normal menu flow:

```bash
ollama
# choose OpenCode -> sign in if prompted -> choose a model
```

## Select and launch a model

```bash
jsat ollama --tool opencode                 # interactive local/cloud selector
ollama pull qwen3.5
jsat ollama --tool opencode -m qwen3.5      # exact local model
ollama signin
jsat ollama --tool opencode -m gemma4:31b-cloud
```

The selected model is injected into only the launched OpenCode process. It does not persist as
JSAT's direct AI provider and does not require another pull. A cloud model is authenticated with
`ollama signin`, not downloaded.

### Remember a model for this tool

`jsat connect ollama tool=opencode --model gemma4:31b-cloud` saves that model as OpenCode's
default for this launch route. A later bare `jsat ollama --tool opencode` (or the shorthand
`jsat ollama opencode`) reuses it automatically instead of showing Ollama's interactive
selector — pass `-m`/`--model` explicitly to override it for a single launch.

## Use and verify JSAT

Inside OpenCode:

```text
/jsat status
/jsat query find the checkout entry point
/jsat-help crack
```

Ask OpenCode to call `jsat__get_index_status`, and verify the model/provider shown in OpenCode's
status line. Seeing `1 MCP` alone proves only that a server is registered; a successful tool call
proves it can execute.

## Managed lifecycle

```bash
jsat start opencode --via ollama --model qwen3.5
jsat ps
jsat restart opencode
jsat stop opencode
jsat resume opencode
jsat resume opencode --session SESSION_ID
```

With `--via auto`, JSAT prefers a PATH-visible native OpenCode. If none is visible and Ollama is
installed, it uses this route. Pass `--via ollama` to remove ambiguity.

## Troubleshooting

- If OpenCode works via `ollama launch opencode` but direct JSAT says a model is missing, the two
  routes have different model configuration. Do not pull again unless you actually want direct
  local Ollama; launch OpenCode through Ollama with its selected model.
- If `/jsat` is absent, rerun `jsat connect ollama tool=opencode`, then restart OpenCode.
- If MCP is listed but commands are absent, the MCP config loaded but command files did not;
  reconnect to reinstall both surfaces.

For a separately installed binary and OpenCode-owned provider, use [native OpenCode](opencode.md).
