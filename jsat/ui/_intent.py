"""jsat.ui._intent — turn a free-text prompt into a real tool call.

Local, offline, deterministic. No AI is involved: a rule table maps phrasing
patterns to the MCP tool names the Studio runs, extracting a ``target`` (or
other primary argument) from the text where the tool needs one. Anything that
does not match a rule is treated as a natural-language codebase question and
routes to ``query``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# rule: (regex, tool, arg_key)
# arg_key None => no primary argument extracted.
_RULES: list[tuple[re.Pattern[str], str, str | None]] = [
    (re.compile(r"\b(index|graph|status|catalog)\b", re.I), "get_index_status", None),
    (re.compile(r"\b(blast|impact|break\w*|ripple)\b", re.I), "blast_radius", "target"),
    (re.compile(r"\b(security|owasp|vuln|cve-in-code|sast)\b", re.I), "security_review", "path"),
    (re.compile(r"\btest gap|untested|coverage gap", re.I), "get_test_gaps", "path"),
    (re.compile(r"\b(incident|outage|down|investigate|root cause)\b", re.I), "investigate_incident", "description"),
    (re.compile(r"\badd a test|unit test for", re.I), "generate_unit_test", "function"),
    (re.compile(r"\bcontract test", re.I), "generate_contract_test", None),
    (re.compile(r"\bintegration test", re.I), "generate_integration_test", "endpoint"),
    (re.compile(r"\bapi diff|contract diff", re.I), "get_api_diff", None),
    (re.compile(r"\bcompat(ibility)? score", re.I), "get_compat_score", None),
    (re.compile(r"\bconsumers?\b|\bconsumes\b", re.I), "get_consumers", "target"),
    (re.compile(r"\bdata flow|reads? from|writes? to", re.I), "get_data_flow", "service"),
    (re.compile(r"\btrace .* to |call chain", re.I), "trace_call_chain", None),
    (re.compile(r"\brunbook", re.I), "generate_runbook", "hypothesis"),
    (re.compile(r"\block (duration|estimate|time)", re.I), "estimate_lock_duration", None),
    (re.compile(r"\bmigration|zero-downtime", re.I), "validate_migration", None),
    (re.compile(r"\bauth (coverage|coverage)|no auth", re.I), "get_auth_coverage", "service"),
    (re.compile(r"\bsecrets?|hardcoded keys?", re.I), "list_secrets", None),
    (re.compile(r"\bdependenc(y|ies)|cve\b|osv", re.I), "get_dependency_cves", None),
    (re.compile(r"\bknowledge|adr|runbook (search|find)", re.I), "knowledge_query", "question"),
    (re.compile(r"\boptimize (this )?prompt|prompt improve", re.I), "prompt_optimize", "query"),
    (re.compile(r"\bimprove", re.I), "improve_status", None),
    (re.compile(r"\btoken budget", re.I), "token_budget", None),
    (re.compile(r"\btoken count|count tokens|how many tokens|\btokens\b", re.I), "token_count", "text"),
    (re.compile(r"\bcompress(?:ion)?\b|token compress", re.I), "token_compress", "text"),
    (re.compile(r"\bmost reliable bugs|high.?confidence bugs", re.I), "get_high_confidence_bugs", None),
    (re.compile(r"\bcoverage|behavioral", re.I), "get_behavioral_coverage", "service"),
    (re.compile(r"\breview (the )?(diff|pr)|submit for review", re.I), "submit_for_review", None),
    (re.compile(r"\buntested|risk(est)? untested", re.I), "list_untested_paths", None),
    (re.compile(r"\brecent changes|what changed", re.I), "get_recent_changes", None),
    (re.compile(r"\bhealth|healthy", re.I), "health", None),
    (re.compile(r"\bplan|i?thinking|decompose", re.I), "ithinking_plan", "task"),
]

# tokens that look like a primary argument when the rule has one.
_TOKEN_RE = re.compile(r"[A-Za-z_][\w./:-]*")
_QUOTED_RE = re.compile(r"[`'\"]([^`'\"]+)[`'\"]")


@dataclass(frozen=True)
class Intent:
    tool: str
    args: dict[str, str]
    confidence: float  # 0.0 (guess) .. 1.0 (explicit match)
    reason: str


def _extract_target(text: str) -> str:
    """Pull the best primary-argument candidate out of free text."""
    for m in _QUOTED_RE.finditer(text):
        return m.group(1).strip()
    glue = re.search(r"\b(?:of|for|from|on|touch(?:ing)?|to|in|the)\s+([`']?[\w./:-]+[`']?)", text, re.I)
    if glue:
        cand = glue.group(1).strip("`'\"")
        if len(cand) > 1 and cand.lower() not in {"this", "that", "these", "those", "it"}:
            return cand
    words = [w for w in _TOKEN_RE.findall(text) if w.lower() not in {
        "jsat", "the", "a", "an", "of", "for", "with", "what", "how", "why",
        "which", "where", "who", "and", "or", "do", "does", "can", "please",
        "me", "show", "list", "find", "all", "every", "any", "then"} and len(w) > 1]
    return words[-1] if words else ""


def resolve(text: str) -> Intent:
    """Map a free-text prompt to a tool call; falls back to ``query``."""
    cleaned = text.strip()
    if not cleaned:
        return Intent("query", {}, 0.0, "empty prompt")
    for pattern, tool, arg_key in _RULES:
        if pattern.search(cleaned):
            args: dict[str, str] = {}
            reason = "matched explicit rule"
            confidence = 1.0
            if arg_key:
                target = _extract_target(cleaned)
                if not target:
                    confidence = 0.6
                    reason = "matched rule but could not extract its argument"
                else:
                    args[arg_key] = target
            return Intent(tool, args, confidence, reason)
    return Intent("query", {"question": cleaned}, 0.5,
                  "no rule matched; treating as a codebase question")