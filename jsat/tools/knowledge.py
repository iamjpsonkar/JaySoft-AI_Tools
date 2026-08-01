"""jsat.tools.knowledge — Tool 10: Knowledge Base Builder.

Two execution modes:
- DEFAULT (no graphiti-core): AI-assisted entity extraction with regex pre-pass.
- TEAM (jsat[team] extra, graphiti-core installed): full Graphiti integration.

Public API (backward-compatible):
    query(question)          -> KnowledgeResult
    add(text, category)      -> None
    list_entries(category)   -> list[dict]
    flag_stale(entry_id)     -> None

New ingestion API:
    ingest_file(path)        -> int   (number of entries ingested)
    ingest_directory(path)   -> int
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jsat._call_context import checkpoint
from jsat.tools import BaseTool

if TYPE_CHECKING:
    pass

_LABEL = "KnowledgeEntry"
_ENTITY_LABEL = "KnowledgeEntity"
_REL_LABEL = "KnowledgeRelation"

# ── Stop-words excluded from keyword index ────────────────────────────────────
_STOP_WORDS = frozenset(
    [
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "not", "no", "nor",
        "and", "or", "but", "if", "then", "else", "for", "of", "to", "in",
        "on", "at", "with", "by", "from", "as", "its", "it", "this", "that",
        "these", "those", "i", "we", "you", "he", "she", "they", "what",
        "which", "who", "when", "where", "how", "why", "our", "their", "your",
        "all", "any", "some", "more", "most",
    ]
)


@dataclass
class KnowledgeResult:
    answer: str
    sources: list[str]
    confidence: float
    entities_found: list[str] = field(default_factory=list)
    stale_flagged: list[str] = field(default_factory=list)


# ── Entity / relation data classes (stored as JSON in node properties) ────────

@dataclass
class Entity:
    name: str
    entity_type: str   # SERVICE | FILE | FUNCTION | CONCEPT | PERSON | TEAM | OTHER
    raw: str           # original mention in text

    def node_id(self, entry_id: str) -> str:
        safe = re.sub(r"[^a-z0-9_]", "_", self.name.lower())
        return f"ke::{safe}"


@dataclass
class Relation:
    source: str   # entity name
    target: str   # entity name
    rel_type: str # USES | OWNS | CALLS | DOCUMENTS | RELATED_TO | etc.


# ── Regex-based pre-extraction (fast, zero-cost, no AI needed) ────────────────

_RE_FILE_PATH = re.compile(r"\b[\w/.-]+\.(py|ts|js|go|rb|java|rs|yaml|yml|json|toml|md)\b")
_RE_FUNC_REF  = re.compile(r"\b([\w]+)\.([\w]+)\(\)")
_RE_SERVICE   = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+Service|[a-z]+-service)\b")
_RE_PERSON    = re.compile(r"@([\w.-]+)")
_RE_CONCEPT   = re.compile(r"\b(ADR|RFC|PR|MR|issue|ticket|incident|runbook|SLA|SLO|SLI|DORA)\b",
                            re.IGNORECASE)
_RE_CODE_REF  = re.compile(r"`([^`]+)`")


def _regex_extract(text: str) -> list[Entity]:
    """Fast regex pass — collects entities before sending to AI."""
    entities: list[Entity] = []
    seen: set[str] = set()

    def _add(name: str, typ: str, raw: str) -> None:
        key = f"{typ}::{name.lower()}"
        if key not in seen:
            seen.add(key)
            entities.append(Entity(name=name, entity_type=typ, raw=raw))

    for m in _RE_FILE_PATH.finditer(text):
        _add(m.group(0), "FILE", m.group(0))

    for m in _RE_FUNC_REF.finditer(text):
        _add(f"{m.group(1)}.{m.group(2)}", "FUNCTION", m.group(0))

    for m in _RE_SERVICE.finditer(text):
        _add(m.group(0), "SERVICE", m.group(0))

    for m in _RE_PERSON.finditer(text):
        _add(m.group(1), "PERSON", m.group(0))

    for m in _RE_CONCEPT.finditer(text):
        _add(m.group(0), "CONCEPT", m.group(0))

    for m in _RE_CODE_REF.finditer(text):
        val = m.group(1).strip()
        if "." in val and not val.endswith("."):
            _add(val, "FUNCTION" if "()" in val or "." in val else "FILE", m.group(0))

    return entities


def _ai_extract_entities(ai: Any, text: str) -> tuple[list[Entity], list[Relation]]:
    """Use the AI provider to extract entities and relations as JSON.

    Returns (entities, relations). Falls back to empty lists on any error.
    """
    prompt = (
        "You are a knowledge extraction engine for a software codebase.\n"
        "Extract named entities and relationships from technical text.\n"
        "Rules: only extract entities EXPLICITLY named in the text. "
        "Prefer FUNCTION for method names, SERVICE for microservices, "
        "FILE for .py/.go/.ts paths, CONCEPT for design patterns.\n"
        "Return ONLY valid JSON (no markdown fences):\n"
        '{"entities": [{"name": str, "type": "SERVICE|FILE|FUNCTION|CONCEPT|PERSON|TEAM|OTHER", "raw": str}],'  # noqa: E501
        ' "relations": [{"source": str, "target": str,'
        ' "rel": "USES|OWNS|CALLS|DOCUMENTS|RELATED_TO|DEPENDS_ON"}]}\n'
        f"TEXT:\n{text[:2000]}"
    )
    try:
        raw = ai.complete(prompt, max_tokens=512, temperature=0.0)
        # Strip markdown fences if the model adds them anyway
        raw = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        data = json.loads(raw)
        entities = [
            Entity(
                name=e.get("name", ""),
                entity_type=e.get("type", "OTHER"),
                raw=e.get("raw", e.get("name", "")),
            )
            for e in data.get("entities", [])
            if e.get("name")
        ]
        relations = [
            Relation(source=r["source"], target=r["target"], rel_type=r.get("rel", "RELATED_TO"))
            for r in data.get("relations", [])
            if r.get("source") and r.get("target")
        ]
        return entities, relations
    except Exception:
        return [], []


def _merge_entities(regex_ents: list[Entity], ai_ents: list[Entity]) -> list[Entity]:
    """Merge regex and AI entities, deduplicating by (type, name)."""
    seen: set[str] = set()
    merged: list[Entity] = []
    for e in regex_ents + ai_ents:
        key = f"{e.entity_type}::{e.name.lower()}"
        if key not in seen:
            seen.add(key)
            merged.append(e)
    return merged


# ── Decay detection helper ────────────────────────────────────────────────────

def _check_code_refs_live(graph: Any, entities: list[Entity]) -> list[str]:
    """Return entity names whose referenced code nodes are gone from the graph."""
    stale: list[str] = []
    for ent in entities:
        if ent.entity_type not in ("FILE", "FUNCTION"):
            continue
        # Build candidate node IDs the indexer would have used
        candidates = [
            f"fn::{ent.name}",
            f"file::{ent.name}",
            ent.name,
        ]
        found = False
        for cid in candidates:
            node = graph.get_node(cid)
            if node is not None:
                found = True
                break
        if not found:
            stale.append(ent.name)
    return stale


# ── Main tool ─────────────────────────────────────────────────────────────────

class KnowledgeTool(BaseTool):
    """Stores and queries project knowledge using the graph + AI synthesis.

    Mode selection:
    - graphiti-core installed (jsat[team])  → self._graphiti_mode = True
    - otherwise                             → AI + regex extraction
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._graphiti_client: Any = None
        self._graphiti_mode = self._try_init_graphiti()

    def _try_init_graphiti(self) -> bool:
        """Attempt to initialise graphiti-core. Return True on success."""
        import structlog
        log = structlog.get_logger(__name__)
        try:
            from graphiti_core import Graphiti  # type: ignore[import]  # noqa: F401
            log.info("knowledge_graphiti_mode", mode="graphiti-core")
            # Defer actual client creation until first use (needs event loop)
            return True
        except ImportError:
            log.info("knowledge_graphiti_mode", mode="regex+ai",
                     hint="install jsat[team] for full Graphiti integration")
            return False

    # ── Public API ────────────────────────────────────────────────────────────

    def query(self, question: str) -> KnowledgeResult:
        import structlog
        log = structlog.get_logger(__name__)
        log.info("knowledge_query_start", question=question[:120])
        checkpoint(f"knowledge: query start — '{question[:80]}'")
        t0 = time.monotonic()

        mode = "graphiti" if self._graphiti_mode else "regex+ai"
        checkpoint(f"knowledge: using {mode} query mode")
        if self._graphiti_mode:
            result = self._query_graphiti(question)
        else:
            result = self._query_default(question)

        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info(
            "knowledge_query_done",
            sources=len(result.sources),
            confidence=result.confidence,
            entities_found=len(result.entities_found),
            stale_flagged=len(result.stale_flagged),
            duration_ms=duration_ms,
        )
        checkpoint(
            f"knowledge: DONE — confidence={result.confidence:.2f} "
            f"sources={len(result.sources)} entities={len(result.entities_found)} "
            f"stale_flagged={len(result.stale_flagged)} answer_len={len(result.answer)} "
            f"{duration_ms}ms"
        )
        return result

    def add(self, text: str, category: str = "general") -> None:
        import structlog
        log = structlog.get_logger(__name__)

        if not text or not text.strip():
            log.warning("knowledge_add_empty", category=category)
            return

        # Stable deterministic ID: hash of (category, text)
        entry_id = "knowledge::" + hashlib.sha256(
            f"{category}::{text}".encode()
        ).hexdigest()[:16]

        log.info("knowledge_add_start", entry_id=entry_id, category=category,
                 text_len=len(text))

        # Entity extraction
        entities, relations = self._extract(text)
        log.debug("knowledge_entities_extracted", count=len(entities),
                  relations=len(relations))

        props: dict[str, Any] = {
            "text": text,
            "category": category,
            "stale": False,
            "created_at": datetime.datetime.utcnow().isoformat(),
            "entities": [
                {"name": e.name, "type": e.entity_type, "raw": e.raw}
                for e in entities
            ],
            "relations": [
                {"source": r.source, "target": r.target, "rel": r.rel_type}
                for r in relations
            ],
            "keywords": self._keyword_index(text),
        }

        self._graph.add_node(entry_id, _LABEL, props)

        # Store entity nodes and edges into the graph
        for ent in entities:
            ent_node_id = ent.node_id(entry_id)
            ent_props = {
                "name": ent.name,
                "entity_type": ent.entity_type,
                "raw": ent.raw,
                "source_entry": entry_id,
            }
            self._graph.add_node(ent_node_id, _ENTITY_LABEL, ent_props)
            self._graph.add_edge(entry_id, ent_node_id, "HAS_ENTITY")
            log.debug("knowledge_entity_stored", node_id=ent_node_id, type=ent.entity_type)

        # Store relationship edges between entity nodes
        ent_lookup = {e.name.lower(): e.node_id(entry_id) for e in entities}
        for rel in relations:
            src_id = ent_lookup.get(rel.source.lower())
            tgt_id = ent_lookup.get(rel.target.lower())
            if src_id and tgt_id:
                self._graph.add_edge(src_id, tgt_id, rel.rel_type)
                log.debug("knowledge_relation_stored", source=rel.source,
                          target=rel.target, rel=rel.rel_type)

        if hasattr(self._graph, "commit"):
            self._graph.commit()  # type: ignore[attr-defined]

        log.info("knowledge_add_done", entry_id=entry_id, entities=len(entities),
                 relations=len(relations))

    def list_entries(self, category: str | None = None) -> list[dict]:
        import structlog
        log = structlog.get_logger(__name__)
        log.debug("knowledge_list_entries", category=category)
        try:
            rows = self._graph.query(f"MATCH (n:{_LABEL}) RETURN n")
            entries: list[dict] = []
            for r in rows:
                props = r.get("properties", {})
                if category and props.get("category") != category:
                    continue
                entries.append({
                    "id": r.get("id", ""),
                    "text": props.get("text", ""),
                    "category": props.get("category", ""),
                    "stale": props.get("stale", False),
                    "created_at": props.get("created_at", ""),
                    "entities": props.get("entities", []),
                })
            log.debug("knowledge_list_done", count=len(entries), category=category)
            return entries
        except Exception as exc:
            import structlog as _sl
            _sl.get_logger(__name__).warning("knowledge_list_error", error=str(exc))
            return []

    def flag_stale(self, entry_id: str) -> None:
        import structlog
        log = structlog.get_logger(__name__)
        log.info("knowledge_flag_stale", entry_id=entry_id)
        node = self._graph.get_node(entry_id)
        if node:
            props = {**node.get("properties", {}), "stale": True,
                     "stale_at": datetime.datetime.utcnow().isoformat()}
            self._graph.add_node(entry_id, _LABEL, props)
            if hasattr(self._graph, "commit"):
                self._graph.commit()  # type: ignore[attr-defined]
            log.info("knowledge_flagged_stale", entry_id=entry_id)
        else:
            log.warning("knowledge_flag_stale_not_found", entry_id=entry_id)

    # ── Ingestion API ─────────────────────────────────────────────────────────

    def ingest_file(self, path: Path, category: str | None = None) -> int:
        """Ingest a single markdown (or text) file. Returns number of entries created."""
        import structlog
        log = structlog.get_logger(__name__)

        path = Path(path)
        if not path.exists():
            log.warning("knowledge_ingest_file_missing", path=str(path))
            return 0

        log.info("knowledge_ingest_file_start", path=str(path))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            log.error("knowledge_ingest_file_read_error", path=str(path), error=str(exc))
            return 0

        # Determine category from file name/path heuristics
        if category is None:
            category = self._infer_category(path)

        # Split large files into logical sections
        sections = self._split_sections(text, path)
        count = 0
        for section_text, section_cat in sections:
            if len(section_text.strip()) < 20:
                continue
            self.add(section_text, category=section_cat or category)
            count += 1

        log.info("knowledge_ingest_file_done", path=str(path), entries=count, category=category)
        return count

    def ingest_directory(self, path: Path, pattern: str = "*.md") -> int:
        """Recursively ingest all files matching pattern. Returns total entries."""
        import structlog
        log = structlog.get_logger(__name__)

        path = Path(path)
        if not path.exists():
            log.warning("knowledge_ingest_dir_missing", path=str(path))
            return 0

        files = list(path.rglob(pattern))
        log.info("knowledge_ingest_dir_start", path=str(path), pattern=pattern,
                 file_count=len(files))

        total = 0
        for f in files:
            try:
                total += self.ingest_file(f)
            except Exception as exc:
                log.warning("knowledge_ingest_dir_file_error", file=str(f), error=str(exc))

        log.info("knowledge_ingest_dir_done", path=str(path), total_entries=total)
        return total

    # ── Private: query paths ─────────────────────────────────────────────────

    def _query_default(self, question: str) -> KnowledgeResult:
        """AI + regex extraction query path (no graphiti-core)."""
        import structlog
        log = structlog.get_logger(__name__)

        checkpoint("knowledge: searching and ranking entries")
        ctx_entries, sources = self._search_ranked(question)
        log.debug("knowledge_search_results", count=len(sources))
        checkpoint(f"knowledge: {len(sources)} relevant entries found")

        # Decay detection: check code references in top results
        checkpoint(f"knowledge: running decay detection on {len(ctx_entries)} entries")
        stale_flagged: list[str] = []
        for entry in ctx_entries:
            entry_id = entry.get("id", "")
            if not entry_id:
                continue
            entities_raw = entry.get("properties", {}).get("entities", [])
            entities = [
                Entity(name=e["name"], entity_type=e["type"], raw=e.get("raw", e["name"]))
                for e in entities_raw
                if e.get("name")
            ]
            gone = _check_code_refs_live(self._graph, entities)
            if gone:
                log.info("knowledge_decay_detected", entry_id=entry_id,
                         missing_refs=gone)
                self.flag_stale(entry_id)
                stale_flagged.append(entry_id)

        context = "\n\n---\n\n".join(
            e.get("properties", {}).get("text", "")
            for e in ctx_entries
            if not e.get("properties", {}).get("stale", False)
        )

        ctx_len = sum(len(e.get("properties", {}).get("text", "")) for e in ctx_entries)
        checkpoint(f"knowledge: calling AI synthesis ({ctx_len} chars context)")
        answer = self._synthesize(question, context)
        checkpoint(f"knowledge: AI answer received ({len(answer)} chars)")
        checkpoint("knowledge: estimating confidence score")
        confidence = self._estimate_confidence(question, ctx_entries)
        checkpoint(f"knowledge: confidence={confidence:.2f}")

        # Collect entity names from matched entries for caller context
        entity_names: list[str] = []
        for e in ctx_entries:
            for ent in e.get("properties", {}).get("entities", []):
                n = ent.get("name", "")
                if n and n not in entity_names:
                    entity_names.append(n)

        return KnowledgeResult(
            answer=answer,
            sources=sources,
            confidence=confidence,
            entities_found=entity_names[:20],
            stale_flagged=stale_flagged,
        )

    def _query_graphiti(self, question: str) -> KnowledgeResult:
        """Graphiti-powered query (jsat[team])."""
        import asyncio

        import structlog
        log = structlog.get_logger(__name__)

        try:
            from graphiti_core import Graphiti  # type: ignore[import]

            if self._graphiti_client is None:
                log.info("knowledge_graphiti_client_init")
                # Graphiti needs a Neo4j URI — fall back to default mock if missing
                neo4j_uri = getattr(getattr(self._cfg, "graph", None), "remote_uri", None)
                neo4j_user = getattr(getattr(self._cfg, "graph", None), "username", "neo4j")
                import os
                neo4j_pass = os.environ.get(
                    getattr(getattr(self._cfg, "graph", None), "password_env", "NEO4J_PASSWORD"), ""
                )
                if not neo4j_uri:
                    log.warning(
                        "knowledge_graphiti_no_neo4j",
                        hint="Set graph.remote_uri in config; falling back to regex+ai mode",
                    )
                    return self._query_default(question)

                self._graphiti_client = Graphiti(neo4j_uri, neo4j_user, neo4j_pass)
                log.info("knowledge_graphiti_client_ready", uri=neo4j_uri)

            loop = asyncio.new_event_loop()
            try:
                facts = loop.run_until_complete(
                    self._graphiti_client.search(query=question, num_results=10)
                )
            finally:
                loop.close()

            context = "\n\n".join(
                getattr(f, "fact", str(f)) for f in facts
            )
            sources = [getattr(f, "uuid", str(i)) for i, f in enumerate(facts)]
            answer = self._synthesize(question, context)
            log.info("knowledge_graphiti_query_done", facts=len(facts))
            return KnowledgeResult(
                answer=answer,
                sources=sources,
                confidence=0.85 if facts else 0.4,
                entities_found=[],
                stale_flagged=[],
            )

        except Exception as exc:
            import structlog as _sl
            _sl.get_logger(__name__).warning(
                "knowledge_graphiti_query_failed",
                error=str(exc),
                fallback="regex+ai",
            )
            return self._query_default(question)

    # ── Private: search + ranking ────────────────────────────────────────────

    def _search_ranked(self, question: str) -> tuple[list[dict], list[str]]:
        """Return top-N matching entries + their node IDs, ranked by relevance."""
        import structlog
        log = structlog.get_logger(__name__)

        try:
            rows = self._graph.query(f"MATCH (n:{_LABEL}) RETURN n")
        except Exception as exc:
            log.warning("knowledge_search_graph_error", error=str(exc))
            return [], []

        q_keywords = self._tokenise(question)
        q_lower = question.lower()
        scored: list[tuple[float, dict]] = []

        for r in rows:
            props = r.get("properties", {})
            if props.get("stale"):
                continue

            text = props.get("text", "")
            score = self._score_entry(q_keywords, q_lower, text, props)
            if score > 0:
                scored.append((score, r))

        # If AI is available, re-rank the top candidates
        if self._ai and len(scored) > 3:
            scored = self._ai_rerank(question, scored)
        else:
            scored.sort(key=lambda x: x[0], reverse=True)

        top = scored[:5]
        sources = [r.get("id", "") for _, r in top]
        log.debug("knowledge_search_ranked", candidates=len(scored), returned=len(top))
        return [r for _, r in top], sources

    def _score_entry(
        self,
        q_keywords: set[str],
        q_lower: str,
        text: str,
        props: dict[str, Any],
    ) -> float:
        """Multi-signal relevance score for a single entry."""
        score = 0.0

        # 1. Keyword overlap (Jaccard-like)
        entry_keywords = set(props.get("keywords", self._tokenise(text)))
        if q_keywords and entry_keywords:
            overlap = len(q_keywords & entry_keywords)
            score += 0.5 * overlap / max(len(q_keywords | entry_keywords), 1)

        # 2. Entity name match bonus
        entities = props.get("entities", [])
        for ent in entities:
            name = ent.get("name", "").lower()
            if name and name in q_lower:
                score += 0.3

        # 3. Substring match of question words in text
        text_lower = text.lower()
        for kw in q_keywords:
            if kw in text_lower:
                score += 0.1 / max(len(q_keywords), 1)

        # 4. Recency bonus (newer entries slightly preferred)
        try:
            created = props.get("created_at", "")
            if created:
                dt = datetime.datetime.fromisoformat(created)
                age_days = (datetime.datetime.utcnow() - dt).days
                score += max(0.0, 0.05 - age_days * 0.001)
        except Exception:
            pass

        return round(score, 4)

    def _ai_rerank(
        self, question: str, scored: list[tuple[float, dict]]
    ) -> list[tuple[float, dict]]:
        """Ask the AI to re-rank candidates by relevance to the question."""
        import structlog
        log = structlog.get_logger(__name__)

        # Only re-rank top-10 to keep token usage bounded
        candidates = scored[:10]
        snippets = "\n".join(
            f"[{i}] {r.get('properties', {}).get('text', '')[:200]}"
            for i, (_, r) in enumerate(candidates)
        )
        prompt = (
            "You are a relevance ranker for a software knowledge base.\n"
            f"Question: {question}\n\n"
            "Rank the entries below from MOST to LEAST relevant. "
            "Favor: direct answers, specific technical detail, named functions/services. "
            "Penalize: generic statements, unrelated services.\n"
            "Reply with ONLY the indices in order, comma-separated (e.g.: 2,0,5,1,3).\n\n"
            f"ENTRIES:\n{snippets}"
        )
        try:
            raw = self._ai.complete(prompt, max_tokens=64, temperature=0.0)
            indices = [int(x.strip()) for x in raw.strip().split(",") if x.strip().isdigit()]
            reordered: list[tuple[float, dict]] = []
            seen: set[int] = set()
            for idx in indices:
                if 0 <= idx < len(candidates) and idx not in seen:
                    seen.add(idx)
                    # Give a synthetic score that preserves AI ordering
                    _, r = candidates[idx]
                    reordered.append((1.0 - len(reordered) * 0.05, r))
            # Append any not mentioned by AI
            for i, pair in enumerate(candidates):
                if i not in seen:
                    reordered.append(pair)
            log.debug("knowledge_ai_rerank_done", indices=indices[:5])
            return reordered
        except Exception as exc:
            log.warning("knowledge_ai_rerank_failed", error=str(exc),
                        fallback="score_sort")
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored

    # ── Private: synthesis + confidence ─────────────────────────────────────

    def _synthesize(self, question: str, context: str) -> str:
        """Generate an answer from the retrieved context."""
        import structlog
        log = structlog.get_logger(__name__)

        if self._ai is None:
            return "[No AI provider — install jsat[local] or jsat[anthropic] for AI synthesis]"

        if not context.strip():
            prompt = (
                f"Answer this question about the codebase as best you can:\n{question}"
            )
        else:
            prompt = (
                "You are a precise software codebase knowledge assistant.\n"
                "Answer the question using ONLY the context entries provided. "
                "Reference specific ADRs, runbooks, or decision entries by name where relevant. "
                "If the context does not contain enough information, say so explicitly — "
                "do not guess or invent details not present in the entries.\n\n"
                f"CONTEXT:\n{context}\n\n"
                f"QUESTION: {question}\n\n"
                "ANSWER (cite specific entries; be direct and actionable):"
            )

        log.debug("knowledge_synthesize", prompt_len=len(prompt), has_context=bool(context.strip()))
        try:
            answer = self._ai.complete(prompt, max_tokens=512, temperature=0.1)
            log.debug("knowledge_synthesize_done", answer_len=len(answer))
            return answer
        except Exception as exc:
            log.error("knowledge_synthesize_error", error=str(exc))
            return f"[AI synthesis error: {exc}]"

    def _estimate_confidence(self, question: str, entries: list[dict]) -> float:
        """Heuristic confidence: 0.0–1.0."""
        if not entries:
            return 0.2
        q_kw = self._tokenise(question)
        best = 0.0
        for e in entries:
            props = e.get("properties", {})
            if props.get("stale"):
                continue
            kw = set(props.get("keywords", []))
            if q_kw and kw:
                overlap = len(q_kw & kw) / max(len(q_kw | kw), 1)
                best = max(best, overlap)
        # Scale: overlap ≥ 0.4 → confidence ≥ 0.75
        return round(min(0.95, 0.4 + best * 1.2), 2)

    # ── Private: extraction dispatch ─────────────────────────────────────────

    def _extract(self, text: str) -> tuple[list[Entity], list[Relation]]:
        """Dispatch to graphiti, AI, or regex extraction based on mode."""
        if self._graphiti_mode:
            return self._extract_graphiti(text)
        return self._extract_default(text)

    def _extract_default(self, text: str) -> tuple[list[Entity], list[Relation]]:
        """Regex + AI entity extraction (default mode)."""
        import structlog
        log = structlog.get_logger(__name__)

        regex_ents = _regex_extract(text)
        log.debug("knowledge_regex_extract", count=len(regex_ents))

        ai_ents: list[Entity] = []
        ai_rels: list[Relation] = []
        if self._ai and len(text.strip()) > 50:
            ai_ents, ai_rels = _ai_extract_entities(self._ai, text)
            log.debug("knowledge_ai_extract", entities=len(ai_ents), relations=len(ai_rels))
        else:
            log.debug("knowledge_ai_extract_skipped",
                      reason="no AI provider" if self._ai is None else "text too short")

        merged = _merge_entities(regex_ents, ai_ents)
        return merged, ai_rels

    def _extract_graphiti(self, text: str) -> tuple[list[Entity], list[Relation]]:
        """Attempt Graphiti entity extraction; fall back to default on failure."""
        import asyncio

        import structlog
        log = structlog.get_logger(__name__)

        try:

            if self._graphiti_client is None:
                log.debug("knowledge_graphiti_add_skip",
                          reason="no neo4j URI configured; using default extraction")
                return self._extract_default(text)

            # graphiti.add_episode returns nodes/edges; we run it in a new event loop
            loop = asyncio.new_event_loop()
            try:
                episode = loop.run_until_complete(
                    self._graphiti_client.add_episode(
                        name=f"episode_{hashlib.sha256(text[:100].encode()).hexdigest()[:8]}",
                        episode_body=text,
                        source_description="JSAT knowledge ingest",
                        reference_time=datetime.datetime.utcnow(),
                    )
                )
            finally:
                loop.close()

            # Convert Graphiti episode nodes → Entity list
            entities: list[Entity] = []
            seen: set[str] = set()
            for node in getattr(episode, "nodes", []):
                name = getattr(node, "name", str(node))
                typ = getattr(node, "entity_type", "OTHER")
                key = f"{typ}::{name.lower()}"
                if key not in seen:
                    seen.add(key)
                    entities.append(Entity(name=name, entity_type=str(typ), raw=name))

            relations: list[Relation] = []
            for edge in getattr(episode, "edges", []):
                src = getattr(edge, "source_node_uuid", None)
                tgt = getattr(edge, "target_node_uuid", None)
                rel = getattr(edge, "fact", "RELATED_TO")
                if src and tgt:
                    relations.append(Relation(source=str(src), target=str(tgt), rel_type=str(rel)))

            log.info("knowledge_graphiti_extract_done",
                     entities=len(entities), relations=len(relations))
            return entities, relations

        except Exception as exc:
            import structlog as _sl
            _sl.get_logger(__name__).warning(
                "knowledge_graphiti_extract_failed",
                error=str(exc),
                fallback="regex+ai",
            )
            return self._extract_default(text)

    # ── Private: file ingestion helpers ──────────────────────────────────────

    def _infer_category(self, path: Path) -> str:
        """Guess category from path name."""
        name = path.name.lower()
        parent = str(path.parent).lower()
        if "adr" in parent or name.startswith("adr-") or re.match(r"\d{4}-", name):
            return "adr"
        if "incident" in parent or "incident" in name:
            return "incident"
        if "claude" in name or name == "claude.md":
            return "claude_md"
        if "decision" in parent or "decision" in name:
            return "decision"
        if "runbook" in parent or "runbook" in name:
            return "runbook"
        return "general"

    def _split_sections(self, text: str, path: Path) -> list[tuple[str, str]]:
        """Split markdown into top-level sections.

        Returns list of (section_text, section_category).
        For non-markdown or unsectioned text, returns the whole text as one entry.
        """
        if path.suffix.lower() not in (".md", ".markdown", ".txt"):
            return [(text, "")]

        # Split on H1/H2 headings
        parts = re.split(r"(?m)^(#{1,2} .+)$", text)
        if len(parts) <= 1:
            # No headings — return as single entry
            return [(text, "")]

        # Reassemble: parts alternate between heading and content
        sections: list[tuple[str, str]] = []
        heading = ""
        for _i, part in enumerate(parts):
            if re.match(r"^#{1,2} ", part):
                heading = part
            else:
                combined = f"{heading}\n{part}".strip() if heading else part.strip()
                if combined:
                    # Infer sub-category from heading
                    h_lower = heading.lower()
                    sub_cat = ""
                    if any(w in h_lower for w in ("decision", "adr", "architecture")):
                        sub_cat = "adr"
                    elif any(w in h_lower for w in ("incident", "postmortem", "root cause")):
                        sub_cat = "incident"
                    elif any(w in h_lower for w in ("runbook", "playbook", "on-call")):
                        sub_cat = "runbook"
                    sections.append((combined, sub_cat))

        return sections if sections else [(text, "")]

    # ── Private: text utilities ───────────────────────────────────────────────

    @staticmethod
    def _tokenise(text: str) -> set[str]:
        """Lower-case word tokens, stop-words removed, min length 3."""
        tokens = re.findall(r"[a-z][a-z0-9_]{2,}", text.lower())
        return {t for t in tokens if t not in _STOP_WORDS}

    @staticmethod
    def _keyword_index(text: str) -> list[str]:
        """Sorted list of non-stop tokens for storage."""
        tokens = re.findall(r"[a-z][a-z0-9_]{2,}", text.lower())
        return sorted({t for t in tokens if t not in _STOP_WORDS})
