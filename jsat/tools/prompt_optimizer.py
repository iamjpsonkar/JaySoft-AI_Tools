"""jsat.tools.prompt_optimizer — 7-stage prompt engineering pipeline.

Stage 1: Task classification (code_gen/refactor/review/debug/question/plan/test/security)
Stage 2: Context injection from JSAT graph (BFS subgraph, pinned start+end)
Stage 3: Constraint injection from knowledge base (ADRs, coding standards)
Stage 4: Few-shot example selection (kNN over .jsat/prompt-history.jsonl)
Stage 5: Output format specification (code_only/json_findings/prose/numbered_steps)
Stage 6: Model-specific formatting (XML for Claude, Markdown for GPT, plain for Ollama)
Stage 7: Compression (token pruning when over budget)
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from jsat.tools import BaseTool

# ── Data models ───────────────────────────────────────────────────────────────

TaskType = Literal["code_gen", "refactor", "review", "debug", "question", "plan", "test", "security"]


class PromptResult(BaseModel):
    raw_input: str
    optimized_prompt: str
    task_type: str
    model_format: str
    tokens_before: int
    tokens_after: int
    context_nodes: list[str] = Field(default_factory=list)
    examples_used: int = 0
    stages_applied: list[str] = Field(default_factory=list)


class PromptHistory(BaseModel):
    ts: str
    task_type: str
    raw_input: str
    optimized_prompt: str
    response: str
    quality_score: float = 0.8


# ── Keyword tables ─────────────────────────────────────────────────────────────

_TASK_KEYWORDS: dict[str, list[str]] = {
    "security":  ["secure", "vulnerability", "auth", "permission", "injection", "owasp", "xss", "exploit"],
    "test":      ["test", "spec", "verify", "assert", "unit test", "integration test", "pytest", "coverage"],
    "debug":     ["why", "broken", "error", "crash", "fix", "not working", "failing", "traceback", "exception", "bug"],
    "review":    ["review", "check", "audit", "find bugs", "inspect", "analyse", "analyze"],
    "refactor":  ["refactor", "rewrite", "improve", "cleanup", "clean up", "restructure", "simplify"],
    "code_gen":  ["write", "implement", "add", "create", "build", "scaffold", "generate", "develop", "make"],
    "plan":      ["design", "plan", "architecture", "approach", "strategy", "how should", "how do i", "best way"],
    "question":  ["what", "how", "explain", "describe", "understand", "tell me", "why does", "when does"],
}

_TASK_PRIORITY = ["security", "test", "debug", "review", "refactor", "code_gen", "plan", "question"]

_FORMAT_INSTRUCTIONS: dict[str, str] = {
    "code_gen":  "Return ONLY valid code. No prose. No markdown fences.",
    "review":    'Return ONLY a JSON array: [{"file":"...","line":null,"severity":"high|medium|low","title":"...","description":"..."}]',
    "question":  "Answer in ≤ 3 paragraphs. Be specific and cite code paths.",
    "plan":      "Return numbered implementation steps. Each step: what, where, why.",
    "debug":     "State root cause in 1 sentence. Then provide the exact fix.",
    "test":      "Return a complete test file. Use the detected test framework.",
    "security":  "Return JSON array of SecurityFinding objects with OWASP category, severity, proof-of-concept.",
    "refactor":  "Return only the modified code. No explanation.",
}


class PromptOptimizer(BaseTool):
    """7-stage prompt engineering pipeline."""

    def optimize(
        self,
        raw_input: str,
        ai_provider: str | None = None,
        output_format: str | None = None,
        cot: bool = False,
        compress: bool = True,
        max_context_tokens: int = 8192,
        few_shot_k: int = 3,
        no_context: bool = False,
        no_examples: bool = False,
    ) -> PromptResult:
        import structlog
        log = structlog.get_logger(__name__)
        log.info("prompt_optimizer_start", raw_len=len(raw_input), ai_provider=ai_provider)
        t0 = time.monotonic()
        stages: list[str] = []

        provider = ai_provider or getattr(getattr(self._cfg, "ai", None), "provider", "ollama")
        tokens_before = self._count_tokens(raw_input)

        # Stage 1: classify
        task_type = self._stage1_classify(raw_input)
        stages.append("stage1_classify")

        # Stage 2: context
        context_str, context_nodes = "", []
        if not no_context:
            try:
                context_str, context_nodes = self._stage2_inject_context(
                    raw_input, task_type, int(max_context_tokens * 0.4))
                stages.append("stage2_context")
            except Exception as e:
                log.warning("stage2_failed", error=str(e))

        # Stage 3: constraints
        constraints_str = ""
        try:
            constraints_str = self._stage3_inject_constraints(task_type)
            stages.append("stage3_constraints")
        except Exception as e:
            log.warning("stage3_failed", error=str(e))

        # Stage 4: few-shot
        examples: list[PromptHistory] = []
        if not no_examples and few_shot_k > 0:
            try:
                examples = self._stage4_few_shot(raw_input, task_type, few_shot_k)
                stages.append("stage4_few_shot")
            except Exception as e:
                log.warning("stage4_failed", error=str(e))

        # Stage 5: output format
        output_spec = self._stage5_output_format(task_type, override=output_format)
        stages.append("stage5_output_format")

        # Stage 6: format
        prompt, model_format = self._stage6_format(
            raw_input, context_str, constraints_str, examples, output_spec, task_type, provider, cot)
        stages.append("stage6_format")

        # Stage 7: compress
        compress_threshold = getattr(getattr(self._cfg, "prompt", None), "compress_threshold", 6000)
        if compress and self._count_tokens(prompt) > compress_threshold:
            prompt = self._stage7_compress(prompt, max_context_tokens)
            stages.append("stage7_compress")

        tokens_after = self._count_tokens(prompt)
        log.info("prompt_optimizer_done", task=task_type, before=tokens_before, after=tokens_after,
                 duration_ms=round((time.monotonic()-t0)*1000))

        return PromptResult(
            raw_input=raw_input, optimized_prompt=prompt, task_type=task_type,
            model_format=model_format, tokens_before=tokens_before, tokens_after=tokens_after,
            context_nodes=context_nodes, examples_used=len(examples), stages_applied=stages,
        )

    def _stage1_classify(self, raw: str) -> str:
        lower = raw.lower()
        for task in _TASK_PRIORITY:
            if any(kw in lower for kw in _TASK_KEYWORDS[task]):
                return task
        return "question"

    def _stage2_inject_context(self, raw: str, task_type: str, max_tokens: int) -> tuple[str, list[str]]:
        import structlog
        log = structlog.get_logger(__name__)
        depth = getattr(getattr(self._cfg, "prompt", None), "context_depth", 2)

        # Find entity nodes from raw input
        tokens = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", raw))
        tokens.update(re.findall(r"\b[\w/-]+\.(py|ts|js|go|rb|java|rs)\b", raw))
        matched_ids: list[str] = []
        try:
            rows = self._graph.query("MATCH (n) RETURN n LIMIT 3000")
            for r in rows:
                node_id = r.get("id", "")
                props = r.get("properties", {})
                name = props.get("name", "") or props.get("file", "") or ""
                for tok in tokens:
                    if tok.lower() in node_id.lower() or tok.lower() in name.lower():
                        matched_ids.append(node_id)
                        break
        except Exception as e:
            log.warning("context_graph_scan_failed", error=str(e))

        if not matched_ids:
            return "", []

        # BFS
        snippets: list[str] = []
        used_ids: list[str] = []
        try:
            for node_id, node_depth, _ in self._graph.bfs(list(dict.fromkeys(matched_ids)), max_depth=depth):
                node = self._graph.get_node(node_id)
                if not node:
                    continue
                props = node.get("properties", {})
                name = props.get("name", node_id.split("::")[-1])
                file_ = props.get("file", "")
                label = node.get("label", "")
                snippet = f"{label} {file_}::{name}" if file_ else f"{label} {name}"
                snippets.append(snippet)
                used_ids.append(node_id)
                if self._count_tokens("\n".join(snippets)) > max_tokens:
                    break
        except Exception as e:
            log.warning("context_bfs_failed", error=str(e))

        # 70/30 split for recency bias
        split = max(1, int(len(snippets) * 0.7))
        ctx_start = "\n".join(snippets[:split])
        ctx_end = "\n".join(snippets[split:])
        combined = "\n\n".join(filter(None, [ctx_start, ctx_end]))
        return combined, used_ids

    def _stage3_inject_constraints(self, task_type: str) -> str:
        query_terms = {
            "code_gen": "coding standards guidelines",
            "refactor": "patterns anti-patterns standards",
            "review": "code review ADR checklist",
            "debug": "known issues gotchas",
            "question": "architecture ADR",
            "plan": "architecture design decisions",
            "test": "testing standards patterns",
            "security": "security standards OWASP auth",
        }
        query = query_terms.get(task_type, "coding standards")
        constraints: list[str] = []
        try:
            rows = self._graph.query("MATCH (n:KnowledgeEntry) RETURN n")
            q_words = set(query.lower().split())
            scored = []
            for r in rows:
                props = r.get("properties", {})
                if props.get("stale"):
                    continue
                text = props.get("text", "")
                if not text:
                    continue
                overlap = sum(1 for w in q_words if w in text.lower())
                cat = props.get("category", "")
                score = overlap / max(len(q_words), 1) + (0.3 if cat in ("adr", "decision", "standards") else 0)
                if score > 0:
                    scored.append((score, text))
            scored.sort(key=lambda x: x[0], reverse=True)
            constraints = [t.strip().splitlines()[0][:200] for _, t in scored[:5]]
        except Exception:
            pass
        return "\n".join(f"- {c}" for c in constraints) if constraints else ""

    def _stage4_few_shot(self, raw: str, task_type: str, k: int) -> list[PromptHistory]:
        history_path = Path(getattr(getattr(self._cfg, "prompt", None), "history_path", ".jsat/prompt-history.jsonl"))
        if not history_path.exists():
            return []
        try:
            lines = history_path.read_text(encoding="utf-8").splitlines()[-10000:]
            candidates = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("task_type") == task_type:
                        candidates.append(PromptHistory(**data))
                except Exception:
                    pass
            if not candidates:
                return []
            q_tokens = set(re.findall(r"[a-z0-9_]{3,}", raw.lower()))
            def score(e: PromptHistory) -> float:
                e_tokens = set(re.findall(r"[a-z0-9_]{3,}", e.raw_input.lower()))
                overlap = len(q_tokens & e_tokens) / max(len(q_tokens | e_tokens), 1)
                return overlap * 0.8 + e.quality_score * 0.2
            return sorted(sorted(candidates, key=score)[-k:], key=score)
        except Exception:
            return []

    def _stage5_output_format(self, task_type: str, override: str | None = None) -> str:
        if override:
            return override
        return _FORMAT_INSTRUCTIONS.get(task_type, "Return a clear, specific answer.")

    def _stage6_format(self, raw: str, context: str, constraints: str,
                       examples: list[PromptHistory], output_spec: str,
                       task_type: str, ai_provider: str, cot: bool) -> tuple[str, str]:
        p = (ai_provider or "").lower()
        if p in ("anthropic", "claude_cli", "claude"):
            return self._fmt_claude(raw, context, constraints, examples, output_spec, cot), "xml"
        elif p in ("openai", "gemini", "openai_compat"):
            return self._fmt_gpt(raw, context, constraints, examples, output_spec, cot), "markdown"
        else:
            return self._fmt_plain(raw, context, constraints, examples, output_spec, cot), "plain"

    def _fmt_claude(self, raw, context, constraints, examples, output_spec, cot) -> str:
        parts = []
        sys = "You are an expert software engineer."
        if constraints:
            sys += f"\n<constraints>\n{constraints}\n</constraints>"
        parts.append(f"<system>\n{sys}\n</system>")
        ctx_lines = context.splitlines() if context else []
        split = max(1, int(len(ctx_lines) * 0.7))
        ctx_start = "\n".join(ctx_lines[:split])
        ctx_end = "\n".join(ctx_lines[split:])
        if ctx_start:
            parts.append(f"<context>\n{ctx_start}\n</context>")
        if examples:
            ex = "\n".join(
                f"<example>\n<input>{e.raw_input}</input>\n<output>\n{chr(10).join(e.response.splitlines()[:15])}\n</output>\n</example>"
                for e in examples
            )
            parts.append(f"<examples>\n{ex}\n</examples>")
        parts.append(f"<task>\n{raw}\n</task>")
        if ctx_end:
            parts.append(f"<context>\n{ctx_end}\n</context>")
        parts.append(f"<output_format>\n{output_spec}\n</output_format>")
        if cot:
            parts.append("<instruction>Think step by step inside <thinking> tags before answering.</instruction>")
        return "\n\n".join(parts)

    def _fmt_gpt(self, raw, context, constraints, examples, output_spec, cot) -> str:
        parts = ["# System\nYou are an expert software engineer."]
        if constraints:
            parts[-1] += f"\n\n**Constraints:**\n{constraints}"
        if context:
            parts.append(f"# Codebase Context\n```\n{context}\n```")
        if examples:
            ex_parts = ["# Examples"]
            for e in examples:
                ex_parts.append(f"**Input:** {e.raw_input}\n\n**Output:**\n```\n{chr(10).join(e.response.splitlines()[:15])}\n```")
            parts.append("\n\n".join(ex_parts))
        parts.append(f"# Task\n{raw}")
        parts.append(f"# Output Format\n{output_spec}")
        if cot:
            parts.append("Think step by step before giving your final answer.")
        return "\n\n".join(parts)

    def _fmt_plain(self, raw, context, constraints, examples, output_spec, cot) -> str:
        parts = []
        if constraints:
            parts.append(f"Rules:\n{constraints}")
        if context:
            parts.append(f"Code context:\n{context}")
        if examples:
            ex_lines = ["Examples:"]
            for e in examples:
                ex_lines.append(f"Input: {e.raw_input}\nOutput:\n{chr(10).join(e.response.splitlines()[:10])}")
            parts.append("\n\n".join(ex_lines))
        parts.append(f"Task: {raw}")
        parts.append(output_spec)
        if cot:
            parts.append("Think step by step before giving your final answer.")
        return "\n\n".join(parts)

    def _stage7_compress(self, prompt: str, max_tokens: int) -> str:
        import structlog
        log = structlog.get_logger(__name__)
        orig = self._count_tokens(prompt)
        if orig <= max_tokens:
            return prompt

        # Pass 1: shorten example outputs
        def shorten_output(m: re.Match) -> str:
            lines = m.group(1).splitlines()
            sigs = [l for l in lines if re.match(r"^\s*(def |class |async def |@)", l)]
            short = "\n".join(sigs[:3]) if sigs else lines[0] if lines else ""
            return f"<output>\n{short}\n</output>"
        compressed = re.sub(r"<output>(.*?)</output>", shorten_output, prompt, flags=re.DOTALL)

        if self._count_tokens(compressed) <= max_tokens:
            log.info("compress_done", ratio=round(1-self._count_tokens(compressed)/orig, 2))
            return compressed

        # Pass 2: remove middle context blocks
        blocks = re.findall(r"<context>.*?</context>", compressed, flags=re.DOTALL)
        for b in blocks[1:-1]:
            compressed = compressed.replace(b, "", 1)

        if self._count_tokens(compressed) <= max_tokens:
            log.info("compress_done", ratio=round(1-self._count_tokens(compressed)/orig, 2))
            return compressed

        # Pass 3: strip docstrings
        compressed = re.sub(r'""".*?"""', '"""..."""', compressed, flags=re.DOTALL)
        compressed = re.sub(r"'''.*?'''", "'''...'''", compressed, flags=re.DOTALL)

        log.info("compress_done", ratio=round(1-self._count_tokens(compressed)/orig, 2))
        return compressed

    def save_to_history(self, result: PromptResult, response: str, quality_score: float = 0.8) -> None:
        from datetime import datetime, timezone

        import structlog
        log = structlog.get_logger(__name__)
        history_path = Path(getattr(getattr(self._cfg, "prompt", None), "history_path", ".jsat/prompt-history.jsonl"))
        max_entries = getattr(getattr(self._cfg, "prompt", None), "history_max_entries", 10000)
        entry = PromptHistory(
            ts=datetime.now(timezone.utc).isoformat(),
            task_type=result.task_type,
            raw_input=result.raw_input,
            optimized_prompt=result.optimized_prompt,
            response=response,
            quality_score=max(0.0, min(1.0, quality_score)),
        )
        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            existing = history_path.read_text(encoding="utf-8").splitlines() if history_path.exists() else []
            existing.append(entry.model_dump_json())
            if len(existing) > max_entries:
                existing = existing[len(existing)-max_entries:]
            history_path.write_text("\n".join(existing) + "\n", encoding="utf-8")
            log.info("history_saved", entries=len(existing))
        except Exception as e:
            log.error("history_save_failed", error=str(e))

    def _count_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) * 1.3))
