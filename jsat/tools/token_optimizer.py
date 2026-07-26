"""jsat.tools.token_optimizer — Offline token analysis and multi-strategy compression.

Zero LLM calls. All strategies are deterministic and offline.

Strategies (applied in order):
  whitespace      — normalize blank lines, strip trailing spaces     (~0ms)
  stopphrase      — remove AI filler ("Certainly!", "As an AI...")  (~1ms)
  import_collapse — merge repeated "from X import A/B" lines        (~2ms)
  dedup           — Jaccard-similarity sentence dedup (threshold 0.82) (~5ms)
  comment_strip   — remove code comment lines (opt-in)              (~2ms)
  recency_pin     — trim middle when still over budget              (~0ms)

Usage:
    from jsat.tools.token_optimizer import TokenOptimizer, estimate_tokens
    opt = TokenOptimizer(graph=g, cfg=cfg)
    report = opt.compress(text, model="claude-cli")
    print(report.savings_pct, report.compressed_text)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import structlog

from jsat.tools import BaseTool

log = structlog.get_logger(__name__)

# ── Model context limits (input window, approximate as of 2026-07) ────────────

MODEL_LIMITS: dict[str, int] = {
    # Anthropic Claude
    "claude-cli":                    200_000,
    "claude_cli":                    200_000,
    "anthropic":                     200_000,
    "claude-3-5-sonnet-20241022":    200_000,
    "claude-3-5-haiku-20241022":     200_000,
    "claude-3-opus-20240229":        200_000,
    "claude-sonnet-4-6":             200_000,
    "claude-haiku-4-5":              200_000,
    "claude-opus-4-8":               200_000,
    "claude-fable-5":                200_000,
    # OpenAI
    "openai":                        128_000,
    "gpt-4o":                        128_000,
    "gpt-4o-mini":                   128_000,
    "gpt-4-turbo":                   128_000,
    "gpt-4":                           8_192,
    "gpt-3.5-turbo":                  16_385,
    "o1":                            200_000,
    "o3":                            200_000,
    "o3-mini":                       200_000,
    # Google Gemini
    "gemini-1.5-pro":              1_000_000,
    "gemini-1.5-flash":            1_000_000,
    "gemini-2.0-flash":            1_000_000,
    # Ollama / local (conservative defaults — actual limits vary by quantization)
    "ollama":                          8_192,
    "llama3":                          8_192,
    "llama3.2":                      131_072,
    "llama3.1":                      131_072,
    "llama3.3":                      131_072,
    "mistral":                        32_768,
    "mistral-nemo":                  131_072,
    "codellama":                      16_384,
    "phi3":                          128_000,
    "phi3.5":                        128_000,
    "qwen2":                         131_072,
    "qwen2.5":                       131_072,
    "deepseek-coder":                 16_384,
    "deepseek-r1":                   131_072,
    "gemma2":                          8_192,
    "gemma3":                        131_072,
    "nomic-embed-code":                8_192,
}

# ── AI filler stop-phrases ────────────────────────────────────────────────────

_STOP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*(Certainly!|Sure!|Of course!|Absolutely!)\s*$",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Sure,?\s+I(?:'d\s+be\s+happy\s+to|'ll)?\s+help(?:\s+with\s+that)?[.!]?\s*$",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*As\s+an\s+AI(?:\s+language\s+model)?,?\s*",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Let\s+me\s+(?:explain|walk\s+you\s+through|break\s+(?:it|this)\s+down)[.!]\s*$",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*(?:In\s+conclusion|To\s+summarize|To\s+recap),?\s+",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*I\s+hope\s+(?:this\s+)?helps[.!]?\s*$",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Feel\s+free\s+to\s+ask\s+(?:if\s+you\s+have\s+(?:any\s+)?(?:more\s+)?questions?|anything)[.!]?\s*$",
               re.IGNORECASE | re.MULTILINE),
]


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class TokenReport:
    original_text: str
    original_tokens: int
    compressed_text: str
    compressed_tokens: int
    savings_tokens: int
    savings_pct: float
    strategies_applied: list[str]
    model: str | None
    model_limit: int | None
    budget_used_pct: float | None    # compressed_tokens / model_limit × 100
    section_breakdown: dict[str, int] = field(default_factory=dict)
    elapsed_ms: float = 0.0


# ── Token estimation ──────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """
    Character-based token estimator. No LLM, no tiktoken dependency.

    Heuristic: code-heavy text (~3.2 chars/token) vs mixed (~3.8) vs prose (~4.2).
    Calibrated against tiktoken cl100k_base on typical code+prompt text.
    Error margin: ±12% vs actual BPE tokenization.
    """
    if not text:
        return 0
    total = len(text)
    code_punct = sum(text.count(c) for c in "{}()[];,<>=!@#$%^&*|\\")
    ratio = code_punct / max(total, 1)
    if ratio > 0.04:
        chars_per_tok = 3.2   # dense code
    elif ratio > 0.01:
        chars_per_tok = 3.8   # mixed code + prose
    else:
        chars_per_tok = 4.2   # plain prose
    return max(1, round(total / chars_per_tok))


# ── Compression strategies (all offline, deterministic) ──────────────────────

def _apply_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)       # trailing spaces/tabs
    text = re.sub(r"\n{3,}", "\n\n", text)        # 3+ blank lines → 2
    text = re.sub(r"^\n+", "", text)              # leading blank lines
    return text.rstrip()


def _apply_stopphrase(text: str) -> str:
    for pat in _STOP_PATTERNS:
        text = pat.sub("", text)
    return text


def _apply_import_collapse(text: str) -> str:
    """Merge consecutive 'from X import A' / 'from X import B' → 'from X import A, B'."""
    from_re = re.compile(r"^(from\s+\S+\s+import)\s+(.+)$")
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = from_re.match(lines[i].rstrip())
        if m:
            prefix, names = m.group(1), [m.group(2).strip()]
            j = i + 1
            while j < len(lines):
                m2 = from_re.match(lines[j].rstrip())
                if m2 and m2.group(1) == prefix:
                    names.append(m2.group(2).strip())
                    j += 1
                else:
                    break
            out.append(f"{prefix} {', '.join(names)}\n" if j > i + 1 else lines[i])
            i = j if j > i + 1 else i + 1
        else:
            out.append(lines[i])
            i += 1
    return "".join(out)


def _apply_dedup(text: str, threshold: float = 0.82) -> str:
    """Remove near-duplicate sentences/chunks via Jaccard similarity on word sets."""
    if not text or not text.strip():
        return text
    # Split into logical chunks: sentence boundaries or blank-line paragraphs
    chunks = re.split(r"(?<=[.!?])\s{2,}|\n{2,}", text.strip())
    if len(chunks) <= 2:
        chunks = text.splitlines()   # fall back to line-level

    seen: list[set[str]] = []
    kept: list[str] = []

    for chunk in chunks:
        stripped = chunk.strip()
        if not stripped:
            kept.append(chunk)
            continue
        words = set(re.findall(r"[a-z0-9_]{2,}", stripped.lower()))
        if not words:
            kept.append(chunk)
            continue
        is_dup = any(
            len(words & prev) / max(len(words | prev), 1) >= threshold
            for prev in seen
        )
        if not is_dup:
            kept.append(chunk)
            seen.append(words)

    separator = "\n\n" if "\n\n" in text else "\n"
    return separator.join(k for k in kept if k.strip())


def _apply_comment_strip(text: str) -> str:
    """Remove single-line code comments. Shebang lines (#!) are preserved."""
    text = re.sub(r"(?m)^[ \t]*#(?!!)[^\n]*$", "", text)   # Python # (not #!)
    text = re.sub(r"(?m)[ \t]*//[^\n]*$", "", text)         # JS/Go/Rust //
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)   # /* */ blocks
    return text


