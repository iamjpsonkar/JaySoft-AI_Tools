# Native OpenCode

Use this route when `opencode` is installed on `PATH` and OpenCode should own its provider and
model. It remains separate from an OpenCode copy installed or launched internally by Ollama.

## Prerequisites and connect

Install OpenCode using its supported installer, configure its provider, then:

```bash
pip install jsat
cd /path/to/project
jsat index .
jsat connect opencode
```

JSAT writes `~/.config/opencode/opencode.json` and installs `/jsat` plus `/jsat-help` under
`~/.config/opencode/commands/`.

## Start and select a model

```bash
jsat start opencode --via native --repo .
```

Choose the provider/model inside OpenCode. To let JSAT's own LLM-backed tools call that native
OpenCode configuration too:

```bash
jsat ai use opencode
jsat ai test
```

## Use, verify, and manage

```text
/jsat status
/jsat query what calls the payment adapter?
/jsat-help
```

Ask OpenCode to call `jsat__get_index_status` to verify MCP, then manage the process with:

```bash
jsat ps
jsat restart opencode
jsat stop opencode
jsat resume opencode
jsat resume opencode --session SESSION_ID
```

If `--via auto` cannot find a PATH-visible OpenCode but does find Ollama, JSAT chooses the
Ollama route. Use `--via native` when you need to prove this route is isolated.

## Troubleshooting and removal

- If `/jsat` is absent, rerun `jsat connect opencode` and restart OpenCode.
- If the command exists but MCP does not, inspect `~/.config/opencode/opencode.json` and run
  `jsat doctor`.
- If OpenCode exists only because Ollama installed it internally, use
  [OpenCode through Ollama](ollama-opencode.md), not this route.

```bash
jsat disconnect opencode
```
