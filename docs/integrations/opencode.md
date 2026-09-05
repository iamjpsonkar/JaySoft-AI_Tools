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

By default JSAT wires JSAT into **just this repo**, mirroring `jsat connect claude`:

- `.opencode/opencode.json` — OpenCode's MCP config, with JSAT pinned to this repo
  via `--repo`, so every OpenCode session in this checkout starts the same JSAT graph
- `.opencode/commands/` — the `/jsat` and `/jsat-help` slash commands
- `AGENTS.md` — JSAT tool guidance (OpenCode loads AGENTS.md from the project root
  automatically, the same way Claude Code loads CLAUDE.md)

For a one-time, all-projects setup, pass `--global`:

```bash
jsat connect opencode --global   # ~/.config/opencode/opencode.json (+ ~/.config/opencode/commands/)
```

Global installs are not repo-pinned (`--repo` is omitted): OpenCode starts JSAT in
whichever workspace is active, and nothing is written into the project.

After connecting, restart OpenCode — it reads config once at startup and does not
hot-reload it.

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

`jsat opencode` and `jsat ollama --tool opencode` auto-connect JSAT to the repo's
`.opencode/` wiring on the way in, so a fresh checkout gets MCP + slash commands
without a manual `jsat connect opencode`.

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
- If the command exists but MCP does not, inspect the config that applies to your session
  (`.opencode/opencode.json` in the repo, or `~/.config/opencode/opencode.json` for a
  global install) and run `jsat doctor`.
- If OpenCode exists only because Ollama installed it internally, use
  [OpenCode through Ollama](ollama-opencode.md), not this route.

```bash
jsat disconnect opencode                  # removes this repo's .opencode/ wiring + AGENTS.md block
jsat disconnect opencode --scope global   # removes the ~/.config/opencode wiring
```