def _apply_recency_pin(text: str, target_tokens: int) -> str:
    """Last-resort trim: keep first 70% + last 30%, drop middle with a marker."""
    if not text:
        return text
    cur = estimate_tokens(text)
    if cur <= target_tokens or cur == 0:
        return text
    chars_per_tok = len(text) / max(cur, 1)
    budget_chars = int(target_tokens * chars_per_tok)
    head = int(budget_chars * 0.70)
    tail = int(budget_chars * 0.30)
    if head + tail >= len(text):
        return text
    marker = "\n\n[... middle content omitted — token budget ...]\n\n"
    return text[:head] + marker + text[len(text) - tail:]


# ── Section breakdown ─────────────────────────────────────────────────────────

def section_breakdown(text: str) -> dict[str, int]:
    """Token count per XML tag or Markdown header section."""
    xml = re.findall(r"<(\w+)>(.*?)</\1>", text, re.DOTALL)
    if xml:
        return {tag: estimate_tokens(body) for tag, body in xml}

    md = re.split(r"(?m)^(#{1,3} .+)$", text)
    if len(md) > 1:
        result: dict[str, int] = {}
        for i in range(1, len(md), 2):
            header = md[i].lstrip("#").strip()
            body = md[i + 1] if i + 1 < len(md) else ""
            result[header] = estimate_tokens(body)
        return result

    paras = [p for p in re.split(r"\n{2,}", text) if p.strip()]
    return {f"para_{i + 1}": estimate_tokens(p) for i, p in enumerate(paras)}


