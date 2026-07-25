# JSAT — JaySoft AI Tools

> Codebase intelligence shell and SDK. Lightweight by default.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Author](https://img.shields.io/badge/author-Jay%20Prakash%20Sonkar-green.svg)](https://github.com/iamjpsonkar)

## What is JSAT?

JSAT gives any AI (Claude, Codex, Gemini, or local Ollama) deep, structured understanding of
your codebase — so you spend less time explaining context and more time shipping.

- **Interactive shell** like IPython, but for codebase intelligence
- **Python SDK** — `from jsat import JSAT`
- **Works offline** with local Ollama — no API keys required
- **Lightweight by default** — `pip install jsat` is ~80MB and starts in <800ms

## Quick Start

```bash
pip install jsat          # core only
pip install jsat[local]   # + Ollama for local AI (recommended)

cd your-project/
jsat init --profile solo  # write .jsat.yaml
jsat index .              # build the codebase graph
jsat                      # start the shell
```

```
JSAT Shell v0.1.0
> what does this project do?
> which services write to the orders table?
> blast-radius src/payment/refund.py
```

## Installation Profiles

| Profile | Command | Size | Use case |
|---------|---------|------|---------|
| Core | `pip install jsat` | ~80MB | Quick evaluation |
| Local AI | `pip install jsat[local]` | ~85MB | Solo dev with Ollama |
| Standard | `pip install jsat[standard]` | ~120MB | Individual engineers |
| Team | `pip install jsat[team]` | ~200MB | Engineering teams |
| CI | `pip install jsat[ci]` | ~90MB | CI pipelines (no AI cost) |
| Full | `pip install jsat[all]` | ~350MB | Power users |

## System Auto-Detection

JSAT probes your machine on first run and selects the right backends:

```bash
jsat doctor   # see what's detected and what to install
```

| Your setup | Graph | Embeddings | Cache |
|-----------|-------|-----------|-------|
| Laptop, Ollama running | SQLite | nomic-embed-code (local) | disk |
| Team server (Neo4j+Qdrant+Redis) | Neo4j | text-embedding-3-small | Redis |
| ARM (Apple M2, Pi) | SQLite | nomic-embed-code via Metal | disk |
| CI environment | SQLite | none (skipped) | memory |

## Python SDK

```python
from jsat import JSAT

js = JSAT(repo=".")
js.index()

# Natural language query
result = js.query("what calls the refund endpoint?")
print(result.answer)

# Blast radius — trace impact of a change
report = js.blast_radius("src/payment/refund.py")
for impact in report.impacts:
    print(f"{impact.severity}: {impact.node_name}")

# Incident investigation
incident = js.investigate_incident("500 errors on checkout since 14:00")
for h in incident.hypotheses:
    print(f"Score {h.score}: {h.commit_summary}")

# Export for sharing
js.export("backup.jsat.zip")
```

## CLI Reference

```bash
jsat index [PATH] [--branch HEAD] [--force]
jsat shell
jsat doctor [--refresh] [--json]
jsat init --profile solo|team|ci|raspberry-pi
jsat export OUTPUT
jsat import ARCHIVE
jsat skills list
jsat version
```

## Architecture

JSAT is built around a **graph-native architecture**:

- **tree-sitter** for multi-language AST parsing
- **SQLite** (local) or **Neo4j** (team) for the codebase graph
- **Ollama** (local) or any cloud LLM for AI features
- **Lazy loading** — nothing heavy loads until you use it

All backends implement ABCs — tools never call backends directly.

## Project

- **Author:** Jay Prakash Sonkar ([@iamjpsonkar](https://github.com/iamjpsonkar))
- **Email:** iamjpsonkar@gmail.com
- **License:** MIT
- **Specification:** [`plan.md`](plan.md) | **Implementation guide:** [`prompt.md`](prompt.md)
