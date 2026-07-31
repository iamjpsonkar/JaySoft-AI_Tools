"""jsat.tools.crack — JSAT Crack: Multi-Agent War Room.

Multiple specialist AI agents discuss a complex engineering task in rounds,
responding to each other's arguments — like a real architecture meeting or
incident war room. A Moderator synthesizes consensus at the end.

Architecture:
  Round N (for N in 1..rounds):
    All non-moderator roles run IN PARALLEL:
      architect, security, implementer, tester, skeptic
    Each receives: task + codebase context + previous rounds transcript
    Moderator runs LAST each round, synthesising what others said

Output:
  Markdown document saved to .jsat/crack/<slug>.md
  Sections: Opening → Round-by-round → Consensus + Action plan
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from jsat.tools import BaseTool

log = structlog.get_logger(__name__)

# ── Role system prompts ───────────────────────────────────────────────────────

_ROLE_PROMPTS: dict[str, str] = {
    "architect": (
        "You are a senior software architect.\n"
        "Examine the codebase context to identify existing design patterns, service "
        "boundaries, and data flow. Reference specific services, modules, or files "
        "from the context. Analyze: decomposition trade-offs, interface contracts, "
        "data model impacts, scalability constraints, and how the proposal fits or "
        "clashes with the existing architecture. Be concrete — name what you see."
    ),
    "security": (
        "You are a security engineer.\n"
        "Use the codebase context to identify specific attack surfaces and trust "
        "boundaries. Look for: authentication gaps in listed endpoints, sensitive "
        "data flows between services, idempotency risks in mutation paths, and "
        "injection vectors in input-handling functions. Reference specific function "
        "names, routes, or services from the context when raising risks."
    ),
    "implementer": (
        "You are the engineer who knows this codebase best.\n"
        "Read the codebase context carefully — the services, functions, and endpoints "
        "listed are what actually exists. Estimate effort by identifying which "
        "existing functions need to change, what new code is needed, and what "
        "integration points are affected. Name specific files or functions. Flag "
        "backwards-compatibility constraints or migration complexity."
    ),
    "tester": (
        "You are a QA engineer focused on test strategy.\n"
        "Using the codebase context, identify untested paths and edge cases for the "
        "named services and functions. Propose concrete test cases: unit tests for "
        "specific functions, integration tests for service boundaries shown in context, "
        "and contract tests for listed API endpoints. Name the code paths you'd target."
    ),
    "skeptic": (
        "You are the team's devil's advocate.\n"
        "Challenge every assumption using the codebase context as evidence. Find: "
        "existing patterns that would be broken, services not mentioned that would be "
        "affected, complexity hidden in listed functions. Ask 'what could go wrong?' "
        "for each concrete item in the context. Raise risks with specific references, "
        "not generic concerns."
    ),
    "moderator": (
        "You are the technical lead who must drive the team to a clear decision.\n"
        "Review all specialist statements and the codebase context. Identify the ONE "
        "core trade-off that matters most. Make a CLEAR recommendation — not "
        "'it depends'. List only what must be true for the recommendation to succeed.\n\n"
        "Structure your output EXACTLY as:\n"
        "**✅ Agreed:** (what all agents converged on)\n"
        "**⚠️ Disputed:** (the live tensions, with stakes)\n"
        "**❓ Open questions:** (must-answer questions before starting)\n"
        "**🎯 Recommended action:** (one specific, concrete next step)"
    ),
}

_DEFAULT_ROLES = ["architect", "security", "implementer", "tester", "skeptic", "moderator"]
_ROLE_EMOJI = {
    "architect": "🏛",
    "security": "🔒",
    "implementer": "⚙️",
    "tester": "🧪",
    "skeptic": "😈",
    "moderator": "🎯",
}

# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class CrackStatement:
    role: str
    round_num: int
    text: str
    elapsed_ms: float


@dataclass
class CrackResult:
    task: str
    roles: list[str]
    rounds_run: int
    statements: list[CrackStatement]
    synthesis: str           # moderator's last statement
    output_path: str | None
    elapsed_ms: float
    ai_available: bool


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_history(statements: list[CrackStatement], max_chars_per: int = 1200) -> str:
    """Format all previous statements as a readable transcript."""
    if not statements:
        return "No previous statements."
    lines: list[str] = []
    cur_round = 0
    for s in statements:
        if s.round_num != cur_round:
            cur_round = s.round_num
            lines.append(f"\n--- Round {cur_round} ---")
        emoji = _ROLE_EMOJI.get(s.role, "•")
        text = s.text[:max_chars_per] + ("…" if len(s.text) > max_chars_per else "")
        lines.append(f"{emoji} {s.role.upper()}: {text}")
    return "\n".join(lines)


def _build_agent_prompt(
    role: str,
    task: str,
    context: str,
    history: str,
    round_num: int,
    total_rounds: int,
) -> str:
    system = _ROLE_PROMPTS[role]
    if round_num == 1:
        instruction = (
            f"This is Round 1 of {total_rounds}. State your initial position on the task.\n"
            "Be specific and concrete. You will respond to others' views in later rounds."
        )
    elif role == "moderator":
        instruction = (
            f"This is Round {round_num} of {total_rounds} — your synthesis round.\n"
            "Read ALL previous statements and produce your structured synthesis."
        )
    else:
        instruction = (
            f"This is Round {round_num} of {total_rounds}.\n"
            "Read what others said and RESPOND directly to their points.\n"
            "Agree where warranted. Push back where you disagree. Be specific."
        )

    parts = [
        f"ROLE: {system}\n",
        f"TASK UNDER DISCUSSION:\n{task}\n",
    ]
    if context.strip():
        parts.append(f"CODEBASE CONTEXT:\n{context}\n")
    if history and history != "No previous statements.":
        parts.append(f"DISCUSSION SO FAR:\n{history}\n")
    parts.append(f"YOUR TURN ({role.upper()}):\n{instruction}\n\nRespond now:")
    return "\n".join(parts)


def _agent_turn(
    role: str,
    task: str,
    context: str,
    history: str,
    round_num: int,
    total_rounds: int,
    ai: Any,
) -> CrackStatement:
    t0 = time.monotonic()
    prompt = _build_agent_prompt(role, task, context, history, round_num, total_rounds)
    try:
        text = ai.complete(prompt, max_tokens=600)
        text = text.strip() or f"[{role} had no response]"
    except Exception as e:
        log.warning("crack_agent_failed", role=role, round=round_num, error=str(e))
        text = f"[{role} error: {e}]"
    elapsed = round((time.monotonic() - t0) * 1000, 1)
    log.debug("crack_agent_done", role=role, round=round_num, elapsed_ms=elapsed)
    return CrackStatement(role=role, round_num=round_num, text=text, elapsed_ms=elapsed)


def _offline_statement(role: str, round_num: int, task: str, context: str) -> CrackStatement:
    """Fallback when AI is unavailable — generate a structural placeholder."""
    templates = {
        "architect": "Consider the system design tradeoffs for: {task}. Context: {ctx}",
        "security": "Security review needed for: {task}. Key risk areas: auth, data integrity.",
        "implementer": (
            "Existing code context:\n{ctx}\n"
            "Implementation complexity: unknown without AI."
        ),
        "tester": "Test coverage gaps for: {task} require investigation.",
        "skeptic": "Challenging assumption: is {task} the right problem to solve?",
        "moderator": "Consensus synthesis requires AI. Run: jsat ai use claude-cli to enable.",
    }
    ctx_summary = context[:200] if context else "no graph context available"
    text = templates.get(role, "Analysis of: {task}").format(
        task=task[:100], ctx=ctx_summary
    )
    return CrackStatement(role=role, round_num=round_num, text=text, elapsed_ms=0.0)


def _render_markdown(task: str, statements: list[CrackStatement], synthesis: str) -> str:
    """Render the full war room discussion as Markdown."""
    lines = [
        f"# JSAT Crack — {task[:60]}",
        f"> War room discussion — {len(set(s.role for s in statements))} agents · "
        f"{max((s.round_num for s in statements), default=0)} rounds",
        "",
    ]

    # Group by round
    rounds: dict[int, list[CrackStatement]] = {}
    for s in statements:
        rounds.setdefault(s.round_num, []).append(s)

    for r_num, r_statements in sorted(rounds.items()):
        lines += [f"## Round {r_num}", ""]
        for s in r_statements:
            if s.role == "moderator":
                continue   # moderator shown separately in synthesis
            emoji = _ROLE_EMOJI.get(s.role, "•")
            lines += [f"### {emoji} {s.role.title()}", "", s.text, ""]

        # Show moderator's round statement (if not last round)
        mod = next((s for s in r_statements if s.role == "moderator"), None)
        if mod and r_num < max(rounds.keys()):
            lines += [f"### 🎯 Moderator (Round {r_num})", "", mod.text, ""]

    lines += [
        "---",
        "",
        "## 🎯 Final Synthesis",
        "",
        synthesis if synthesis else "_AI not available — synthesis requires an AI provider._",
        "",
        "---",
        "*Generated by JSAT Crack. Re-run `jsat crack` to update.*",
    ]
    return "\n".join(lines)


# ── Main tool ─────────────────────────────────────────────────────────────────

class CrackTool(BaseTool):
    """Multi-agent war room discussion for complex engineering decisions."""

    def run(
        self,
        task: str,
        roles: list[str] | None = None,
        rounds: int = 3,
        output_file: str | None = None,
        repo_path: Path | None = None,
        progress_fn=None,
    ) -> CrackResult:
        t0 = time.monotonic()
        _notify = progress_fn or (lambda *a, **kw: None)
        active_roles = [r for r in (roles or _DEFAULT_ROLES) if r in _ROLE_PROMPTS]
        if "moderator" not in active_roles:
            active_roles.append("moderator")

        log.info("crack_start", task=task[:80], roles=active_roles, rounds=rounds)

        # Check AI availability
        ai_ok = self._ai is not None and self._ai.is_available()  # type: ignore[attr-defined]
        if not ai_ok:
            log.warning("crack_ai_unavailable", note="returning offline placeholders")

        # Load codebase context (reuse ContextAgent from prompt_optimizer)
        context = ""
        _notify("Loading codebase context…", 0, rounds * 2 + 1)
        try:
            from jsat.tools.prompt_optimizer import ContextAgent
            context = ContextAgent(self._graph, depth=2, max_tokens=3000).run(task).text
            log.debug("crack_context_loaded", chars=len(context))
        except Exception as e:
            log.debug("crack_context_failed", error=str(e))

        # Run rounds
        all_statements: list[CrackStatement] = []
        non_moderator = [r for r in active_roles if r != "moderator"]
        total_steps = rounds * 2 + 1  # context + (agents + moderator) per round

        _round_labels = {1: "Opening statements", 2: "Cross-examination", 3: "Consensus"}

        for round_num in range(1, rounds + 1):
            step = (round_num - 1) * 2 + 1
            label = _round_labels.get(round_num, f"Round {round_num}")
            _notify(f"Round {round_num}/{rounds}: {label}…", step, total_steps)
            log.info("crack_round_start", round=round_num, agents=len(non_moderator))
            history = _format_history(all_statements)

            if ai_ok:
                # Parallel: all non-moderator agents
                with ThreadPoolExecutor(max_workers=min(len(non_moderator), 5)) as pool:
                    futs = {
                        pool.submit(_agent_turn, role, task, context, history,
                                    round_num, rounds, self._ai): role
                        for role in non_moderator
                    }
                    for fut in as_completed(futs):
                        stmt = fut.result()
                        all_statements.append(stmt)
                        log.debug("crack_statement_received", role=stmt.role,
                                  round=round_num, chars=len(stmt.text))

                # Moderator always runs last (sees all non-moderator statements this round)
                _notify(f"Round {round_num}/{rounds}: Moderator synthesising…",
                        step + 1, total_steps)
                if "moderator" in active_roles:
                    full_history = _format_history(all_statements)
                    mod_stmt = _agent_turn(
                        "moderator", task, context, full_history,
                        round_num, rounds, self._ai
                    )
                    all_statements.append(mod_stmt)
            else:
                # Offline fallback
                for role in active_roles:
                    all_statements.append(_offline_statement(role, round_num, task, context))

            log.info("crack_round_done", round=round_num,
                     statements=len([s for s in all_statements if s.round_num == round_num]))

        # Synthesis = last moderator statement
        synthesis = next(
            (s.text for s in reversed(all_statements) if s.role == "moderator"), ""
        )

        # Render and write output
        _notify("Writing discussion document…", total_steps, total_steps)
        md = _render_markdown(task, all_statements, synthesis)
        resolved_output: str | None = None

        if output_file:
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            Path(output_file).write_text(md, encoding="utf-8")
            resolved_output = output_file
        elif repo_path:
            slug = re.sub(r"\W+", "-", task[:40]).strip("-").lower()
            out_path = repo_path / ".jsat" / "crack" / f"{slug}.md"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md, encoding="utf-8")
            resolved_output = str(out_path)

        elapsed = round((time.monotonic() - t0) * 1000, 1)
        log.info("crack_done", roles=active_roles, rounds=rounds,
                 statements=len(all_statements), elapsed_ms=elapsed,
                 output=resolved_output)

        return CrackResult(
            task=task,
            roles=active_roles,
            rounds_run=rounds,
            statements=all_statements,
            synthesis=synthesis,
            output_path=resolved_output,
            elapsed_ms=elapsed,
            ai_available=ai_ok,
        )
