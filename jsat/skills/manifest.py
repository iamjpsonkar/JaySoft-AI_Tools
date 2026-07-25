"""jsat.skills.manifest — SkillManifest Pydantic model."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SkillInput(BaseModel):
    name: str
    type: str = "string"  # "string"|"integer"|"boolean"|"object"
    description: str = ""
    required: bool = False


class SkillOutput(BaseModel):
    name: str
    type: str = "markdown"  # "markdown"|"json"|"text"
    description: str = ""


class SkillSource(BaseModel):
    type: Literal["claude_skill", "codex_skill", "script", "mcp_tool", "jsat_builtin"]
    path: str | None = None        # file path for script / claude_skill / codex_skill
    tool_name: str | None = None   # for mcp_tool type
    builtin_name: str | None = None  # for jsat_builtin type


class SkillManifest(BaseModel):
    """
    YAML manifest for a JSAT skill.

    Example manifest (skills/blast-radius.yaml):

        name: blast-radius
        description: "Trace impact of a code change across services"
        version: "1.0.0"
        source:
          type: claude_skill
          path: .claude/commands/blast-radius.md
        input:
          - name: changed_file
            type: string
            description: "Path to the changed file or diff"
        output:
          - name: impact_report
            type: markdown
        jsat_tool: blast_radius
    """

    name: str
    description: str = ""
    version: str = "0.1.0"
    source: SkillSource
    input: list[SkillInput] = Field(default_factory=list)
    output: list[SkillOutput] = Field(default_factory=list)
    jsat_tool: str | None = None   # maps to js.<jsat_tool>() in the SDK
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> SkillManifest:
        """Load a manifest from a YAML file."""
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def to_mcp_tool(self) -> dict:
        """Convert this manifest into an MCP tool definition dict."""
        properties = {
            inp.name: {"type": inp.type, "description": inp.description}
            for inp in self.input
        }
        required = [inp.name for inp in self.input if inp.required]
        schema: dict = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": schema,
        }
