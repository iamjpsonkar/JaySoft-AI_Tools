"""jsat.tools.query — Natural language query over the codebase graph."""
from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from jsat._call_context import checkpoint
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
        log.info("query_start", question=question[:80], context_budget=context_budget,
                 service=service, thinking=thinking)
        t0 = time.monotonic()

        checkpoint("query: building graph context")
        context = self._build_context(question, context_budget, service)
        checkpoint(f"query: context ready ({len(context)} chars) — building prompt")
        prompt = self._build_prompt(question, context)

        checkpoint(f"query: calling AI (prompt={len(prompt)} chars, max_tokens=2048)")
        try:
            answer = self._ai.complete(prompt, max_tokens=2048, temperature=0.1)  # type: ignore[union-attr]
            tokens_used = len(prompt.split()) + len(answer.split())  # rough estimate
            log.info("query_ai_success", tokens_used=tokens_used)
            checkpoint(f"query: AI response received ({len(answer)} chars)")
        except Exception as e:
            log.error("query_ai_error", error=str(e))
            checkpoint(f"query: AI error — {e}")
            answer = f"[AI unavailable: {e}]"
            tokens_used = 0

        checkpoint("query: extracting sources from context")
        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("query_done", answer_len=len(answer), duration_ms=duration_ms)

        return QueryResult(
            answer=answer,
            sources=self._extract_sources(context),
            tokens_used=tokens_used,
        )

    def _build_context(self, question: str, budget: int, service: str | None) -> str:
        lines: list[str] = []
        try:
            checkpoint("query: fetching graph node/edge counts")
            n = self._graph.node_count()
            e = self._graph.edge_count()
            lines.append(f"Graph: {n} nodes, {e} edges")

            checkpoint("query: extracting keywords from question")
            keywords = self._extract_keywords(question)
            checkpoint(f"query: keywords={sorted(keywords)[:8]}")

            checkpoint("query: fetching Service nodes")
            services = self._graph.query(
                "SELECT id, properties FROM nodes WHERE label = 'Service'", {}
            )
            checkpoint(f"query: {len(services)} services found")
            for row in services[:10]:
                props = row.get("properties") or {}
                svc_name = props.get("name", "?")
                if service and service.lower() not in svc_name.lower():
                    continue
                lines.append(f"Service: {svc_name} ({props.get('language', '?')})")

            checkpoint("query: fetching Endpoint nodes")
            endpoints = self._graph.query(
                "SELECT id, properties FROM nodes WHERE label = 'Endpoint'", {}
            )
            checkpoint(f"query: {len(endpoints)} endpoints found")
            for row in endpoints[:20]:
                props = row.get("properties") or {}
                lines.append(f"Endpoint: {props.get('method','GET')} {props.get('route','?')}")

            checkpoint("query: fetching Table nodes")
            tables = self._graph.query(
                "SELECT id, properties FROM nodes WHERE label = 'Table'", {}
            )
            checkpoint(f"query: {len(tables)} tables found")
            for row in tables[:10]:
                props = row.get("properties") or {}
                lines.append(f"Table: {props.get('name', '?')}")

            checkpoint("query: fetching Function nodes")
            fn_rows = self._graph.query(
                "SELECT id, properties FROM nodes WHERE label = 'Function'", {}
            )
            checkpoint(f"query: {len(fn_rows)} functions — filtering by relevance")
            relevant_fns = [
                r for r in fn_rows if self._is_relevant(r.get("properties") or {}, keywords)
            ]
            checkpoint(f"query: {len(relevant_fns)} relevant functions")
            for row in relevant_fns[:20]:
                props = row.get("properties") or {}
                name = props.get("name", "?")
                file_ = props.get("file", "?")
                ret = props.get("return_type", "")
                params = props.get("parameters", [])
                param_parts: list[str] = []
                if isinstance(params, list):
                    for p in params[:4]:
                        if isinstance(p, dict):
                            pn = p.get("name", "")
                            pt = p.get("type", "")
                            param_parts.append(f"{pn}:{pt}" if pt else pn)
                param_str = f"({', '.join(param_parts)})" if param_parts else ""
                fn_line = f"Function: {name}{param_str} in {file_}" + (f" -> {ret}" if ret else "")
                lines.append(fn_line)
                doc = props.get("docstring", "")
                if doc:
                    lines.append(f"  # {doc[:80]}")

            checkpoint("query: fetching Class nodes")
            cls_rows = self._graph.query(
                "SELECT id, properties FROM nodes WHERE label = 'Class'", {}
            )
            checkpoint(f"query: {len(cls_rows)} classes — filtering by relevance")
            relevant_cls = [
                r for r in cls_rows if self._is_relevant(r.get("properties") or {}, keywords)
            ]
            checkpoint(f"query: {len(relevant_cls)} relevant classes")
            for row in relevant_cls[:10]:
                props = row.get("properties") or {}
                lines.append(f"Class: {props.get('name','?')} in {props.get('file','?')}")

        except Exception:
            lines = ["[Graph context unavailable]"]

        ctx = "\n".join(lines)
        max_chars = budget * 4
        if len(ctx) > max_chars:
            checkpoint(f"query: context truncated to {max_chars} chars (was {len(ctx)})")
            return ctx[:max_chars]
        return ctx

    def _extract_keywords(self, question: str) -> set[str]:
        stop = {"what", "where", "which", "who", "how", "does", "do", "is", "are",
                "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
                "with", "that", "this", "it", "be", "by", "from", "as", "into",
                "find", "show", "list", "get", "give", "tell", "me"}
        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', question.lower())
        return {w for w in words if w not in stop}

    def _is_relevant(self, props: dict, keywords: set[str]) -> bool:
        if not keywords:
            return True
        searchable = " ".join(str(v) for v in props.values() if isinstance(v, str)).lower()
        return any(kw in searchable for kw in keywords)

    def _build_prompt(self, question: str, context: str) -> str:
        return (
            "You are a precise codebase intelligence assistant. Answer questions about "
            "the codebase using ONLY the provided graph context. Be specific: reference "
            "actual service names, function names, file paths, and data relationships "
            "from the context. If the context lacks sufficient detail to answer "
            "definitively, say so clearly rather than guessing.\n\n"
            f"CODEBASE CONTEXT:\n{context}\n\n"
            f"QUESTION: {question}\n\n"
            f"ANSWER (cite specific names from context; be direct and actionable):"
        )

    def _extract_sources(self, context: str) -> list[str]:
        return [line for line in context.splitlines()
                if line.startswith(("Service:", "Function:", "Table:"))][:8]
