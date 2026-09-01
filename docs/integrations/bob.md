# Bob Shell

Use this route when the `bob` executable is installed and Bob Shell should own the conversation
and model selection. JSAT supplies MCP tools plus 47 `/jsat-*` slash commands and `BOB.md`
guidance.

## Prerequisites and connect

```bash
npm install -g @ibm/bob-shell
pip install jsat
cd /path/to/project
jsat index .
jsat connect bob --global
```

Use `jsat connect bob` instead for project scope. Global setup writes under `~/.bob/`; project
setup writes `.bob/settings.json`, `.bob/commands/`, and `BOB.md` at the project root. Use
`--no-commands` for MCP only, or `--no-instructions` to skip `BOB.md`.

## Start and select a model

```bash
jsat bob --repo .
jsat bob --mode advanced   # plan | code | advanced | ask
```

Bob Shell selects its model through its own configured provider/mode — no Ollama model is
pulled or selected. To make JSAT's internal LLM-backed tools use Bob too:

```bash
jsat ai use bob_cli
jsat ai test
```

## Use and verify JSAT

Inside Bob Shell, type `/` to browse the installed commands:

```text
/jsat-query what calls the payment adapter?
/jsat-blast-radius src/payments/service.py
/jsat-security
/jsat-review
```

`/jsat-prompt` optimizes your query and then answers it (`--optimize-only` to just see the
rewrite). A visible `/jsat-*` command does not by itself prove the MCP server started — if a
command runs but returns no graph data, reconnect and restart Bob Shell.

## Lifecycle

Bob is not one of JSAT's managed lifecycle clients (`jsat start`/`stop`/`restart`/`resume` cover
only Claude, Codex, and OpenCode). Bob's own session controls are exposed directly through the
launcher instead:

```bash
jsat bob --resume SESSION_ID
jsat bob --continue
```

## Troubleshooting and removal

- After install or reconnect, close every existing Bob Shell process and start a new one.
- Run `jsat connect list` and `jsat doctor` if MCP tools are absent.
- `.bob/settings.json` (or `~/.bob/settings.json`) holds the MCP server entry; `.bob/commands/`
  holds the `/jsat-*` command files — both are required for the full experience.

```bash
jsat disconnect bob
jsat disconnect bob --scope all
```
