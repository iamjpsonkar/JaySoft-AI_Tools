"""jsat.tools.query — Natural language query over the codebase graph."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from jsat.tools import BaseTool

if TYPE_CHECKING:
    from jsat._models import QueryResult


class QueryTool(BaseTool):
    """Answers natural language questions using graph context + AI."""

    def run(
        self,
        question: str,
        context_budget: int = 8192,
        service: str | None = None,
        thinking: bool = False,
    ) -> QueryResult:
        import structlog

        from jsat._models import QueryResult

        log = structlog.get_logger(__name__)
        log.info("query_start", question=question[:80], context_budget=context_budget)
        t0 = time.monotonic()

        context = self._build_context(question, context_budget, service)
        prompt = self._build_prompt(question, context)

        try:
            answer = self._ai.complete(prompt, max_tokens=2048, temperature=0.1)  # type: ignore[union-attr]
            tokens_used = len(prompt.split()) + len(answer.split())  # rough estimate
        except Exception as e:
            log.error("query_ai_error", error=str(e))
            answer = f"[AI unavailable: {e}]"
            tokens_used = 0

        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("query_done", answer_len=len(answer), duration_ms=duration_ms)

        return QueryResult(
            answer=answer,
            sources=self._extract_sources(context),
            tokens_used=tokens_used,
        )

    def _build_context(self, question: str, budget: int, service: str | None) -> str:
        """Pull relevant graph nodes for the question (simple keyword approach in v0.1)."""
        lines = []
        try:
            # Get all services
            services = self._graph.query("MATCH (n:Service) RETURN n")
            for row in services[:10]:
                props = row.get("properties", {})
                lines.append(f"Service: {props.get('name','?')} ({props.get('language','?')})")

            # Get endpoints
            endpoints = self._graph.query("MATCH (n:Endpoint) RETURN n")
            for row in endpoints[:20]:
                props = row.get("properties", {})
                lines.append(f"Endpoint: {props.get('method','GET')} {props.get('route','?')}")

            # Get total stats
            n = self._graph.node_count()
            e = self._graph.edge_count()
            lines.insert(0, f"Graph: {n} nodes, {e} edges")
        except Exception:
            lines = ["[Graph context unavailable]"]

        ctx = "\n".join(lines)
        # Truncate to budget (rough token estimate: 4 chars per token)
        max_chars = budget * 4
        return ctx[:max_chars] if len(ctx) > max_chars else ctx

    def _build_prompt(self, question: str, context: str) -> str:
        return (
            f"You are a codebase intelligence assistant. "
            f"Answer the question using the graph context below.\n\n"
            f"CODEBASE CONTEXT:\n{context}\n\n"
            f"QUESTION: {question}\n\n"
            f"ANSWER (be concise and specific):"
        )

    def _extract_sources(self, context: str) -> list[str]:
        return [line for line in context.splitlines() if line.startswith("Service:")][:5]
