"""jsat.tools.feature — Tool 3: Feature Helper (Spec-to-Implementation)."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from jsat.tools import BaseTool


@dataclass
class FeaturePlan:
    description: str
    affected_services: list[str]
    implementation_steps: list[str]
    files_to_modify: list[str]
    test_plan: list[str]
    estimated_complexity: str  # "low"|"medium"|"high"
    duration_ms: int


class FeatureTool(BaseTool):
    """Produces a structured implementation plan from a feature description."""

    def run(self, description: str) -> FeaturePlan:
        import structlog
        log = structlog.get_logger(__name__)
        log.info("feature_start", description=description[:80])
        t0 = time.monotonic()

        context = self._load_context()
        prompt = self._build_prompt(description, context)

        try:
            response = self._ai.complete(prompt, max_tokens=2048)  # type: ignore[union-attr]
        except Exception as e:
            log.error("feature_ai_error", error=str(e))
            response = "{}"

        plan = self._parse(response)
        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info(
            "feature_done",
            complexity=plan.get("estimated_complexity"),
            duration_ms=duration_ms,
        )

        return FeaturePlan(
            description=description,
            affected_services=plan.get("affected_services", []),
            implementation_steps=plan.get("implementation_steps", []),
            files_to_modify=plan.get("files_to_modify", []),
            test_plan=plan.get("test_plan", []),
            estimated_complexity=plan.get("estimated_complexity", "medium"),
            duration_ms=duration_ms,
        )

    def _load_context(self) -> str:
        try:
            services = self._graph.query(
                "SELECT id, properties FROM nodes WHERE label = 'Service'", {}
            )
            endpoints = self._graph.query(
                "SELECT id, properties FROM nodes WHERE label = 'Endpoint'", {}
            )
            lines = [f"Nodes: {self._graph.node_count()}, Edges: {self._graph.edge_count()}"]
            for s in services[:5]:
                props = s.get("properties") or {}
                lines.append(f"Service: {props.get('name', '?')} ({props.get('language', '?')})")
            for e in endpoints[:10]:
                p = e.get("properties") or {}
                lines.append(f"Endpoint: {p.get('method', '?')} {p.get('route', '?')}")
            return "\n".join(lines)
        except Exception:
            return "[Graph context unavailable]"

    def _build_prompt(self, description: str, context: str) -> str:
        return (
            "You are a senior software engineer planning a feature implementation.\n"
            "You have the codebase graph context below — use it to give specific, grounded "
            "answers. Reference actual service names, file paths, and function names from "
            "the context. Do not invent files or services not listed.\n\n"
            f"CODEBASE CONTEXT:\n{context}\n\n"
            f"FEATURE REQUEST: {description}\n\n"
            "Using ONLY what exists in the codebase context, return a JSON plan:\n"
            '{"affected_services": ["exact service names from context"],'
            ' "implementation_steps": ["numbered steps referencing real files/functions"],'
            ' "files_to_modify": ["exact file paths from context"],'
            ' "test_plan": ["specific test scenarios for the named functions/endpoints"],'
            ' "estimated_complexity": "low|medium|high"}'
        )

    def _parse(self, response: str) -> dict:
        m = re.search(r"\{.*\}", response, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        return {"affected_services": [], "implementation_steps": [response.strip()],
                "files_to_modify": [], "test_plan": [], "estimated_complexity": "medium"}
