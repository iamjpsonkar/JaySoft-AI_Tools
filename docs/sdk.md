# Python SDK

The `JSAT` class is the main entry point for all programmatic use. Import it from the `jsat` package.

```python
from jsat import JSAT
```

All heavy dependencies are lazy-loaded on first use. Instantiation is fast — only config loading and system detection run.

---

## Construction

```python
JSAT(
    repo=".",
    config=None,
    ai_provider=None,
    model=None,
    log_level="WARNING",
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `repo` | `str \| Path` | `"."` | Repository root directory |
| `config` | `str \| Path \| None` | `None` | Explicit config file path. If `None`, config is searched in the standard locations (see [Configuration](configuration.md)) |
| `ai_provider` | `str \| None` | `None` | Override the AI provider from config. Aliases: `"ollama"`, `"anthropic"`, `"openai"`, `"gemini"`, `"claude"`, `"lmstudio"` |
| `model` | `str \| None` | `None` | Override the model from config |
| `log_level` | `str` | `"WARNING"` | Logging level: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"` |

```python
# Default — auto-detects everything
js = JSAT(repo=".")

# Explicit AI provider
js = JSAT(repo=".", ai_provider="ollama", model="phi3:mini")

# Verbose logging for debugging
js = JSAT(repo=".", log_level="DEBUG")

# Explicit config file
js = JSAT(repo="/path/to/project", config="/etc/jsat/config.yaml")
```

---

## Methods

### `index`

Build or update the codebase graph. Blocks until indexing is complete.

```python
result = js.index(
    path=None,
    branch="HEAD",
    force=False,
    languages=None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str \| Path \| None` | `None` | Directory to index. Defaults to repo root |
| `branch` | `str` | `"HEAD"` | Git branch to index |
| `force` | `bool` | `False` | Re-index all files, ignoring incremental cache |
| `languages` | `list[str] \| None` | `None` | Restrict to specific languages, e.g. `["python", "go"]` |

Returns `IndexResult`:

```python
class IndexResult:
    nodes_indexed: int
    edges_indexed: int
    duration_ms: int
    languages: list[str]
    commit: str
    repo_path: str
```

```python
result = js.index()
print(f"Indexed {result.nodes_indexed} nodes in {result.duration_ms}ms")

result = js.index(path="src/payments/", force=True, languages=["python"])
```

---

### `index_stream`

Stream progress events while indexing. Yields `IndexEvent` objects.

```python
gen = js.index_stream(path=None, branch="HEAD")
```

Each `IndexEvent`:

```python
class IndexEvent:
    phase: str           # "parsing" | "embedding" | "storing" | "done"
    progress_pct: float  # 0.0 to 100.0
    message: str
    files_done: int
    files_total: int
```

```python
for event in js.index_stream():
    print(f"[{event.phase}] {event.progress_pct:.0f}% — {event.message}")
```

---

### `query`

Natural language query over the indexed codebase graph.

```python
result = js.query(
    question,
    context_budget=8192,
    service=None,
    ithinking=False,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `question` | `str` | (required) | Natural language question |
| `context_budget` | `int` | `8192` | Maximum tokens of graph context to include |
| `service` | `str \| None` | `None` | Scope query to a specific service |
| `ithinking` | `bool` | `False` | Enable IThinking structured planning |

Returns `QueryResult`:

```python
class QueryResult:
    answer: str
    sources: list[str]    # file paths / node IDs used to answer
    confidence: float     # 0.0 to 1.0
    tokens_used: int
```

```python
result = js.query("what calls the refund endpoint?")
print(result.answer)
for source in result.sources:
    print(f"  source: {source}")

