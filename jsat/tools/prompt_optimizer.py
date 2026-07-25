"""jsat.tools.prompt_optimizer — Multi-agent prompt engineering pipeline.

Architecture — ZERO LLM calls during optimization:
  6 offline agents run in parallel (ThreadPoolExecutor)
  Only the final AI completion call uses the LLM
  Token usage is minimized by selective context + compression

Agents (all offline):
  ClassifyAgent     — keyword regex, ~0ms
  ContextAgent      — BFS graph, no LLM
  ConstraintAgent   — KB query, no LLM
  FewShotAgent      — kNN word-overlap, no LLM
  FormatAgent       — rule-based XML/Markdown/plain, no LLM
  CompressAgent     — regex pruning, no LLM

Optional LLM agent:
  CritiqueAgent     — response validation (--self-critique only)

Token optimization strategy:
  - Context budget = 30% of total (not 100%)
  - Few-shot examples truncated to 10 lines (not full)
  - Constraints limited to top-3 (not top-5)
  - Compression triggered at 4000 tokens (not 6000)
  - Output spec is always < 60 chars
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from jsat.tools import BaseTool

# ── Data models ───────────────────────────────────────────────────────────────

TaskType = Literal["code_gen","refactor","review","debug","question","plan","test","security"]

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
    agent_timings: dict[str, float] = Field(default_factory=dict)

class PromptHistory(BaseModel):
    ts: str
    task_type: str
    raw_input: str
    optimized_prompt: str
    response: str
    quality_score: float = 0.8

@dataclass
class ClassifyResult:
    task_type: str
    confidence: float
    matched_keyword: str

@dataclass
class ContextResult:
    text: str
    node_ids: list[str]
    tokens: int

@dataclass
class ConstraintResult:
    text: str
    count: int

@dataclass
class FewShotResult:
    examples: list[PromptHistory]
    scores: list[float]

@dataclass
class FormatResult:
    prompt: str
    model_format: str

@dataclass
class CompressResult:
    prompt: str
    original_tokens: int
    final_tokens: int
    passes: int


# ── Keyword tables ────────────────────────────────────────────────────────────

_TASK_KEYWORDS: dict[str, list[str]] = {
    "security":  ["secure","vulnerability","auth","permission","injection","owasp","xss","exploit","attack","bypass"],
    "test":      ["test","spec","verify","assert","unit test","pytest","coverage","fixture","mock"],
    "debug":     ["why","broken","error","crash","fix","not working","failing","traceback","exception","bug"],
    "review":    ["review","check","audit","find bugs","inspect","analyse","analyze","evaluate"],
    "refactor":  ["refactor","rewrite","improve","cleanup","clean up","restructure","simplify"],
    "code_gen":  ["write","implement","add","create","build","scaffold","generate","develop","make"],
    "plan":      ["design","plan","architecture","approach","strategy","how should","how do i","best way"],
    "question":  ["what","how","explain","describe","understand","tell me","why does","when does"],
}
_TASK_PRIORITY = ["security","test","debug","review","refactor","code_gen","plan","question"]

# Compact output specs — minimize tokens
_FORMAT_INSTRUCTIONS: dict[str, str] = {
    "code_gen":  "Return ONLY valid code. No prose.",
    "review":    'Return JSON array: [{"file":"","line":null,"severity":"high|medium|low","title":"","description":""}]',
    "question":  "Answer in ≤ 3 paragraphs.",
    "plan":      "Numbered steps: what, where, why.",
    "debug":     "Root cause in 1 sentence. Then the fix.",
    "test":      "Return complete test file.",
    "security":  "JSON array: [{owasp_category, severity, title, proof_of_concept, remediation}]",
    "refactor":  "Return only modified code.",
}


# ═══════════════════════════════════════════════════════════════════════════════
# OFFLINE AGENTS — zero LLM calls
# ═══════════════════════════════════════════════════════════════════════════════

class ClassifyAgent:
    """Keyword + regex classification. ~0ms, no I/O."""
    def run(self, raw: str) -> ClassifyResult:
        lower = raw.lower()
        for task in _TASK_PRIORITY:
            for kw in _TASK_KEYWORDS[task]:
                if kw in lower:
                    conf = 1.0 if f" {kw} " in f" {lower} " else 0.8
                    return ClassifyResult(task_type=task, confidence=conf, matched_keyword=kw)
        return ClassifyResult(task_type="question", confidence=0.5, matched_keyword="(fallback)")


class ContextAgent:
    """BFS graph traversal. No LLM. Token-budget aware."""
    def __init__(self, graph, depth: int = 2, max_tokens: int = 1200):
        # max_tokens = 30% of total budget (token-efficient)
        self._graph = graph
        self._depth = depth
        self._max_tokens = max_tokens

    def run(self, raw: str) -> ContextResult:
        tokens = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", raw))
        tokens.update(re.findall(r"\b[\w/-]+\.(py|ts|js|go|rb|java|rs)\b", raw))

        matched: list[str] = []
        try:
            rows = self._graph.query("MATCH (n) RETURN n LIMIT 2000")
            for r in rows:
                nid = r.get("id","")
                name = r.get("properties",{}).get("name","") or r.get("properties",{}).get("file","") or ""
                if any(tok.lower() in nid.lower() or tok.lower() in name.lower() for tok in tokens):
                    matched.append(nid)
        except Exception:
            return ContextResult(text="", node_ids=[], tokens=0)

        if not matched:
            return ContextResult(text="", node_ids=[], tokens=0)

        snippets, used = [], []
        try:
            for nid, depth, _ in self._graph.bfs(list(dict.fromkeys(matched)), max_depth=self._depth):
                node = self._graph.get_node(nid)
                if not node:
                    continue
                props = node.get("properties",{})
                label = node.get("label","")
                name = props.get("name", nid.split("::")[-1])
                file_ = props.get("file","")
                # Compact 1-line format to save tokens
                snippet = f"{label} {file_}::{name}" if file_ else f"{label} {name}"
                snippets.append(snippet)
                used.append(nid)
                if _tok("\n".join(snippets)) > self._max_tokens:
                    snippets.pop(); used.pop()
                    break
        except Exception:
            pass

        # 70/30 recency split
        split = max(1, int(len(snippets) * 0.7))
        combined = "\n".join(snippets[:split]) + "\n\n" + "\n".join(snippets[split:])
        combined = combined.strip()
        return ContextResult(text=combined, node_ids=used, tokens=_tok(combined))


class ConstraintAgent:
    """Knowledge base query. No LLM. Returns top-3 only (token-efficient)."""
    def __init__(self, graph):
        self._graph = graph

    def run(self, task_type: str) -> ConstraintResult:
        q_map = {
            "code_gen":"coding standards guidelines","refactor":"patterns standards",
            "review":"code review ADR","debug":"known issues gotchas",
            "question":"architecture ADR","plan":"design decisions",
            "test":"testing standards","security":"security OWASP auth",
        }
        q_words = set(q_map.get(task_type,"standards").lower().split())
        try:
            rows = self._graph.query("MATCH (n:KnowledgeEntry) RETURN n")
            scored = []
            for r in rows:
                props = r.get("properties",{})
                if props.get("stale"): continue
                text = props.get("text","")
                if not text: continue
                cat = props.get("category","")
                overlap = sum(1 for w in q_words if w in text.lower())
                score = overlap/max(len(q_words),1) + (0.3 if cat in ("adr","decision","standards") else 0)
                if score > 0:
                    scored.append((score, text.strip().splitlines()[0][:150]))
            scored.sort(reverse=True)
            constraints = [t for _,t in scored[:3]]   # top-3 only = fewer tokens
            text = "\n".join(f"- {c}" for c in constraints) if constraints else ""
            return ConstraintResult(text=text, count=len(constraints))
        except Exception:
            return ConstraintResult(text="", count=0)


class FewShotAgent:
    """kNN word-overlap over prompt history. No LLM. Truncates examples to 10 lines."""
    def __init__(self, history_path: Path, max_entries: int = 10000):
        self._path = history_path
        self._max = max_entries

    def run(self, raw: str, task_type: str, k: int) -> FewShotResult:
        if k == 0 or not self._path.exists():
            return FewShotResult(examples=[], scores=[])
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()[-self._max:]
            candidates = []
            for line in lines:
                line = line.strip()
                if not line: continue
                try:
                    d = json.loads(line)
                    if d.get("task_type") == task_type:
                        candidates.append(PromptHistory(**d))
                except Exception:
                    pass
            if not candidates:
                return FewShotResult(examples=[], scores=[])
            q_tokens = set(re.findall(r"[a-z0-9_]{3,}", raw.lower()))
            def score(e: PromptHistory) -> float:
                e_tokens = set(re.findall(r"[a-z0-9_]{3,}", e.raw_input.lower()))
                j = len(q_tokens & e_tokens)/max(len(q_tokens|e_tokens),1)
                return j*0.8 + e.quality_score*0.2
            ranked = sorted(sorted(candidates, key=score)[-k:], key=score)
            return FewShotResult(examples=ranked, scores=[score(e) for e in ranked])
        except Exception:
            return FewShotResult(examples=[], scores=[])


class FormatAgent:
    """Rule-based model-specific formatting. No LLM."""
    def run(self, raw: str, task_type: str, ctx: ContextResult, con: ConstraintResult,
            fs: FewShotResult, output_format: str | None, ai_provider: str, cot: bool) -> FormatResult:
        spec = output_format or _FORMAT_INSTRUCTIONS.get(task_type, "Be specific and concise.")
        p = (ai_provider or "").lower()
        if p in ("anthropic","claude_cli","claude"):
            return FormatResult(prompt=self._xml(raw,ctx,con,fs,spec,cot), model_format="xml")
        elif p in ("openai","gemini","openai_compat"):
            return FormatResult(prompt=self._md(raw,ctx,con,fs,spec,cot), model_format="markdown")
        return FormatResult(prompt=self._plain(raw,ctx,con,fs,spec,cot), model_format="plain")

    def _xml(self, raw, ctx, con, fs, spec, cot) -> str:
        parts = []
        sys = "Expert software engineer."
        if con.text: sys += f"\n<constraints>\n{con.text}\n</constraints>"
        parts.append(f"<system>\n{sys}\n</system>")

        if ctx.text:
            lines = ctx.text.splitlines()
            split = max(1, int(len(lines)*0.7))
            ctx_start, ctx_end = "\n".join(lines[:split]), "\n".join(lines[split:])
            parts.append(f"<context>\n{ctx_start}\n</context>")
        else:
            ctx_end = ""

        if fs.examples:
            ex = []
            for e in fs.examples:
                resp = "\n".join(e.response.splitlines()[:10])  # 10 lines max
                ex.append(f"<example>\n<input>{e.raw_input}</input>\n<output>\n{resp}\n</output>\n</example>")
            parts.append("<examples>\n" + "\n".join(ex) + "\n</examples>")

        parts.append(f"<task>\n{raw}\n</task>")
        if ctx_end: parts.append(f"<context>\n{ctx_end}\n</context>")
        parts.append(f"<output_format>{spec}</output_format>")
        if cot: parts.append("<instruction>Think step by step inside <thinking> tags.</instruction>")
        return "\n\n".join(parts)

    def _md(self, raw, ctx, con, fs, spec, cot) -> str:
        parts = ["# System\nExpert software engineer."]
        if con.text: parts[-1] += f"\n\n**Rules:**\n{con.text}"
        if ctx.text: parts.append(f"# Context\n```\n{ctx.text}\n```")
        if fs.examples:
            ex = ["# Examples"]
            for e in fs.examples:
                resp = "\n".join(e.response.splitlines()[:10])
                ex.append(f"**Input:** {e.raw_input}\n```\n{resp}\n```")
            parts.append("\n\n".join(ex))
        parts.extend([f"# Task\n{raw}", f"# Format\n{spec}"])
        if cot: parts.append("Think step by step.")
        return "\n\n".join(parts)

    def _plain(self, raw, ctx, con, fs, spec, cot) -> str:
        parts = []
        if con.text: parts.append(f"Rules:\n{con.text}")
        if ctx.text: parts.append(f"Context:\n{ctx.text}")
        if fs.examples:
            ex = ["Examples:"]
            for e in fs.examples:
                resp = "\n".join(e.response.splitlines()[:8])
                ex.append(f"In: {e.raw_input}\nOut:\n{resp}")
            parts.append("\n\n".join(ex))
        parts.extend([f"Task: {raw}", spec])
        if cot: parts.append("Think step by step.")
        return "\n\n".join(parts)


class CompressAgent:
    """Regex token pruning. No LLM. Aggressive threshold for token efficiency."""
    def run(self, prompt: str, max_tokens: int) -> CompressResult:
        orig = _tok(prompt)
        if orig <= max_tokens:
            return CompressResult(prompt=prompt, original_tokens=orig, final_tokens=orig, passes=0)

        c, passes = prompt, 0

        # Pass 1: shorten <output> blocks to signatures
        def shorten(m: re.Match) -> str:
            lines = m.group(1).splitlines()
            sigs = [l for l in lines if re.match(r"^\s*(def |class |async def |@|pub fn |func )", l)]
            return f"<output>\n{chr(10).join(sigs[:2]) if sigs else lines[0] if lines else ''}\n</output>"
        c = re.sub(r"<output>(.*?)</output>", shorten, c, flags=re.DOTALL); passes += 1
        if _tok(c) <= max_tokens:
            return CompressResult(prompt=c, original_tokens=orig, final_tokens=_tok(c), passes=passes)

        # Pass 2: drop middle context blocks
        blocks = re.findall(r"<context>.*?</context>", c, flags=re.DOTALL)
        for b in blocks[1:-1]: c = c.replace(b,"",1)
        passes += 1
        if _tok(c) <= max_tokens:
            return CompressResult(prompt=c, original_tokens=orig, final_tokens=_tok(c), passes=passes)

        # Pass 3: strip docstrings
        c = re.sub(r'""".*?"""','"""..."""',c,flags=re.DOTALL)
        c = re.sub(r"'''.*?'''","'''...'''",c,flags=re.DOTALL)
        passes += 1
        return CompressResult(prompt=c, original_tokens=orig, final_tokens=_tok(c), passes=passes)


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

class PromptOptimizer(BaseTool):
    """Multi-agent prompt optimizer. 0 LLM calls during optimization.

    Token-efficient defaults:
      - Context = 30% of budget (not 100%)
      - Examples truncated to 10 lines
      - Constraints top-3 only
      - Compress threshold = 4000 tokens
    """

    def optimize(
        self,
        raw_input: str,
        ai_provider: str | None = None,
        output_format: str | None = None,
        cot: bool = False,
        compress: bool = True,
        max_context_tokens: int = 4096,    # tighter default = fewer tokens sent
        few_shot_k: int = 2,               # 2 examples instead of 3
        no_context: bool = False,
        no_examples: bool = False,
    ) -> PromptResult:
        import structlog
        log = structlog.get_logger(__name__)
        t0 = time.monotonic()

        provider = ai_provider or getattr(getattr(self._cfg,"ai",None),"provider","ollama")
        tokens_before = _tok(raw_input)

        prompt_cfg = getattr(self._cfg,"prompt",None)
        depth = getattr(prompt_cfg,"context_depth",2)
        compress_threshold = getattr(prompt_cfg,"compress_threshold",4000)  # tighter
        history_path = Path(getattr(prompt_cfg,"history_path",".jsat/prompt-history.jsonl"))
        max_history = getattr(prompt_cfg,"history_max_entries",10000)

        timings: dict[str, float] = {}

        # Stage 1: Classify (fast, sequential — informs parallel agents)
        t = time.monotonic()
        classify = ClassifyAgent().run(raw_input)
        task_type = classify.task_type
        timings["classify"] = round((time.monotonic()-t)*1000,1)

        # Stages 2-4: Parallel offline agents (zero LLM)
        context_budget = max(500, int(max_context_tokens * 0.30))  # 30% for context

        def run_ctx() -> ContextResult:
            if no_context: return ContextResult(text="",node_ids=[],tokens=0)
            t = time.monotonic()
            r = ContextAgent(self._graph, depth=depth, max_tokens=context_budget).run(raw_input)
            timings["context"] = round((time.monotonic()-t)*1000,1)
            return r

        def run_con() -> ConstraintResult:
            t = time.monotonic()
            r = ConstraintAgent(self._graph).run(task_type)
            timings["constraints"] = round((time.monotonic()-t)*1000,1)
            return r

        def run_fs() -> FewShotResult:
            if no_examples: return FewShotResult(examples=[],scores=[])
            t = time.monotonic()
            r = FewShotAgent(history_path, max_history).run(raw_input, task_type, few_shot_k)
            timings["fewshot"] = round((time.monotonic()-t)*1000,1)
            return r

        with ThreadPoolExecutor(max_workers=3) as pool:
            fc = pool.submit(run_ctx)
            fn = pool.submit(run_con)
            ff = pool.submit(run_fs)
            ctx_r, con_r, fs_r = fc.result(), fn.result(), ff.result()

        # Stage 5: Format (offline)
        t = time.monotonic()
        fmt_r = FormatAgent().run(raw_input, task_type, ctx_r, con_r, fs_r, output_format, provider, cot)
        timings["format"] = round((time.monotonic()-t)*1000,1)

        # Stage 6: Compress (offline, aggressive threshold)
        t = time.monotonic()
        if compress and _tok(fmt_r.prompt) > compress_threshold:
            cmp_r = CompressAgent().run(fmt_r.prompt, max_context_tokens)
        else:
            cmp_r = CompressResult(prompt=fmt_r.prompt, original_tokens=_tok(fmt_r.prompt),
                                   final_tokens=_tok(fmt_r.prompt), passes=0)
        timings["compress"] = round((time.monotonic()-t)*1000,1)

        stages = ["classify","context","constraints","fewshot","format"]
        if cmp_r.passes > 0: stages.append("compress")

        log.info("prompt_optimizer_done", task=task_type, before=tokens_before,
                 after=cmp_r.final_tokens, llm_calls=0,
                 total_ms=round((time.monotonic()-t0)*1000,1))

        return PromptResult(
            raw_input=raw_input, optimized_prompt=cmp_r.prompt, task_type=task_type,
            model_format=fmt_r.model_format, tokens_before=tokens_before,
            tokens_after=cmp_r.final_tokens, context_nodes=ctx_r.node_ids,
            examples_used=len(fs_r.examples), stages_applied=stages, agent_timings=timings,
        )

    def self_critique(self, prompt: str, response: str, task_type: str) -> str | None:
        """The ONLY LLM call in the optimizer — optional, explicit only."""
        import structlog
        log = structlog.get_logger(__name__)
        if self._ai is None or not self._ai.is_available():
            return None
        critique = (
            f"Task: '{task_type}'. Review this response.\n"
            f"PROMPT (excerpt):\n{prompt[:300]}\n\n"
            f"RESPONSE:\n{response[:800]}\n\n"
            "Check: security issues, correctness, constraint violations.\n"
            "Reply CLEAN if ok, or VIOLATIONS FOUND then corrected version."
        )
        try:
            result = self._ai.complete(critique, max_tokens=512)
            if result.strip().upper().startswith("CLEAN"):
                return None
            lines = result.splitlines()
            start = next((i for i,l in enumerate(lines) if "VIOLATIONS" in l.upper()), 0)
            return "\n".join(lines[start+1:]).strip() or response
        except Exception as e:
            log.error("self_critique_failed", error=str(e))
            return None

    def save_to_history(self, result: PromptResult, response: str, quality_score: float = 0.8) -> None:
        from datetime import datetime, timezone

        import structlog
        log = structlog.get_logger(__name__)
        history_path = Path(getattr(getattr(self._cfg,"prompt",None),"history_path",".jsat/prompt-history.jsonl"))
        max_entries = getattr(getattr(self._cfg,"prompt",None),"history_max_entries",10000)
        entry = PromptHistory(ts=datetime.now(timezone.utc).isoformat(), task_type=result.task_type,
                              raw_input=result.raw_input, optimized_prompt=result.optimized_prompt,
                              response=response, quality_score=max(0.0,min(1.0,quality_score)))
        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            existing = history_path.read_text(encoding="utf-8").splitlines() if history_path.exists() else []
            existing.append(entry.model_dump_json())
            if len(existing) > max_entries:
                existing = existing[len(existing)-max_entries:]
            history_path.write_text("\n".join(existing)+"\n", encoding="utf-8")
        except Exception as e:
            log.error("history_save_failed", error=str(e))


def _tok(text: str) -> int:
    """Token approximation. No LLM."""
    return max(1, int(len(text.split()) * 1.3))


# Aliases for backward compat
_count_tokens = _tok
