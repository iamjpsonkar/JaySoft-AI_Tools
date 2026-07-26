"""jsat.skills.registry — Skills discovery, registration, and dispatch."""
from __future__ import annotations

from pathlib import Path
from typing import Any


class SkillsRegistry:
    """Discovers YAML skill manifests and dispatches skill invocations."""

    def __init__(self, skills_dir: str | Path = "skills/") -> None:
        import structlog
        self._log = structlog.get_logger(__name__)
        self._dir = Path(skills_dir)
        self._skills: dict[str, dict] = {}
        self._auto_discover()
        self._log.info("skills_registry_init", dir=str(self._dir),
                       count=len(self._skills))

    def _auto_discover(self) -> None:
        if not self._dir.exists():
            return
        for f in self._dir.glob("*.yaml"):
            try:
                self.import_skill(f)
            except Exception as e:
                self._log.warning("skills_discover_error", file=str(f), error=str(e))

    def import_skill(self, path: Path) -> None:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        name = data.get("name") or path.stem
        self._skills[name] = data
        self._log.info("skill_registered", name=name,
                       version=data.get("version", "?"),
                       source_type=data.get("source", {}).get("type", "?"))

    def list_skills(self) -> list[dict]:
        return [
            {"name": k, "description": v.get("description", ""),
             "version": v.get("version", "0.1.0"),
             "source_type": v.get("source", {}).get("type", "?")}
            for k, v in self._skills.items()
        ]

    def run(self, name: str, **kwargs: Any) -> str:
        import subprocess

        from jsat._exceptions import SkillExecutionError, SkillNotFound

        if name not in self._skills:
            raise SkillNotFound(name=name)

        skill = self._skills[name]
        src = skill.get("source", {})
        src_type = src.get("type", "")
        self._log.info("skill_run", name=name, type=src_type, kwargs=list(kwargs.keys()))

        try:
            if src_type == "script":
                result = subprocess.run(
                    [src["path"]], capture_output=True, text=True,
                    input=str(kwargs), timeout=60,
                )
                output = result.stdout or result.stderr
                self._log.info("skill_run_done", name=name, output_len=len(output))
                return output

            if src_type in ("claude_skill", "codex_skill"):
                return f"[{src_type} '{name}' — invoke via Claude Code: /{name}]"

            if src_type == "mcp_tool":
                return f"[MCP tool '{name}' — dispatch via MCP server]"

            if src_type == "jsat_builtin":
                return f"[Built-in skill '{name}' — use jsat.{name}() in SDK]"

            return f"[Skill '{name}' type='{src_type}' — dispatch not implemented in v0.1]"

        except Exception as e:
            self._log.error("skill_run_error", name=name, error=str(e))
            raise SkillExecutionError(f"Skill '{name}' failed", name=name, detail=str(e)) from e
