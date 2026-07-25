# CLI Reference

All JSAT commands start with `jsat`. Run `jsat --help` or `jsat <command> --help` for any command.

---

## 1. Core Commands

### `jsat index`

Build or update the codebase graph.

```
jsat index [PATH] [OPTIONS]
```

| Argument / Flag | Default | Description |
|----------------|---------|-------------|
| `PATH` | repo root | Directory to index |
| `--branch`, `-b` | `HEAD` | Git branch to index |
| `--force`, `-f` | false | Re-index all files (ignore incremental cache) |
| `--languages`, `-l` | auto | Comma-separated list, e.g. `python,go` |
| `--incremental/--full` | incremental | Use incremental or full index strategy |

```bash
jsat index .
jsat index src/payments/ --force
jsat index . --branch feature/new-api --languages python,go
jsat index . --full
```

---

### `jsat shell`

Start the JSAT interactive shell.

```
jsat shell [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repository root |
| `--verbose`, `-v` | false | Enable DEBUG logging |

```bash
jsat shell
jsat shell --repo /path/to/project
```

Inside the shell, type natural language questions or built-in commands:

```
> what does this project do?
> blast-radius src/payment/refund.py
> security-review
> incident "500 errors since 14:00"
> switch claude
> status
> help
```

---

### `jsat claude`

Open Claude Code with all JSAT MCP tools available.

```
jsat claude [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repository root |
| `--verbose`, `-v` | false | Enable DEBUG logging |

```bash
jsat claude
jsat claude --repo /path/to/project
```

Requires Claude Code CLI to be installed. JSAT must be connected first (`jsat connect claude`).

---

### `jsat gpt`

Open a GPT-4o session with JSAT tools.

```
jsat gpt [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repository root |
| `--verbose`, `-v` | false | Enable DEBUG logging |

```bash
export OPENAI_API_KEY=sk-...
jsat gpt
```

---

### `jsat ollama`

Open an Ollama-powered session (local, free, no API key).

```
jsat ollama [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repository root |
| `--model`, `-m` | `llama3.2` | Ollama model name |
| `--verbose`, `-v` | false | Enable DEBUG logging |

```bash
jsat ollama
jsat ollama --model phi3:mini
jsat ollama --model qwen2.5-coder:7b
```

---

### `jsat doctor`

Run a system health check. Shows system, services, AI providers, and index status.

```
jsat doctor [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--refresh` | false | Re-detect system (ignore cached profile) |
| `--json` | false | Output raw JSON |

```bash
jsat doctor
jsat doctor --refresh
jsat doctor --json | jq '.ai'
```

---

### `jsat version`

Print the installed JSAT version.

```bash
jsat version
# jsat 0.1.0
```

---

## 2. AI Commands (`jsat ai`)

### `jsat ai status`

Show which AI providers are available and which is currently configured.

```bash
jsat ai status
```

Output columns: Provider, Status, Free, Notes/Models.

---

### `jsat ai use`

Configure JSAT to use a specific AI provider. Writes to `.jsat/config.yaml`.

```
jsat ai use PROVIDER [OPTIONS]
```

| Argument / Flag | Description |
|----------------|-------------|
| `PROVIDER` | `ollama`, `anthropic`, `openai`, `lmstudio` |
| `--model`, `-m` | Override the default model for this provider |
| `--config`, `-c` | Config file to write (default: `.jsat/config.yaml`) |

```bash
jsat ai use ollama
jsat ai use ollama --model phi3:mini
jsat ai use anthropic
jsat ai use anthropic --model claude-haiku-4-5-20251001
jsat ai use openai --model gpt-4o-mini
jsat ai use lmstudio
```

Runs a connectivity test after writing and reports whether the AI is reachable.

---

### `jsat ai test`

Send a test prompt to the configured AI and print the response.

```
jsat ai test [PROMPT]
```

| Argument | Default | Description |
|---------|---------|-------------|
| `PROMPT` | `"Say hello in one sentence."` | Prompt to send |

```bash
jsat ai test
jsat ai test "what is 2 + 2?"
```

---

### `jsat ai models`

List available models for the configured provider.

- For **Ollama**: queries `http://localhost:11434/api/tags`
- For **LM Studio**: queries `http://localhost:1234/v1/models`
- For cloud providers: shows the currently configured model (no remote list)

```bash
jsat ai models
```

---

## 3. Connect Commands (`jsat connect`)

### `jsat connect claude`

Wire JSAT into Claude Code as an MCP server and install `/jsat-*` slash commands.

```
jsat connect claude [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--scope`, `-s` | `project` | `project` or `global` |
| `--repo`, `-r` | `.` | Repo path for the MCP server |
| `--install-skills/--no-skills` | `--install-skills` | Install `/jsat-*` commands |
| `--show` | false | Print the written config |

```bash
jsat connect claude                         # project scope
jsat connect claude --scope global          # global scope (all sessions)
jsat connect claude --no-skills             # MCP only, no slash commands
jsat connect claude --show                  # print config after writing
```

Restart Claude Code after running.

---

### `jsat connect cursor`

Wire JSAT into Cursor as an MCP server.

```
jsat connect cursor [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repo path for the MCP server |

```bash
jsat connect cursor
```

Writes to `~/.cursor/mcp.json`. Restart Cursor after running.

---

### `jsat connect list`

Show all Claude Code and Cursor MCP configs that include JSAT.

```bash
jsat connect list
```

Checks:

- `~/.claude/settings.json` (global Claude Code)
- `.claude/settings.json` (project Claude Code)
- `~/.cursor/mcp.json` (Cursor)

---

## 4. Disconnect Commands (`jsat disconnect`)

### `jsat disconnect claude`

Remove JSAT from Claude Code's MCP config and optionally remove skill files.

```
jsat disconnect claude [OPTIONS]
```

| Argument | Default | Description |
|---------|---------|-------------|
| `TOOL` | `claude` | Tool to disconnect: `claude`, `cursor`, or `all` |
| `--scope`, `-s` | `project` | `project`, `global`, or `all` |
| `--keep-skills` | false | Keep `/jsat-*` skill files (default: remove them) |

```bash
jsat disconnect claude                       # project scope
jsat disconnect claude --scope global        # global scope
jsat disconnect claude --scope all           # both project and global
jsat disconnect claude --keep-skills         # remove MCP entry, keep skill files
jsat disconnect cursor                       # disconnect from Cursor
```

Restart Claude Code after running.

---

## 5. Init Command

### `jsat init`

Generate a starter `.jsat/config.yaml` for a given profile. Does not overwrite if the file already exists.

```
jsat init [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--profile`, `-p` | `solo` | `solo`, `team`, `ci`, or `raspberry-pi` |
| `--output`, `-o` | `.jsat/config.yaml` | Output path |

```bash
jsat init --profile solo
jsat init --profile team
jsat init --profile ci
jsat init --profile raspberry-pi --output /etc/jsat/config.yaml
```

---

## 6. Export and Import

### `jsat export`

Export the current index to a portable zip archive.

```
jsat export OUTPUT [OPTIONS]
```

| Argument / Flag | Default | Description |
|----------------|---------|-------------|
| `OUTPUT` | (required) | Output path, e.g. `backup.jsat.zip` |
| `--compress`, `-z` | `6` | Compression level 0-9 (0 = no compression, 9 = max) |

```bash
jsat export backup.jsat.zip
jsat export backup.jsat.zip --compress 9
```

---

### `jsat import`

Restore an index from an exported archive.

```
jsat import ARCHIVE [OPTIONS]
```

| Argument / Flag | Default | Description |
|----------------|---------|-------------|
| `ARCHIVE` | (required) | Path to `.jsat.zip` archive |
| `--migrate` | false | Apply schema migrations if version differs |

```bash
jsat import backup.jsat.zip
```

---

## 7. Remove Command

### `jsat remove`

Remove all JSAT artifacts from the current repository. Interactive confirmation by default.

```
jsat remove [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--yes`, `-y` | false | Skip confirmation prompt |
| `--keep-config` | false | Keep `.jsat/config.yaml` (preserve settings) |

Removes:

- `.jsat/graph/` — codebase graph database
- `.jsat/vectors/` — embedding vectors
- `.jsat/cache/` — semantic cache
- `.jsat/system-profile.json`
- `.jsat/config.yaml` (unless `--keep-config`)
- `.claude/commands/jsat-*.md` — skill files
- `mcpServers.jsat` entry in `.claude/settings.json`

Does not touch your source code, git history, or other Claude configuration.

```bash
jsat remove
jsat remove --yes              # skip confirmation
jsat remove --keep-config      # preserve config.yaml
```

---

## 8. Skills Commands (`jsat skills`)

### `jsat skills list`

List installed JSAT skills (YAML manifests in the skills directory).

```bash
jsat skills list
```

---

### `jsat skills run`

Run a named skill.

```
jsat skills run NAME [OPTIONS]
```

| Argument / Flag | Description |
|----------------|-------------|
| `NAME` | Skill name |
| `--args`, `-a` | `key=val` pairs (repeatable) |

```bash
jsat skills run my-skill
jsat skills run my-skill --args target=src/api.py --args depth=3
```

---

## 9. MCP Server (Internal)

### `jsat mcp-server`

Start the JSAT MCP server on stdin/stdout. This is invoked automatically by Claude Code and Cursor when JSAT is connected. You do not normally run this directly.

```
jsat mcp-server [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--repo`, `-r` | `.` | Repository root to serve |
| `--verbose`, `-v` | false | Enable debug logging |

If you need to test the MCP server manually:

```bash
jsat mcp-server --repo /path/to/project --verbose
```

The server speaks JSON-RPC 2.0 over stdin/stdout. It starts immediately and loads JSAT lazily to avoid startup timeout errors in Claude Code.

---

## Environment Variables

| Variable | Used by |
|---------|---------|
| `JSAT_CONFIG` | Override config file path |
| `ANTHROPIC_API_KEY` | Anthropic API provider |
| `OPENAI_API_KEY` | OpenAI provider |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini provider |
| `NEO4J_PASSWORD` | Neo4j graph backend |
| `QDRANT_API_KEY` | Qdrant vector store |
| `JSAT_MCP_TOKEN` | MCP server auth token (if `mcp.auth: true`) |
| `CI` | If `true`/`1`/`yes`, forces CI profile (no embeddings, memory cache) |
