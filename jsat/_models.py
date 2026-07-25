"""jsat._models — All Pydantic models. No circular imports. Import from here."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── System detection ──────────────────────────────────────────────────────────

class SystemProfile(BaseModel):
    ram_gb: float
    cpu_arch: str           # "arm64" | "x86_64" | "aarch64"
    gpu: str                # "cuda" | "metal" | "none"
    is_ci: bool
    ollama_up: bool
    neo4j_up: bool
    qdrant_up: bool
    redis_up: bool
    detected_profile: str   # "solo" | "team" | "ci" | "raspberry-pi"


# ── Config sub-models ─────────────────────────────────────────────────────────

class GraphConfig(BaseModel):
    backend: Literal["sqlite", "neo4j", "lightgraph"] = "sqlite"
    path: str = ".jsat/graph/graph.db"
    remote_uri: str | None = None
    username: str = "neo4j"
    password_env: str = "NEO4J_PASSWORD"
    max_nodes: int = 5_000_000
    max_edges: int = 20_000_000


class VectorStoreConfig(BaseModel):
    backend: Literal["sqlite-vss", "qdrant", "pgvector"] = "sqlite-vss"
    path: str = ".jsat/vectors/"
    remote_uri: str | None = None
    collection: str = "jsat_code"
    api_key_env: str = "QDRANT_API_KEY"


class EmbeddingsConfig(BaseModel):
    provider: Literal["local", "openai", "huggingface", "none"] = "local"
    model: str = "nomic-embed-code"
    api_key_env: str = "OPENAI_API_KEY"
    dimensions: int = 768
    batch_size: int = 64
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)


class AIConfig(BaseModel):
    provider: Literal["ollama", "anthropic", "openai", "openai_compat", "none"] = "ollama"
    model: str = "llama3.2"
    api_key_env: str | None = None
    base_url: str | None = None
    max_tokens: int = 8192
    temperature: float = 0.1
    timeout_seconds: int = 120
    retry_attempts: int = 3


class CacheConfig(BaseModel):
    enabled: bool = True
    backend: Literal["memory", "disk", "redis"] = "memory"
    redis_uri: str | None = None
    similarity_threshold: float = 0.95
    ttl_seconds: int = 3600
    max_memory_mb: int = 512
    disk_path: str = ".jsat/cache/"


class IndexerConfig(BaseModel):
    languages: list[str] = Field(default_factory=lambda: ["python", "javascript", "go"])
    exclude_patterns: list[str] = Field(default_factory=lambda: [
        ".git", "node_modules", "__pycache__", ".venv", "vendor", "dist", "build",
    ])
    incremental: bool = True
    git_hooks: bool = True
    max_file_size_kb: int = 500
    follow_symlinks: bool = False
    embedding_batch_size: int = 64


class MCPConfig(BaseModel):
    mode: Literal["embedded", "server"] = "embedded"
    port: int = 8765
    auth: bool = False
    auth_token_env: str = "JSAT_MCP_TOKEN"


class IThinkingConfig(BaseModel):
    enabled: bool = True
    mode: Literal["interactive", "silent", "report-only"] = "interactive"
    prompt_review: bool = True
    decomposition_review: bool = True
    assumption_audit: bool = True
    local_first: bool = True
    gate_level: Literal["low", "medium", "high"] = "medium"
    reflection: bool = True
    knowledge_update: bool = True


class LogConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["text", "json"] = "text"
    file: str | None = None


class PrivacyConfig(BaseModel):
    """Section L privacy settings — PII handling and audit logging."""
    hash_pii: bool = False          # hash PII fields before storing in knowledge base
    no_telemetry: bool = False      # disable anonymous usage telemetry
    audit_log: bool = False         # write audit log of all queries and tool calls
    audit_log_path: str = ".jsat/audit.log"


class SecurityConfig(BaseModel):
    """Security thresholds for the security review tool."""
    cvss_threshold: float = 7.0
    secret_entropy_threshold: float = 4.5
    block_on_critical: bool = True
    sarif_output: bool = True


class ReviewConfig(BaseModel):
    """Multi-model code review configuration."""
    models: list[dict] = Field(default_factory=list)
    parallel_timeout_seconds: int = 90
    dedup_threshold: float = 0.85
    min_confidence: str = "medium"


class SkillsConfig(BaseModel):
    dir: str = "skills/"
    auto_discover: bool = True
    override_builtins: bool = True
    clusters: dict[str, list[str]] = Field(default_factory=dict)


class JSATConfig(BaseModel):
    """Root config model. Loaded from .jsat/config.yaml."""
    version: str = "1"
    project_name: str = "unnamed"
    project_root: str = "."
    graph: GraphConfig = Field(default_factory=GraphConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    ithinking: IThinkingConfig = Field(default_factory=IThinkingConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)


# ── Tool output models ────────────────────────────────────────────────────────

class IndexEvent(BaseModel):
    phase: str   # "parsing" | "embedding" | "storing" | "done"
    progress_pct: float
    message: str
    files_done: int = 0
    files_total: int = 0


class IndexResult(BaseModel):
    nodes_indexed: int
    edges_indexed: int
    duration_ms: int
    languages: list[str]
    commit: str
    repo_path: str


class ImpactItem(BaseModel):
    node_id: str
    node_type: str
    node_name: str
    file: str | None = None
    severity: Literal["breaking", "degraded", "warning", "safe"]
    path: list[str]   # edge types traversed
    depth: int
    owner: str | None = None
    reason: str = ""


class BlastRadiusReport(BaseModel):
    target: str
    impacts: list[ImpactItem]
    summary: dict[str, int]   # {"breaking": 2, "degraded": 5, ...}
    mermaid_diagram: str = ""
    duration_ms: int = 0


class SecurityFinding(BaseModel):
    file: str
    line: int
    category: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    title: str
    description: str
    proof_of_concept: str | None = None
    remediation: str = ""
    rule_id: str = ""


class CVEFinding(BaseModel):
    package: str
    version: str
    cve_id: str
    cvss: float
    severity: str
    fix_version: str | None = None
    description: str = ""


class SecurityReport(BaseModel):
    findings: list[SecurityFinding]
    cves: list[CVEFinding]
    secrets_found: int
    duration_ms: int = 0


class Hypothesis(BaseModel):
    score: float
    commit_hash: str
    commit_summary: str
    author: str = ""
    timestamp: str = ""
    evidence: list[str]
    recommended_action: str = ""


class IncidentReport(BaseModel):
    description: str
    hypotheses: list[Hypothesis]
    mitigation_steps: list[str]
    runbook: str | None = None
    duration_ms: int = 0


class QueryResult(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    tokens_used: int = 0


class ExportManifest(BaseModel):
    path: str
    size_mb: float
    nodes: int
    edges: int
    commit: str
    jsat_version: str
    created_at: str