result = js.query(
    "which services write to the orders table?",
    service="order_service",
    context_budget=4096,
)
```

---

### `blast_radius`

Trace the downstream impact of a change to a file or symbol.

```python
report = js.blast_radius(
    target,
    diff=None,
    max_depth=5,
    severity_filter=None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target` | `str` | (required) | File path or symbol name |
| `diff` | `str \| None` | `None` | Raw git diff string. If provided, `target` is derived from the diff |
| `max_depth` | `int` | `5` | Maximum graph traversal depth |
| `severity_filter` | `list[str] \| None` | `None` | Include only these severities: `["breaking", "degraded", "warning", "safe"]` |

Returns `BlastRadiusReport`:

```python
class BlastRadiusReport:
    target: str
    impacts: list[ImpactItem]
    summary: dict[str, int]   # {"breaking": 2, "degraded": 5, ...}
    mermaid_diagram: str
    duration_ms: int

class ImpactItem:
    node_id: str
    node_type: str
    node_name: str
    file: str | None
    severity: str             # "breaking" | "degraded" | "warning" | "safe"
    path: list[str]           # edge types traversed
    depth: int
    owner: str | None
    reason: str
```

```python
report = js.blast_radius("src/payment/refund.py")

for item in report.impacts:
    print(f"{item.severity:10} {item.node_name}")

print(f"Summary: {report.summary}")
# Summary: {'breaking': 2, 'degraded': 5, 'warning': 12, 'safe': 31}

# Only breaking and degraded
report = js.blast_radius(
    "PaymentService.process_refund",
    severity_filter=["breaking", "degraded"],
    max_depth=3,
)

# From a git diff
diff = subprocess.check_output(["git", "diff", "main"]).decode()
report = js.blast_radius("", diff=diff)
```

---

### `security_review`

Run a security analysis. Requires `pip install jsat[standard]` for the Semgrep-backed scan.

```python
report = js.security_review(
    path=".",
    severity_threshold="medium",
    include_deps=True,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str \| Path` | `"."` | Directory or file to scan |
| `severity_threshold` | `str` | `"medium"` | Minimum severity to include: `"critical"`, `"high"`, `"medium"`, `"low"`, `"info"` |
| `include_deps` | `bool` | `True` | Include CVE scan of dependencies |

Returns `SecurityReport`:

```python
class SecurityReport:
    findings: list[SecurityFinding]
    cves: list[CVEFinding]
    secrets_found: int
    duration_ms: int

class SecurityFinding:
    file: str
    line: int
    category: str
    severity: str    # "critical" | "high" | "medium" | "low" | "info"
    title: str
    description: str
    proof_of_concept: str | None
    remediation: str
    rule_id: str

class CVEFinding:
    package: str
    version: str
    cve_id: str
    cvss: float
    severity: str
    fix_version: str | None
    description: str
```

```python
from jsat import JSAT
from jsat._exceptions import ProfileError

js = JSAT(repo=".")
try:
    report = js.security_review("src/api/", severity_threshold="high")
except ProfileError as e:
    print(f"Need jsat[standard]: {e}")
else:
    critical = [f for f in report.findings if f.severity == "critical"]
    print(f"Critical findings: {len(critical)}")
```

---

### `investigate_incident`

Investigate a production incident. Returns ranked root-cause hypotheses.

```python
report = js.investigate_incident(
    description,
    since="72h",
    services=None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `description` | `str` | (required) | Description of the incident |
| `since` | `str` | `"72h"` | How far back to search git history. Accepts `"24h"`, `"72h"`, `"7d"`, etc. |
| `services` | `list[str] \| None` | `None` | Limit search to these services |

Returns `IncidentReport`:

```python
class IncidentReport:
    description: str
    hypotheses: list[Hypothesis]
    mitigation_steps: list[str]
    runbook: str | None
    duration_ms: int

class Hypothesis:
    score: float              # 0.0 to 1.0; higher = more likely
    commit_hash: str
    commit_summary: str
    author: str
    timestamp: str            # ISO 8601
    evidence: list[str]
    recommended_action: str
```

```python
report = js.investigate_incident(
    "500 errors on checkout since 14:00",
    since="24h",
    services=["checkout_service", "payment_service"],
)

for h in report.hypotheses[:3]:
    print(f"Score {h.score:.2f}: {h.commit_summary}")
    print(f"  Commit: {h.commit_hash} by {h.author}")
    print(f"  Action: {h.recommended_action}")
```

---

### `export`

Export the index to a portable zip archive.

```python
manifest = js.export(
    output,
    compress_level=6,
    encrypt=False,
    password=None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output` | `str \| Path` | (required) | Output path, e.g. `"backup.jsat.zip"` |
| `compress_level` | `int` | `6` | ZIP compression level 0-9 |
| `encrypt` | `bool` | `False` | Encrypt the archive (not yet implemented) |
| `password` | `str \| None` | `None` | Encryption password (not yet implemented) |

Returns `ExportManifest`:

```python
class ExportManifest:
    path: str
    size_mb: float
    nodes: int
    edges: int
    commit: str
    jsat_version: str
    created_at: str
```

```python
manifest = js.export("team-index.jsat.zip", compress_level=9)
print(f"Exported {manifest.size_mb:.1f} MB — {manifest.nodes} nodes")
```

---

### `JSAT.from_import` (classmethod)

Restore a JSAT instance from an exported archive.

```python
js = JSAT.from_import(archive, password=None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `archive` | `str \| Path` | (required) | Path to `.jsat.zip` archive |
| `password` | `str \| None` | `None` | Decryption password if encrypted |

```python
from jsat import JSAT

js = JSAT.from_import("team-index.jsat.zip")
print(js.index_status)
# {'nodes': 1842, 'edges': 4391, 'commit': 'a3f91cc', 'is_fresh': True}
```

---

### `switch_ai`

Switch the AI provider mid-session without reconstructing the `JSAT` instance.

```python
provider_used, model_used, is_ok = js.switch_ai(provider, model=None, base_url=None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `provider` | `str` | (required) | Provider alias (see table below) |
| `model` | `str \| None` | `None` | Override the default model |
| `base_url` | `str \| None` | `None` | Override the base URL (for `custom` / `compat`) |

Supported aliases:

| Alias | Provider | Default model |
|-------|---------|--------------|
| `claude` | `claude_cli` (if installed) or `anthropic` | `claude-sonnet-4-6` |
| `claude-api` | `anthropic` | `claude-sonnet-4-6` |
| `claude-cli` | `claude_cli` | `claude-sonnet-4-6` |
| `anthropic` | `anthropic` | `claude-sonnet-4-6` |
| `haiku` | `anthropic` | `claude-haiku-4-5-20251001` |
| `opus` | `anthropic` | `claude-opus-4-8` |
| `gpt` / `openai` | `openai` | `gpt-4o` |
| `gpt4mini` | `openai` | `gpt-4o-mini` |
| `ollama` / `llama` | `ollama` | `llama3.2` |
| `phi` | `ollama` | `phi3:mini` |
| `gemini` | `openai_compat` | `gemini-1.5-flash` |
| `gemini-pro` | `openai_compat` | `gemini-1.5-pro` |
| `lmstudio` | `openai_compat` | `local-model` |

```python
js.switch_ai("ollama", model="phi3:mini")
js.switch_ai("anthropic")
js.switch_ai("gemini")
js.switch_ai("custom", base_url="http://my-server:8080/v1")
```

---

### `index_status` (property)

Quick snapshot of the current graph state. Does not re-index.

```python
status = js.index_status
# {'nodes': 1842, 'edges': 4391, 'commit': 'a3f91cc', 'is_fresh': True}
```

Returns a `dict` with keys `nodes`, `edges`, `commit`, `is_fresh`. Returns zeros and `is_fresh: False` if the graph is not available.

---

### `doctor`

Full health check. Returns the same data as `jsat doctor --json`.

```python
report = js.doctor()
```

Returns a `dict` with keys:

- `version` — JSAT version string
- `system` — `ram_gb`, `cpu_arch`, `gpu`, `is_ci`
- `profile` — detected profile: `"solo"`, `"team"`, `"ci"`, `"raspberry-pi"`
- `services` — `ollama`, `neo4j`, `qdrant`, `redis` — each with `running: bool`
- `graph` — `ok`, `backend`, `error`
- `ai` — `ok`, `provider`, `model`, `error`, `available_providers`
- `index` — same as `index_status`

```python
report = js.doctor()
print(f"Profile: {report['profile']}")
print(f"Graph: {report['graph']}")
print(f"AI: {report['ai']['provider']}/{report['ai']['model']}")
for p in report['ai']['available_providers']:
    print(f"  {p['name']}: available={p['available']}")
```

---

## Async Usage

JSAT does not expose a native async API, but the blocking calls can be run in a thread pool for async contexts:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from jsat import JSAT

js = JSAT(repo=".")
executor = ThreadPoolExecutor(max_workers=2)

async def query_async(question: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, js.query, question)

async def index_async():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, js.index)

async def main():
    await index_async()
    result = await query_async("what does this project do?")
    print(result.answer)

asyncio.run(main())
```

---

## Error Handling

All JSAT errors inherit from `jsat._exceptions.JSATError`.

```python
from jsat import JSAT
from jsat._exceptions import JSATError, ProfileError, GraphError, AIError
```

| Exception | When raised |
|-----------|------------|
| `JSATError` | Base class for all JSAT errors |
| `ProfileError` | Required install extra is missing (e.g. `jsat[standard]`) |
| `GraphError` | Graph backend not available or query failed |
| `AIError` | AI provider not available or request failed |

```python
from jsat import JSAT
from jsat._exceptions import ProfileError, AIError

js = JSAT(repo=".")

try:
    report = js.security_review(".")
except ProfileError as e:
    print(f"Install jsat[standard] for security scanning: {e}")

try:
    result = js.query("what calls the auth endpoint?")
except AIError as e:
    # Falls back to graph-only answer if AI is unavailable
    print(f"AI unavailable, using graph-only mode: {e}")

# General catch-all
try:
    js.index()
except JSATError as e:
    print(f"JSAT error: {e}")
```

---

## Complete Example

```python
import sys
from jsat import JSAT
from jsat._exceptions import ProfileError

def main():
    js = JSAT(repo=".", ai_provider="ollama", log_level="INFO")

    # Index the project
    print("Indexing...")
    result = js.index()
    print(f"Indexed {result.nodes_indexed} nodes, {result.edges_indexed} edges")

    # Natural language query
    answer = js.query("what does this project do?")
    print(f"\nProject summary:\n{answer.answer}")

    # Blast radius
    report = js.blast_radius("src/payment/refund.py", max_depth=3)
    print(f"\nBlast radius: {report.summary}")

    # Security scan
    try:
        sec = js.security_review(".", severity_threshold="high")
        print(f"\nHigh+ severity findings: {len(sec.findings)}")
    except ProfileError:
        print("\nSkipping security scan (requires jsat[standard])")

    # Export
    manifest = js.export("backup.jsat.zip")
    print(f"\nExported to {manifest.path} ({manifest.size_mb:.1f} MB)")

if __name__ == "__main__":
    main()
```
