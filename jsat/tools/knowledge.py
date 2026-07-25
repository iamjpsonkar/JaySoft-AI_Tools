"""jsat.tools.knowledge — Tool 10: Knowledge Base Builder."""
from __future__ import annotations

import datetime
import time
from dataclasses import dataclass, field

from jsat.tools import BaseTool

_LABEL = "KnowledgeEntry"


@dataclass
class KnowledgeResult:
    answer: str
    sources: list[str]
    confidence: float


class KnowledgeTool(BaseTool):
    """Stores and queries project knowledge using the graph + AI synthesis."""

    def query(self, question: str) -> KnowledgeResult:
        import structlog
        log = structlog.get_logger(__name__)
        log.info("knowledge_query", question=question[:80])

        ctx, sources = self._search(question)
        answer = self._synthesize(question, ctx)
        confidence = 0.8 if ctx else 0.4
        return KnowledgeResult(answer=answer, sources=sources, confidence=confidence)

    def add(self, text: str, category: str = "general") -> None:
        import structlog
        log = structlog.get_logger(__name__)
        node_id = f"knowledge::{hash(text)}"
        props = {"text": text, "category": category, "stale": False,
                 "created_at": datetime.datetime.utcnow().isoformat()}
        self._graph.add_node(node_id, _LABEL, props)
        if hasattr(self._graph, "commit"):
            self._graph.commit()  # type: ignore[attr-defined]
        log.info("knowledge_added", node_id=node_id, category=category)

    def list_entries(self, category: str | None = None) -> list[dict]:
        try:
            rows = self._graph.query(f"MATCH (n:{_LABEL}) RETURN n")
            entries = []
            for r in rows:
                props = r.get("properties", {})
                if category and props.get("category") != category:
                    continue
                entries.append({"id": r.get("id", ""), "text": props.get("text", ""),
                                "category": props.get("category", ""), "stale": props.get("stale", False)})
            return entries
        except Exception:
            return []

    def flag_stale(self, entry_id: str) -> None:
        import structlog
        node = self._graph.get_node(entry_id)
        if node:
            props = {**node.get("properties", {}), "stale": True}
            self._graph.add_node(entry_id, _LABEL, props)
            if hasattr(self._graph, "commit"):
                self._graph.commit()  # type: ignore[attr-defined]
        structlog.get_logger(__name__).info("knowledge_flagged_stale", id=entry_id)

    def _search(self, question: str) -> tuple[str, list[str]]:
        try:
            rows = self._graph.query(f"MATCH (n:{_LABEL}) RETURN n")
            keywords = set(question.lower().split())
            scored = []
            for r in rows:
                props = r.get("properties", {})
                if props.get("stale"):
                    continue
                words = set(props.get("text", "").lower().split())
                score = len(keywords & words) / max(len(keywords), 1)
                if score > 0:
                    scored.append((score, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[:5]
            ctx = "\n\n".join(r.get("properties", {}).get("text", "") for _, r in top)
            sources = [r.get("id", "") for _, r in top]
            return ctx, sources
        except Exception:
            return "", []

    def _synthesize(self, question: str, context: str) -> str:
        if self._ai is None:
            return "[No AI provider — install jsat[local] for local AI]"
        try:
            prompt = (
                f"Answer using the context below.\n\nCONTEXT:\n{context}\n\n"
                f"QUESTION: {question}\n\nAnswer concisely:" if context else
                f"Answer: {question}"
            )
            return self._ai.complete(prompt, max_tokens=512)
        except Exception as e:
            return f"[AI error: {e}]"
