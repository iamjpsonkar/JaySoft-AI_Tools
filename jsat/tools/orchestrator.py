"""jsat.tools.orchestrator — Tool 11: Multi-Agent Orchestrator."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from jsat.tools import BaseTool

_AGENT_PROMPTS = {
    "understanding": "You are the Understanding Agent. Identify relevant code entities. Be concise.",
    "generation": "You are the Generation Agent. Write code following existing codebase patterns.",
    "review": "You are the Review Agent. Review code for bugs, security, correctness.",
    "test": "You are the Test Agent. Write behavior-covering tests. Focus on edge cases.",
    "security": "You are the Security Agent. Scan for OWASP vulnerabilities.",
    "documentation": "You are the Documentation Agent. Update docs to match the code.",
}


@dataclass
class SubtaskResult:
    subtask: str
    agent: str
    output: str
    status: str  # "success"|"conflict"|"skipped"


@dataclass
class OrchestratorResult:
    task: str
    subtasks: list[SubtaskResult]
    conflicts_detected: int
    mode: str
    duration_ms: int


class OrchestratorTool(BaseTool):
    """Coordinates specialized agents sequentially (v0.1). Parallel in v0.2."""

    def run_task(self, task: str, agents: list[str] | None = None,
                 mode: str = "intent-driven") -> OrchestratorResult:
        import structlog
        log = structlog.get_logger(__name__)
        log.info("orchestrator_start", task=task[:80], mode=mode)
        t0 = time.monotonic()

        decomposed = self._decompose(task)
        if agents:
            requested = set(agents)
            decomposed = [(a, s) for a, s in decomposed if a in requested]

        results: list[SubtaskResult] = []
        context = ""
        conflicts = 0

        for agent, subtask in decomposed:
            result = self._run_agent(agent, subtask, context)
            results.append(result)
            if result.status == "conflict":
                conflicts += 1
            elif result.status == "success":
                context += f"\n[{agent}]: {result.output[:400]}"

        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("orchestrator_done", subtasks=len(results), conflicts=conflicts,
                 duration_ms=duration_ms)
        return OrchestratorResult(task=task, subtasks=results,
                                  conflicts_detected=conflicts, mode=mode,
                                  duration_ms=duration_ms)

    def _decompose(self, task: str) -> list[tuple[str, str]]:
        lower = task.lower()
        subtasks = [("understanding", f"Load context for: {task}")]
        if any(kw in lower for kw in ["write", "implement", "add", "create"]):
            subtasks += [("generation", f"Implement: {task}"),
                         ("test", f"Write tests for: {task}")]
        if any(kw in lower for kw in ["review", "check"]):
            subtasks.append(("review", f"Review: {task}"))
        if any(kw in lower for kw in ["security", "secure", "auth"]):
            subtasks.append(("security", f"Security check: {task}"))
        return subtasks

    def _run_agent(self, agent: str, subtask: str, prior: str) -> SubtaskResult:
        import structlog
        log = structlog.get_logger(__name__)
        system = _AGENT_PROMPTS.get(agent, f"You are the {agent.title()} Agent.")
        prompt = f"{system}\n\n" + (f"CONTEXT:\n{prior[:2000]}\n\n" if prior else "") + f"TASK: {subtask}"

        if self._ai is None:
            return SubtaskResult(subtask=subtask, agent=agent,
                                  output="[No AI provider]", status="skipped")
        try:
            output = self._ai.complete(prompt, max_tokens=1024)
            _CONFLICT_SIGNALS = ("contradicts", "conflicts with", "inconsistent with")
            conflict = any(sig in output.lower() for sig in _CONFLICT_SIGNALS)
            log.info("orchestrator_agent_done", agent=agent, output_len=len(output))
            return SubtaskResult(subtask=subtask, agent=agent, output=output.strip(),
                                  status="conflict" if conflict else "success")
        except Exception as e:
            log.error("orchestrator_agent_error", agent=agent, error=str(e))
            return SubtaskResult(subtask=subtask, agent=agent,
                                  output=f"[Error: {e}]", status="skipped")
