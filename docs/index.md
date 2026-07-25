# JSAT — JaySoft AI Tools

> Codebase intelligence shell and SDK. Lightweight by default.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/iamjpsonkar/JaySoft-AI_Tools/blob/main/LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/jsat.svg)](https://pypi.org/project/jsat/)

## What is JSAT?

JSAT gives any AI (Claude, GPT, Gemini, or local Ollama) deep, structured understanding of your codebase — so you spend less time explaining context and more time shipping.

- **Interactive shell** — IPython-style REPL for codebase intelligence
- **Python SDK** — `from jsat import JSAT` for programmatic access
- **Claude Code integration** — works as an MCP server with `/jsat-*` slash commands
- **Works offline** — local Ollama or LM Studio, no API keys required
- **Lightweight by default** — `pip install jsat` is ~80 MB and starts in under 800 ms
- **Graph-native** — SQLite (solo) or Neo4j (team) codebase graph, indexed by tree-sitter

## Quick Start

Three commands to get running:

```bash
pip install jsat                  # install
cd your-project && jsat index .   # build the codebase graph
jsat shell                        # open the interactive shell
```

Inside the shell:

```
JSAT Shell v0.1.0
> what does this project do?
> which services write to the orders table?
> blast-radius src/payment/refund.py
> switch claude
```

## Claude Code Integration

Connect JSAT to Claude Code for the best experience:

```bash
jsat connect claude    # wires JSAT as an MCP server + installs /jsat-* commands
jsat claude            # open Claude Code with all JSAT tools active
```

Then inside Claude Code, use slash commands:

```
/jsat-query what calls the refund endpoint?
/jsat-blast-radius src/payment/refund.py
/jsat-security
/jsat-incident 500 errors on checkout since 14:00
```

See [Claude Integration](claude-integration.md) for the full guide.

## Installation Profiles

| Profile | Command | Size | Best for |
|---------|---------|------|---------|
| Core | `pip install jsat` | ~80 MB | Quick evaluation |
| Local AI | `pip install jsat[local]` | ~85 MB | Solo dev with Ollama |
| Standard | `pip install jsat[standard]` | ~120 MB | Individual engineers |
| Team | `pip install jsat[team]` | ~200 MB | Engineering teams (Neo4j + Qdrant + Redis) |
| CI | `pip install jsat[ci]` | ~90 MB | CI pipelines (no AI cost) |
| Full | `pip install jsat[all]` | ~350 MB | Power users |

## Auto-Detection Matrix

JSAT detects your environment on first run and selects the right backends automatically. Run `jsat doctor` to see what was detected.

| Environment | Graph | Embeddings | Cache |
|------------|-------|-----------|-------|
| Laptop, Ollama running | SQLite | nomic-embed-code (local) | disk |
| Team server (Neo4j + Qdrant + Redis) | Neo4j | text-embedding-3-small | Redis |
| Apple M-series / ARM | SQLite | nomic-embed-code via Metal | disk |
| CI environment | SQLite | none (skipped) | memory |
| Raspberry Pi (< 4 GB RAM) | SQLite | nomic-embed-code (phi3:mini) | disk |

## Supported AI Providers

| Provider | Needs | Cost |
|----------|-------|------|
| Claude Code CLI | `claude` binary installed | Free tier available |
| Anthropic API | `ANTHROPIC_API_KEY` | Paid |
| OpenAI | `OPENAI_API_KEY` | Paid |
| Google Gemini | `GEMINI_API_KEY` | Paid |
| Ollama (local) | `ollama serve` + model | Free |
| LM Studio (local) | LM Studio running | Free |

## Next Steps

- [Getting Started](getting-started.md) — step-by-step setup
- [Claude Integration](claude-integration.md) — MCP server + `/jsat-*` commands
- [AI Providers](ai-providers.md) — configure any AI backend
- [CLI Reference](cli-reference.md) — every command and flag
- [Tools](tools.md) — the 15 JSAT tools explained
- [Python SDK](sdk.md) — programmatic access
- [Configuration](configuration.md) — `.jsat/config.yaml` reference