# ── Main tool ─────────────────────────────────────────────────────────────────

class TokenOptimizer(BaseTool):
    """
    Offline token analysis and multi-strategy compression. Zero LLM calls.

    Integrates with PromptOptimizer pipeline as a standalone pre-send step.
    """

    # ── Query ─────────────────────────────────────────────────────────────────

    def count(self, text: str) -> int:
        """Estimate token count of any text."""
        return estimate_tokens(text)

    def model_limit(self, model: str) -> int | None:
        """Return known context window size for a model, or None if unknown."""
        key = model.lower()
        if key in MODEL_LIMITS:
            return MODEL_LIMITS[key]
        # Prefix/substring match for versioned names like "claude-3-5-sonnet-20241022"
        for k, v in MODEL_LIMITS.items():
            if key.startswith(k) or k.startswith(key):
                return v
        return None

    def budget(self, text: str, model: str) -> dict:
        """Return budget dict: tokens used, limit, pct, headroom, status."""
        count = estimate_tokens(text)
        limit = self.model_limit(model)
        log.debug("token_budget_query", model=model, tokens=count, limit=limit)
        if not limit:
            return {"tokens": count, "model": model, "limit": None,
                    "budget_pct": None, "headroom_tokens": None, "status": "unknown"}
        used_pct = round(count / limit * 100, 2)
        status = "ok" if used_pct < 80 else ("warn" if used_pct < 95 else "critical")
        return {
            "tokens": count,
            "model": model,
            "limit": limit,
            "budget_pct": used_pct,
            "headroom_tokens": limit - count,
            "status": status,
        }

    # ── Analysis ──────────────────────────────────────────────────────────────

    def analyze(self, text: str, model: str | None = None) -> TokenReport:
        """Count tokens and compute budget. No compression applied."""
        if not text or not text.strip():
            return TokenReport(
                original_text=text, original_tokens=0, compressed_text=text,
                compressed_tokens=0, savings_tokens=0, savings_pct=0.0,
                strategies_applied=[], model=model, model_limit=None,
                budget_used_pct=None,
            )
        log.debug("token_analyze", model=model, text_len=len(text))
        t0 = time.monotonic()
        count = estimate_tokens(text)
        limit = self.model_limit(model) if model else None
        budget_pct = round(count / limit * 100, 3) if limit else None
        breakdown = section_breakdown(text)
        elapsed = (time.monotonic() - t0) * 1000
        log.debug("token_analyze_done", tokens=count, budget_pct=budget_pct,
                  elapsed_ms=round(elapsed, 2))
        return TokenReport(
            original_text=text,
            original_tokens=count,
            compressed_text=text,
            compressed_tokens=count,
            savings_tokens=0,
            savings_pct=0.0,
            strategies_applied=[],
            model=model,
            model_limit=limit,
            budget_used_pct=budget_pct,
            section_breakdown=breakdown,
            elapsed_ms=elapsed,
        )

    # ── Compression ───────────────────────────────────────────────────────────

    def compress(
        self,
        text: str,
        target_tokens: int | None = None,
        *,
        model: str | None = None,
        strip_comments: bool = False,
        dedup: bool = True,
        stopphrase: bool = True,
        collapse_imports: bool = True,
    ) -> TokenReport:
        """
        Apply offline compression strategies in priority order.

        target_tokens: desired ceiling. If None and model is given, defaults to
        85% of the model's context limit. If neither, all lossless strategies run.
        """
        if not text or not text.strip():
            return TokenReport(
                original_text=text, original_tokens=0, compressed_text=text,
                compressed_tokens=0, savings_tokens=0, savings_pct=0.0,
                strategies_applied=[], model=model,
                model_limit=self.model_limit(model) if model else None,
                budget_used_pct=None,
            )
        log.info("token_compress_start",
                 model=model, target_tokens=target_tokens,
                 strip_comments=strip_comments, dedup=dedup,
                 input_chars=len(text))
        t0 = time.monotonic()
        orig_tokens = estimate_tokens(text)
        limit = self.model_limit(model) if model else None

        if target_tokens is None and limit:
            target_tokens = int(limit * 0.85)

        applied: list[str] = []
        c = text

        # 1. Whitespace — always, lossless
        c2 = _apply_whitespace(c)
        if c2 != c:
            applied.append("whitespace")
            log.debug("strategy_whitespace_applied",
                      saved=estimate_tokens(c) - estimate_tokens(c2))
            c = c2

        # 2. Stop-phrase removal — lossless for AI outputs
        if stopphrase:
            c2 = _apply_stopphrase(c)
            if c2 != c:
                applied.append("stopphrase")
                log.debug("strategy_stopphrase_applied",
                          saved=estimate_tokens(c) - estimate_tokens(c2))
                c = c2

        # 3. Comment strip (opt-in — changes code semantics if comments carry meaning)
        if strip_comments:
            c2 = _apply_comment_strip(c)
            if c2 != c:
                applied.append("comment_strip")
                log.debug("strategy_comment_strip_applied",
                          saved=estimate_tokens(c) - estimate_tokens(c2))
                c = c2

        # 4. Import collapse — lossless for Python imports
        if collapse_imports:
            c2 = _apply_import_collapse(c)
            if c2 != c:
                applied.append("import_collapse")
                log.debug("strategy_import_collapse_applied",
                          saved=estimate_tokens(c) - estimate_tokens(c2))
                c = c2

        # 5. Semantic dedup — lossy but semantics-preserving; skip if under budget
        if dedup and (target_tokens is None or estimate_tokens(c) > target_tokens):
            c2 = _apply_dedup(c)
            if c2 != c:
                applied.append("dedup")
                log.debug("strategy_dedup_applied",
                          saved=estimate_tokens(c) - estimate_tokens(c2))
                c = c2

        # 6. Recency pin — last resort, explicitly logged as lossy
        if target_tokens and estimate_tokens(c) > target_tokens:
            c = _apply_recency_pin(c, target_tokens)
            applied.append("recency_pin")
            log.warning("recency_pin_triggered",
                        reason="still_over_budget_after_all_strategies",
                        target_tokens=target_tokens,
                        current_tokens=estimate_tokens(c))

        final_tokens = estimate_tokens(c)
        savings = max(0, orig_tokens - final_tokens)
        savings_pct = round(savings / max(orig_tokens, 1) * 100, 1)
        budget_pct = round(final_tokens / limit * 100, 3) if limit else None
        elapsed = (time.monotonic() - t0) * 1000

        log.info("token_compress_done",
                 original_tokens=orig_tokens, final_tokens=final_tokens,
                 savings_pct=savings_pct, strategies=applied,
                 elapsed_ms=round(elapsed, 1))

        return TokenReport(
            original_text=text,
            original_tokens=orig_tokens,
            compressed_text=c,
            compressed_tokens=final_tokens,
            savings_tokens=savings,
            savings_pct=savings_pct,
            strategies_applied=applied,
            model=model,
            model_limit=limit,
            budget_used_pct=budget_pct,
            section_breakdown=section_breakdown(c),
            elapsed_ms=elapsed,
        )
