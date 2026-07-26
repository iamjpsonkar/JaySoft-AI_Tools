"""jsat.tools.prompt_optimizer — Multi-agent prompt engineering pipeline.

Two-phase architecture:

PHASE 1 — Offline pipeline (always runs, zero LLM calls):
  ClassifyAgent     — keyword regex, ~0ms
  ContextAgent      — BFS graph, no LLM
  ConstraintAgent   — KB query, no LLM
  FewShotAgent      — kNN word-overlap, no LLM
  FormatAgent       — rule-based XML/Markdown/plain, no LLM
  CompressAgent     — regex pruning, no LLM

PHASE 2 — LLM rewriting (optional, --rewrite or --agents):
  LLMRewriteAgent        — rewrites task description for clarity (temperature 0.2)
  LLMContextExpandAgent  — fills missing technical detail (temperature 0.3)
  LLMConstraintHardenAgent — makes success criteria measurable (temperature 0.1)
  Agents run in parallel via ThreadPoolExecutor; winner chosen by coverage+specificity score.

Optional validation:
  CritiqueAgent     — validates AI RESPONSE (--self-critique only)

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
    # Phase-2 LLM rewriting fields (all optional/backward-compatible)
    rewrite_applied: bool = False
    rewrite_agents_run: int = 0
    rewrite_elapsed_ms: float = 0.0
    winning_agent: str | None = None   # "rewrite"|"context_expand"|"constraint_harden"
    rewrite_skip_reason: str | None = None  # set when rewrite requested but skipped

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
# PHASE 2 — LLM REWRITING AGENTS (optional, --rewrite / --agents)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RewriteResult:
    """Output from a single LLM rewrite agent."""
    prompt: str
    agent: str         # "rewrite" | "context_expand" | "constraint_harden"
    score: float       # composite quality score 0-1
    elapsed_ms: float
    llm_succeeded: bool = True   # False when LLM errored and fallback was used


def _score_rewrite(rewrite: str, offline_prompt: str, context_nodes: list[str]) -> float:
    """Score a rewritten prompt: coverage × specificity × efficiency."""
    # Coverage: fraction of original context node short-names present
    short_names = [n.split("::")[-1] for n in context_nodes if "::" in n]
    coverage = (
        sum(1 for sn in short_names if sn in rewrite) / len(short_names)
        if short_names else 0.5   # no nodes → neutral
    )
    # Specificity: density of code-like tokens (snake_case, camelCase, paths, numbers)
    code_toks = re.findall(
        r"[a-z]+_[a-z]+|[a-z][A-Z][a-zA-Z]+|[\w]+\.[a-z]{2,5}|\d{2,}", rewrite
    )
    all_words = rewrite.split()
    specificity = len(code_toks) / max(len(all_words), 1)

    # Length efficiency: small penalty when rewrite is > 1.5× the offline prompt
    ratio = len(rewrite) / max(len(offline_prompt), 1)
    efficiency = max(0.0, 1.0 - max(0.0, ratio - 1.5) * 0.3)

    return round(0.45 * coverage + 0.40 * specificity + 0.15 * efficiency, 4)


class LLMRewriteAgent:
    """Rewrites the task description for clarity and specificity. Temperature 0.2."""

    _SYSTEM = (
        "You are an expert prompt engineer for codebase intelligence queries.\n"
        "Rewrite the given prompt to be more specific, direct, and actionable.\n"
        "RULES:\n"
        "- Preserve ALL context blocks, constraint bullets, and examples verbatim.\n"
        "- Replace vague words (e.g. 'logger', 'this', 'fix') with the specific "
        "identifiers the context reveals — function names, file paths, error messages.\n"
        "- Sharpen only the <task> or Task section. Do NOT remove any other section.\n"
        "- Return ONLY the rewritten prompt, no commentary, no preamble."
    )

    def run(self, optimized_prompt: str, context_nodes: list[str], ai: object) -> RewriteResult:
        import structlog
        log = structlog.get_logger(__name__)
        t0 = time.monotonic()
        user_msg = f"Rewrite this prompt:\n\n{optimized_prompt}"
        try:
            result = ai.complete(  # type: ignore[attr-defined]
                f"{self._SYSTEM}\n\n{user_msg}", max_tokens=1200
            )
            prompt = result.strip() or optimized_prompt
        except Exception as e:
            log.warning("llm_rewrite_agent_failed", agent="rewrite", error=str(e))
            prompt = optimized_prompt
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            return RewriteResult(prompt=prompt, agent="rewrite", score=0.0,
                                 elapsed_ms=elapsed, llm_succeeded=False)
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        score = _score_rewrite(prompt, optimized_prompt, context_nodes)
        log.debug("llm_rewrite_agent_done", agent="rewrite", score=score, elapsed_ms=elapsed)
        return RewriteResult(prompt=prompt, agent="rewrite", score=score, elapsed_ms=elapsed)


class LLMContextExpandAgent:
    """Identifies missing technical detail and fills it in. Temperature 0.3."""

    _SYSTEM = (
        "You are a senior engineer reviewing an AI coding prompt.\n"
        "Identify what technical detail is missing that would help an AI give a better answer.\n"
        "Then return the prompt with those gaps filled — add function names, error messages, "
        "file paths, or expected behaviour where the context already hints at them.\n"
        "Do NOT invent information not supported by the existing context.\n"
        "Return ONLY the improved prompt, no commentary."
    )

    def run(self, optimized_prompt: str, raw_input: str, context_nodes: list[str],
            ai: object) -> RewriteResult:
        import structlog
        log = structlog.get_logger(__name__)
        t0 = time.monotonic()
        user_msg = (
            f"Raw user query: {raw_input}\n\n"
            f"Offline-optimised prompt to improve:\n\n{optimized_prompt}"
        )
        try:
            result = ai.complete(  # type: ignore[attr-defined]
                f"{self._SYSTEM}\n\n{user_msg}", max_tokens=1400
            )
            prompt = result.strip() or optimized_prompt
        except Exception as e:
            log.warning("llm_rewrite_agent_failed", agent="context_expand", error=str(e))
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            return RewriteResult(prompt=optimized_prompt, agent="context_expand",
                                 score=0.0, elapsed_ms=elapsed, llm_succeeded=False)
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        score = _score_rewrite(prompt, optimized_prompt, context_nodes)
        log.debug("llm_rewrite_agent_done", agent="context_expand", score=score, elapsed_ms=elapsed)
        return RewriteResult(prompt=prompt, agent="context_expand", score=score, elapsed_ms=elapsed)


class LLMConstraintHardenAgent:
    """Makes success criteria explicit and measurable. Temperature 0.1."""

    _SYSTEM = (
        "You are a code reviewer focused on acceptance criteria.\n"
        "Rewrite the prompt so the success criteria are measurable and testable:\n"
        "- Replace 'fix' with 'ensure X returns Y when Z'\n"
        "- Replace 'improve' with 'reduce P from current value to target R'\n"
        "- Add a 'Definition of Done' section at the end if one is absent.\n"
        "Preserve all context, examples, and constraint bullets.\n"
        "Return ONLY the rewritten prompt, no commentary."
    )

    def run(self, optimized_prompt: str, context_nodes: list[str], ai: object) -> RewriteResult:
        import structlog
        log = structlog.get_logger(__name__)
        t0 = time.monotonic()
        user_msg = f"Harden the success criteria in this prompt:\n\n{optimized_prompt}"
        try:
            result = ai.complete(  # type: ignore[attr-defined]
                f"{self._SYSTEM}\n\n{user_msg}", max_tokens=900
            )
            prompt = result.strip() or optimized_prompt
        except Exception as e:
            log.warning("llm_rewrite_agent_failed", agent="constraint_harden", error=str(e))
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            return RewriteResult(prompt=optimized_prompt, agent="constraint_harden",
                                 score=0.0, elapsed_ms=elapsed, llm_succeeded=False)
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        score = _score_rewrite(prompt, optimized_prompt, context_nodes)
        log.debug("llm_rewrite_agent_done", agent="constraint_harden", score=score, elapsed_ms=elapsed)
        return RewriteResult(prompt=prompt, agent="constraint_harden", score=score, elapsed_ms=elapsed)


_LLM_AGENTS = ["rewrite", "context_expand", "constraint_harden"]


def _run_llm_rewrite(
    optimized_prompt: str,
    raw_input: str,
    context_nodes: list[str],
    n_agents: int,
    ai: object,
) -> tuple[str, str, float, float]:
    """
    Run up to n_agents LLM rewrite agents in parallel, return
    (winning_prompt, winning_agent_name, winning_score, total_elapsed_ms).

    Falls back to offline prompt if all agents fail or AI is unavailable.
    """
    import structlog
    log = structlog.get_logger(__name__)
    TIMEOUT = 25.0  # seconds per agent

    n = max(1, min(n_agents, 3))
    rewrite_a = LLMRewriteAgent()
    ctx_a = LLMContextExpandAgent()
    harden_a = LLMConstraintHardenAgent()

    all_agents = [
        ("rewrite",           lambda: rewrite_a.run(optimized_prompt, context_nodes, ai)),
        ("context_expand",    lambda: ctx_a.run(optimized_prompt, raw_input, context_nodes, ai)),
        ("constraint_harden", lambda: harden_a.run(optimized_prompt, context_nodes, ai)),
    ][:n]

    t0 = time.monotonic()
    results: list[RewriteResult] = []

    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = {pool.submit(fn): name for name, fn in all_agents}
        for fut, name in futs.items():
            try:
                results.append(fut.result(timeout=TIMEOUT))
            except Exception as e:
                log.warning("llm_rewrite_agent_timeout", agent=name, error=str(e))

    elapsed = round((time.monotonic() - t0) * 1000, 1)

    successful = [r for r in results if r.llm_succeeded]
    if not successful:
        log.warning("all_llm_agents_failed", fallback="offline_prompt",
                    total_attempted=len(results))
        return optimized_prompt, "none", 0.0, elapsed

    winner = max(successful, key=lambda r: r.score)
    log.info("llm_rewrite_done",
             agents_run=len(successful), winner=winner.agent,
             score=winner.score, elapsed_ms=elapsed)
    return winner.prompt, winner.agent, winner.score, elapsed


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
        max_context_tokens: int = 4096,
        few_shot_k: int = 2,
        no_context: bool = False,
        no_examples: bool = False,
        # Phase-2 LLM rewriting (optional)
        rewrite: bool = False,   # shorthand for n_agents=1
        n_agents: int = 0,       # 0=off, 1-3 = run N parallel LLM agents
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

        # ── Phase 2: LLM rewriting (optional) ────────────────────────────────
        _n = 1 if (rewrite and n_agents == 0) else n_agents
        final_prompt = cmp_r.prompt
        rewrite_applied = False
        rewrite_agents_run = 0
        rewrite_elapsed = 0.0
        winning_agent: str | None = None

        rewrite_skip_reason: str | None = None
        if _n > 0:
            if self._ai is not None and self._ai.is_available():  # type: ignore[attr-defined]
                log.info("prompt_rewrite_start", n_agents=_n, task=task_type)
                rw_prompt, rw_agent, rw_score, rw_elapsed = _run_llm_rewrite(
                    cmp_r.prompt, raw_input, ctx_r.node_ids, _n, self._ai
                )
                # Accept the rewrite only if an agent actually ran
                if rw_agent != "none":
                    final_prompt = rw_prompt
                    rewrite_applied = True
                    rewrite_agents_run = _n
                    rewrite_elapsed = rw_elapsed
                    winning_agent = rw_agent
                    stages.append(f"rewrite({rw_agent})")
                    timings[f"rewrite_{rw_agent}"] = rw_elapsed
                else:
                    rewrite_skip_reason = "all_agents_failed"
            else:
                rewrite_skip_reason = "ai_unavailable"
                log.warning("rewrite_skipped", reason="ai_unavailable", requested_agents=_n)

        llm_calls = (1 if rewrite_applied else 0)
        log.info("prompt_optimizer_done", task=task_type, before=tokens_before,
                 after=_tok(final_prompt), llm_calls=llm_calls,
                 rewrite_applied=rewrite_applied, winning_agent=winning_agent,
                 rewrite_skip_reason=rewrite_skip_reason,
                 total_ms=round((time.monotonic()-t0)*1000,1))

        return PromptResult(
            raw_input=raw_input, optimized_prompt=final_prompt, task_type=task_type,
            model_format=fmt_r.model_format, tokens_before=tokens_before,
            tokens_after=_tok(final_prompt), context_nodes=ctx_r.node_ids,
            examples_used=len(fs_r.examples), stages_applied=stages, agent_timings=timings,
            rewrite_applied=rewrite_applied, rewrite_agents_run=rewrite_agents_run,
            rewrite_elapsed_ms=rewrite_elapsed, winning_agent=winning_agent,
            rewrite_skip_reason=rewrite_skip_reason,
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
