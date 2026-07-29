# Getting Started

This guide walks from zero to a working JSAT session in five steps.

## Prerequisites

- Python 3.10 or later
- A project directory with source code to index
- (Optional) Claude Code CLI for the best experience — [install at claude.ai/code](https://claude.ai/code)
- (Optional) Ollama for local, offline AI — see [AI Providers](ai-providers.md)

---

## Step 1: Install JSAT

=== "Core (recommended start)"

    ```bash
    pip install jsat
    ```

    Installs tree-sitter parsers, SQLite graph, and CLI. About 80 MB. Starts in under 800 ms.

=== "With local Ollama AI"

    ```bash
    pip install jsat[local]
    ```

    Adds the `ollama` Python client so JSAT can call your local Ollama server.

=== "Standard (more languages + security)"

    ```bash
    pip install jsat[standard]
    ```

    Adds Semgrep for security scanning, OpenAPI validation, and parsers for Java, Ruby, and Rust.

=== "Team (Neo4j + Redis)"

    ```bash
    pip install jsat[team]
    ```

    Adds Neo4j, Qdrant, and Redis backends for shared team use. Requires those services to be running.

=== "Full"

    ```bash
    pip install jsat[all]
    ```

    Everything: local AI, team backends, Anthropic, OpenAI, CI tooling. About 350 MB.

Verify the install:

```bash
jsat version
# jsat 0.1.0
```

---

## Step 2: Connect Claude Code (Recommended)

If you have Claude Code CLI installed, connect JSAT as an MCP server. This gives you all JSAT tools directly inside Claude Code without leaving your AI session.

=== "Global — one-time setup (recommended)"

    ```bash
    jsat connect claude --global
    ```

    Installs JSAT into `~/.claude/settings.json` and `~/.claude/commands/`. Works in every Claude Code project on this machine — no per-repo setup needed.

=== "Per-project"

    ```bash
    jsat connect claude
    ```

    Installs JSAT into `.claude/settings.json` in the current directory. Only active in this project.

Both commands:

1. Write a JSAT MCP server entry into the Claude settings file
2. Install 31 `/jsat-*` slash command skill files in the Claude commands directory

After running, **restart Claude Code** to activate the MCP tools.

See [Claude Integration](claude-integration.md) for details.

---

## Step 3: Index Your Project

Navigate to your project root and build the codebase graph:

```bash
cd my-project/
jsat index .
```

JSAT will:

1. Parse all source files with tree-sitter (Python, JS/TS, Go, and more)
2. Extract functions, classes, endpoints, tables, and their relationships
3. Store the graph in `~/.jsat/<hash>/graph/graph.db` (global by default, outside the repo)
4. Generate embeddings for semantic search (if a local or API embedding model is configured)

Example output:

```
 Indexing… ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:04
✓ Indexed 1,842 nodes, 4,391 edges in 4.2s
```

**Re-indexing is incremental by default.** Only changed files are re-parsed. Force a full re-index with `--force`:

```bash
jsat index . --force
```

Index only specific languages:

```bash
jsat index . --languages python,go
```

---

## Step 4: Open Claude Code (or the Shell)

=== "Claude Code (recommended)"

    ```bash
    jsat claude
    ```

    Opens Claude Code with JSAT MCP tools automatically available. Claude can call tools like `jsat__query`, `jsat__blast_radius`, and `jsat__security_review` without any extra setup.

=== "Interactive Shell"

    ```bash
    jsat shell
    ```

    Opens a standalone REPL with all JSAT tools. No Claude Code required. You can switch AI providers from inside the shell.

=== "GPT session"

    ```bash
    export OPENAI_API_KEY=sk-...
    jsat gpt
    ```

=== "Ollama session (local)"

    ```bash
    ollama serve          # in a separate terminal
    ollama pull llama3.2  # first time only
    jsat ollama
    ```

---

## Step 5: Try a Query

Inside Claude Code after connecting:

```
/jsat-query what does this project do?
/jsat-query which services call the payments API?
/jsat-blast-radius src/payment/refund.py
/jsat-security
```

Inside the JSAT shell:

```
> what does this project do?
> blast-radius src/payment/refund.py
> security-review
> incident "500 errors on checkout since 14:00"
```

---

## Check Setup Health

Run `jsat doctor` at any time to see what JSAT has detected:

```bash
jsat doctor
```

This shows:

- **System**: RAM, CPU architecture, GPU, CI mode
- **Services**: Ollama, Neo4j, Qdrant, Redis — running or not
- **AI Providers**: which are available, which is active, how to switch
- **Index**: node and edge counts, freshness

Example:

```
╭─ System ──────────────────────────────╮
│ Profile   solo                        │
│ RAM       16.0 GB                     │
│ Arch      arm64                       │
│ GPU       metal                       │
│ CI mode   False                       │
╰───────────────────────────────────────╯
╭─ AI Providers  (active: claude_cli/claude-sonnet-4-6) ─╮
│ Claude Code (CLI)  ✓ available  free   switch claude-cli│
│ Anthropic API      ✓ key set    paid   switch claude-api│
│ Ollama (local)     ✓ running    free   switch ollama    │
│ OpenAI API         ✗ no key     paid   switch gpt       │
╰─────────────────────────────────────────────────────────╯
```

---

## Manual Setup (Without Claude Code)

If you do not have Claude Code installed, JSAT still works fully via its own shell or Python SDK.

```bash
# Generate a global config (applies to all projects on this machine)
jsat init --global --profile solo

# — or — per-project config
jsat init --profile solo

# Set AI provider (globally or per-project)
jsat ai use ollama --global       # global: ~/.jsat/config.yaml
jsat ai use ollama                # per-project: .jsat/config.yaml

# Index your project
jsat index .

# Open the JSAT shell
jsat shell
```

Inside the shell, type any natural language question or use a built-in command:

| Shell command | What it does |
|--------------|-------------|
| `blast-radius src/foo.py` | Trace downstream impact |
| `security-review` | OWASP scan |
| `incident "error description"` | Root-cause hypotheses |
| `switch ollama` | Switch AI provider |
| `switch claude` | Switch to Claude Code CLI |
| `status` | Show graph stats |
| `help` | Show all commands |

---

## What Gets Created

Running `jsat index` and `jsat connect claude` creates these files:

=== "Default (global data dir, per-project connect)"

    ```
    ~/.jsat/
    └── <hash12>/            # global data dir for this repo (never inside git)
        ├── graph/
        │   └── graph.db     # SQLite codebase graph
        ├── vectors/         # embedding vectors (if configured)
        ├── cache/           # semantic cache (disk backend)
        └── system-profile.json

    your-project/
    ├── .jsat/
    │   └── config.yaml      # optional project-specific config (jsat init)
    └── .claude/
        ├── settings.json    # MCP server entry (jsat connect claude)
        └── commands/
            └── jsat-*.md    # 31 slash command files
    ```

=== "Global connect (jsat connect claude --global)"

    ```
    ~/.jsat/
    ├── config.yaml          # global config (jsat init --global)
    └── <hash12>/            # global data dir (per-repo, auto-created)
        ├── graph/graph.db
        ├── vectors/
        └── cache/

    ~/.claude/
    ├── settings.json        # global MCP entry — works in every project
    └── commands/
        └── jsat-*.md        # global slash commands
    ```

The `~/.jsat/<hash12>/` directory is outside every git repo — nothing to `.gitignore`. If you run `jsat connect claude` (project scope), add `.claude/commands/jsat-*.md` to `.gitignore` if you prefer not to commit the skill files.
