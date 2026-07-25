"""Tests for jsat._models. No external deps beyond pydantic."""
import pytest
from jsat._models import (
    JSATConfig, GraphConfig, AIConfig, CacheConfig, EmbeddingsConfig,
    SystemProfile, IndexResult, BlastRadiusReport, ImpactItem,
)


@pytest.mark.ci
def test_jsat_config_defaults():
    cfg = JSATConfig()
    assert cfg.graph.backend == "sqlite"
    assert cfg.ai.provider == "ollama"
    assert cfg.cache.backend == "memory"
    assert cfg.embeddings.provider == "local"


@pytest.mark.ci
def test_jsat_config_from_dict():
    cfg = JSATConfig.model_validate({
        "graph": {"backend": "neo4j"},
        "ai": {"provider": "anthropic", "model": "claude-opus-4-8"},
    })
    assert cfg.graph.backend == "neo4j"
    assert cfg.ai.provider == "anthropic"
    assert cfg.ai.model == "claude-opus-4-8"
    assert cfg.cache.backend == "memory"  # default preserved


@pytest.mark.ci
def test_system_profile():
    p = SystemProfile(
        ram_gb=16.0, cpu_arch="arm64", gpu="metal", is_ci=False,
        ollama_up=True, neo4j_up=False, qdrant_up=False, redis_up=False,
        detected_profile="solo",
    )
    assert p.detected_profile == "solo"
    assert p.gpu == "metal"


@pytest.mark.ci
def test_index_result():
    r = IndexResult(
        nodes_indexed=100, edges_indexed=250, duration_ms=4200,
        languages=["python", "go"], commit="abc123", repo_path="/my/repo",
    )
    assert r.nodes_indexed == 100
    assert "python" in r.languages


@pytest.mark.ci
def test_blast_radius_report():
    impact = ImpactItem(
        node_id="src/pay.py::refund", node_type="Function", node_name="refund",
        severity="breaking", path=["CALLS"], depth=1,
    )
    report = BlastRadiusReport(
        target="src/pay.py", impacts=[impact],
        summary={"breaking": 1, "degraded": 0, "warning": 0, "safe": 0},
    )
    assert report.summary["breaking"] == 1
    assert report.impacts[0].severity == "breaking"


@pytest.mark.ci
def test_config_model_copy():
    cfg = JSATConfig()
    new_cfg = cfg.model_copy(update={"ai": cfg.ai.model_copy(update={"provider": "openai"})})
    assert new_cfg.ai.provider == "openai"
    assert cfg.ai.provider == "ollama"  # original unchanged
