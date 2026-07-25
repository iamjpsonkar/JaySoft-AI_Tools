"""Tests for jsat.skills: registry, clusters, manifest. CI-safe."""
from __future__ import annotations
from pathlib import Path
import pytest
from jsat.skills.registry import SkillsRegistry
from jsat.skills.clusters import list_clusters, run_cluster
from jsat.skills.manifest import SkillManifest
from jsat._exceptions import SkillNotFound

MINIMAL_YAML = """\
name: my-skill
description: A test skill.
version: "0.1.0"
source:
  type: claude_skill
  path: .claude/commands/my-skill.md
"""

# Registry
@pytest.mark.ci
def test_registry_empty_dir(tmp_path):
    r = SkillsRegistry(skills_dir=str(tmp_path / "no_dir"))
    assert r.list_skills() == []

@pytest.mark.ci
def test_registry_import_and_list(tmp_path):
    (tmp_path / "my-skill.yaml").write_text(MINIMAL_YAML)
    r = SkillsRegistry(skills_dir=str(tmp_path))
    names = [s["name"] for s in r.list_skills()]
    assert "my-skill" in names

@pytest.mark.ci
def test_registry_run_unknown_raises(tmp_path):
    r = SkillsRegistry(skills_dir=str(tmp_path))
    with pytest.raises(SkillNotFound):
        r.run("nonexistent")

@pytest.mark.ci
def test_registry_run_claude_skill_no_crash(tmp_path):
    (tmp_path / "my-skill.yaml").write_text(MINIMAL_YAML)
    r = SkillsRegistry(skills_dir=str(tmp_path))
    result = r.run("my-skill")
    assert isinstance(result, str)

@pytest.mark.ci
def test_registry_list_returns_dicts(tmp_path):
    (tmp_path / "my-skill.yaml").write_text(MINIMAL_YAML)
    r = SkillsRegistry(skills_dir=str(tmp_path))
    skills = r.list_skills()
    assert all(isinstance(s, dict) and "name" in s for s in skills)

# Clusters
@pytest.mark.ci
def test_list_clusters_has_new_feature():
    assert "new-feature" in list_clusters()

@pytest.mark.ci
def test_list_clusters_has_incident():
    assert "incident" in list_clusters()

@pytest.mark.ci
def test_run_cluster_missing_skills_no_crash(tmp_path):
    r = SkillsRegistry(skills_dir=str(tmp_path))
    msgs = run_cluster("incident", r)
    assert isinstance(msgs, list) and len(msgs) >= 1

@pytest.mark.ci
def test_run_cluster_messages_indicate_skip(tmp_path):
    r = SkillsRegistry(skills_dir=str(tmp_path))
    msgs = run_cluster("incident", r)
    assert all("not installed" in m.lower() or "skipping" in m.lower() or "error" in m.lower()
               for m in msgs)

@pytest.mark.ci
def test_run_cluster_unknown_raises(tmp_path):
    r = SkillsRegistry(skills_dir=str(tmp_path))
    with pytest.raises(ValueError, match="Unknown cluster"):
        run_cluster("nonexistent-cluster", r)

# Manifest
@pytest.mark.ci
def test_manifest_from_yaml(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(MINIMAL_YAML)
    m = SkillManifest.from_yaml(p)
    assert m.name == "my-skill"
    assert m.source.type == "claude_skill"

@pytest.mark.ci
def test_manifest_to_mcp_tool_structure(tmp_path):
    yaml = """\
name: targeted
description: Test with required input.
version: "0.1.0"
source:
  type: claude_skill
input:
  - name: target_path
    description: Path to analyse.
    required: true
"""
    p = tmp_path / "t.yaml"
    p.write_text(yaml)
    m = SkillManifest.from_yaml(p)
    mcp = m.to_mcp_tool()
    assert "inputSchema" in mcp
    assert "target_path" in mcp["inputSchema"].get("required", [])

@pytest.mark.ci
def test_manifest_version_default(tmp_path):
    yaml = "name: x\nsource:\n  type: script\n  path: ./x.sh\n"
    p = tmp_path / "x.yaml"
    p.write_text(yaml)
    assert SkillManifest.from_yaml(p).version == "0.1.0"
