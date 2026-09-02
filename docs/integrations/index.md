# Choose an AI integration

JSAT can connect to a native coding client, use Ollama directly, or let Ollama launch a
coding client with a local or cloud model. These are separate execution paths. Choose the tab
that matches the process you intend to run.

=== "Codex"

    Native Codex owns the conversation and model. JSAT supplies MCP tools and the `$jsat`
    dispatcher.

    ```bash
    jsat index .
    jsat connect codex
    jsat start codex --via native
    ```

    [Complete native Codex guide](codex.md)

=== "Claude"

    Native Claude Code owns the conversation and model. JSAT supplies MCP tools, `/jsat`, and
    `/jsat-help`.

    ```bash
    jsat index .
    jsat connect claude --global
    jsat start claude --via native
    ```

    [Complete native Claude guide](claude.md)

=== "OpenCode"

    A PATH-installed OpenCode owns the model and provider. This route does not invoke Ollama's
    launcher.

    ```bash
    jsat index .
    jsat connect opencode
    jsat start opencode --via native
    ```

    [Complete native OpenCode guide](opencode.md)

=== "Ollama local"

    JSAT talks directly to a model served by Ollama. No coding-client harness is involved.

    ```bash
    ollama pull qwen2.5:0.5b
    jsat ai use ollama --model qwen2.5:0.5b
    jsat ai test
    jsat ollama --model qwen2.5:0.5b
    ```

    [Complete direct Ollama guide](ollama-local.md)

=== "Ollama + Claude"

    Ollama launches Claude Code and supplies one selected local or cloud model to that process.

    ```bash
    jsat index .
    jsat connect ollama tool=claude
    jsat ollama --tool claude
    ```

    [Complete Ollama-launched Claude guide](ollama-claude.md)

=== "Ollama + OpenCode"

    Ollama launches OpenCode and supplies one selected local or cloud model. A standalone
    OpenCode installation is not required.

    ```bash
    jsat index .
    jsat connect ollama tool=opencode
    jsat ollama --tool opencode
    ```

    [Complete Ollama-launched OpenCode guide](ollama-opencode.md)

=== "Ollama + Codex"

    Ollama launches Codex and supplies one selected local or cloud model.

    ```bash
    jsat index .
    jsat connect ollama tool=codex
    jsat ollama --tool codex
    ```

    [Complete Ollama-launched Codex guide](ollama-codex.md)

## The distinction that prevents duplicate pulls

| Route | Conversation host | Who selects the model? | Needs `ollama pull`? |
|---|---|---|---|
| Native Claude/Codex/OpenCode | Native client | That client/account | No |
| Direct Ollama | JSAT shell | `jsat ai use ollama --model ...` | Local models only |
| Client through Ollama | Claude/Codex/OpenCode | Ollama selector or `--model` | Local models only |
| Client through Ollama Cloud | Claude/Codex/OpenCode | Ollama selector or cloud model name | No; use `ollama signin` |

`jsat ai use ollama` configures the AI provider used by JSAT's own LLM-backed tools.
`jsat ollama --tool TOOL` configures only the launched client process. One does not silently
replace the other.

## Manage all coding clients

With no target, lifecycle commands apply to Claude, Codex, and OpenCode:

```bash
jsat start
jsat ps
jsat restart
jsat stop
jsat resume
```

Interactive clients open in separate terminals. To keep routes isolated, name one client and
one route, for example `jsat start claude --via ollama --model qwen2.5:0.5b`.
