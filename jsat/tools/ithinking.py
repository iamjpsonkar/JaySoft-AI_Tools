"""jsat.tools.ithinking — Tool 14: IThinking Meta-Cognitive Layer."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from jsat.tools import BaseTool

_AMBIGUOUS_WORDS = {"this", "it", "everything", "improve", "fix", "make better",
                    "that", "those", "stuff", "things"}
_LOCAL_PATTERNS = ("where is", "list", "find", "show", "what files", "git")
_RISKY_TERMS = {
    "all": "Assumes all instances — verify scope.",
    "always": "Assumes invariant behaviour — check edge cases.",
    "delete": "Destructive operation — confirm reversibility.",
    "drop": "Destructive operation — confirm reversibility.",
    "production": "Targets production — confirm environment gate.",
}


@dataclass
class PhaseResult:
    phase: int
    name: str
    output: str
    gate_triggered: bool
    approved: bool


@dataclass
class IThinkingResult:
    original_input: str
    confirmed_intent: str
    phases: list[PhaseResult]
    token_estimate: int
    token_actual: int
    duration_ms: int
    mode: str


class IThinkingTool(BaseTool):
    """7-phase meta-cognitive wrapper: intent → plan → verify → execute → reflect."""

    def run(self, user_input: str, tool_callback: Callable[[str], str],
            mode: str = "silent") -> IThinkingResult:
        import structlog
        log = structlog.get_logger(__name__)
        log.info("ithinking_start", input=user_input[:80], mode=mode)
        t0 = time.monotonic()
        phases: list[PhaseResult] = []

        p0 = self._p0_intent(user_input)
        phases.append(p0)
        p1 = self._p1_local(user_input)
        phases.append(p1)
        p2 = self._p2_optimise(user_input)
        phases.append(p2)
        p3 = self._p3_decompose(user_input)
        phases.append(p3)
        p4 = self._p4_audit(user_input)
        phases.append(p4)

        estimate = max(1, len(p2.output) // 4)
        p5, result, actual = self._p5_execute(p2.output, tool_callback)
        phases.append(p5)
        p6 = self._p6_reflect(user_input, result, actual)
        phases.append(p6)

        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("ithinking_done", tokens_estimate=estimate, tokens_actual=actual,
                 duration_ms=duration_ms)

        return IThinkingResult(
            original_input=user_input, confirmed_intent=user_input,
            phases=phases, token_estimate=estimate, token_actual=actual,
            duration_ms=duration_ms, mode=mode,
        )

    def _p0_intent(self, inp: str) -> PhaseResult:
        words = set(inp.lower().split())
        ambiguous = bool(words & _AMBIGUOUS_WORDS)
        output = (f"Ambiguity detected in: '{inp}'. Proceeding with literal interpretation."
                  if ambiguous else f"Confirmed intent: '{inp}'")
        return PhaseResult(0, "Intent Clarification", output, ambiguous, True)

    def _p1_local(self, intent: str) -> PhaseResult:
        local = any(p in intent.lower() for p in _LOCAL_PATTERNS)
        output = "[LOCAL] Graph query (0 tokens)" if local else "[LLM] AI reasoning required"
        return PhaseResult(1, "Local Feasibility", output, False, True)

    def _p2_optimise(self, intent: str) -> PhaseResult:
        filler = r"\b(please|kindly|can you|could you|just|maybe)\b"
        cleaned = re.sub(filler, "", intent, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        optimised = f"{cleaned}\n\nBe concise, accurate, and structured."
        return PhaseResult(2, "Prompt Optimisation", optimised, False, True)

    def _p3_decompose(self, intent: str) -> PhaseResult:
        parts = [p.strip() for p in re.split(r"\band\b|\bthen\b", intent, flags=re.IGNORECASE)
                 if p.strip()]
        output = "\n".join(f"{i+1}. {s}" for i, s in enumerate(parts or [intent]))
        return PhaseResult(3, "Task Decomposition", output, False, True)

    def _p4_audit(self, intent: str) -> PhaseResult:
        found = [f"  [{t}] {msg}" for t, msg in _RISKY_TERMS.items() if t in intent.lower()]
        gate = bool(found)
        output = "Assumptions flagged:\n" + "\n".join(found) if found else "No risky assumptions."
        return PhaseResult(4, "Assumption Audit", output, gate, True)

    def _p5_execute(self, prompt: str, cb: Callable[[str], str]) -> tuple[PhaseResult, str, int]:
        try:
            result = cb(prompt)
            actual = max(1, (len(prompt) + len(result)) // 4)
            output = f"Execution succeeded. Output: {len(result)} chars."
            return PhaseResult(5, "Gated Execution", output, False, True), result, actual
        except Exception as e:
            output = f"Execution failed: {e}"
            return PhaseResult(5, "Gated Execution", output, True, False), "", 0

    def _p6_reflect(self, original: str, result: str, tokens: int) -> PhaseResult:
        ok = bool(result and "error" not in result.lower())
        output = (f"Task complete. Tokens: {tokens}. Intent satisfied."
                  if ok else f"Task may be incomplete. Tokens: {tokens}.")
        return PhaseResult(6, "Reflection", output, not ok, True)
