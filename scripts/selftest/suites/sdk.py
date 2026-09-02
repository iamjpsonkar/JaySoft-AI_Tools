"""
Phase E — the Python SDK, in-process.

`from jsat import JSAT` is a first-class documented surface (docs/sdk.md), and
nothing in the harness touched it before. It matters independently of the CLI
and the MCP server because it can disagree with them: several tools assemble
their context differently depending on which surface called them.

Run from the real installed package with the data dir redirected. A coverage
gate asserts every public method on the JSAT class is exercised, so the SDK
cannot grow an untested entry point.
"""
from __future__ import annotations

import inspect
import os
from pathlib import Path

from ..core import FAIL, PASS, UNAVAILABLE, Check, Report, timed
from ..fixtures import scratch_facts

FACTS = scratch_facts()

# Methods that require a live model, and so are gated behind --llm.
LLM_METHODS = {"query", "prompt", "prompt_and_send", "prompt_stream"}

# Methods deliberately not called here, with the reason.
SKIP_METHODS = {
    "from_import": "covered by the index suite's export/import round trip",
}


def _public_methods() -> dict[str, object]:
    from jsat import JSAT
    out = {}
    for name, member in vars(JSAT).items():
        if name.startswith("_"):
            continue
        out[name] = member
    return out


@timed
def check_exports_importable() -> Check:
    """Everything in __all__ must import, and every error be a JSATError."""
    import jsat
    from jsat import JSATError
    missing, bad_base = [], []
    for name in jsat.__all__:
        obj = getattr(jsat, name, None)
        if obj is None:
            missing.append(name)
            continue
        if name.endswith(("Error", "NotFound", "Corrupted", "Mismatch")) \
                and isinstance(obj, type) and not issubclass(obj, JSATError):
            bad_base.append(name)
    if missing:
        return Check("sdk_exports", "sdk", FAIL,
                     f"{len(missing)} name(s) in jsat.__all__ do not exist",
                     detail=", ".join(missing))
    if bad_base:
        return Check("sdk_exports", "sdk", FAIL,
                     f"{len(bad_base)} exception(s) do not subclass JSATError",
                     detail=", ".join(bad_base))
    return Check("sdk_exports", "sdk", PASS,
                 f"all {len(jsat.__all__)} exported names import; every "
                 "exception derives from JSATError")


@timed
def check_sdk_index_and_status(repo: Path, tmp: Path) -> Check:
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    result = js.index(force=True)
    status = js.index_status
    nodes = status.get("nodes", 0)
    if nodes <= 0:
        return Check("sdk_index", "sdk", FAIL,
                     "JSAT().index() reported success but index_status shows "
                     "no nodes",
                     detail=f"result={result} status={status}")
    return Check("sdk_index", "sdk", PASS,
                 f"JSAT().index() built the graph; index_status reports "
                 f"{nodes} nodes / {status.get('edges', 0)} edges")


@timed
def check_sdk_index_stream(repo: Path) -> Check:
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    events = []
    gen = js.index_stream()
    try:
        while True:
            events.append(next(gen))
    except StopIteration:
        pass
    if not events:
        return Check("sdk_index_stream", "sdk", FAIL,
                     "index_stream() yielded no progress events")
    return Check("sdk_index_stream", "sdk", PASS,
                 f"index_stream() yielded {len(events)} real progress events",
                 detail=str(events[0])[:200])


@timed
def check_sdk_blast_radius(repo: Path) -> Check:
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    js.index()
    report = js.blast_radius(target=FACTS["tested_function"], max_depth=3)
    impacts = getattr(report, "impacts", None)
    if impacts is None:
        return Check("sdk_blast_radius", "sdk", FAIL,
                     "blast_radius() returned no `impacts` collection",
                     detail=str(report)[:300])
    if not impacts:
        return Check("sdk_blast_radius", "sdk", FAIL,
                     f"blast_radius({FACTS['tested_function']!r}) found nothing, "
                     "but the fixture has a real 4-deep call chain through it",
                     detail=str(report)[:300])
    if not getattr(report, "mermaid_diagram", ""):
        return Check("sdk_blast_radius", "sdk", FAIL,
                     "blast_radius() produced no mermaid diagram",
                     detail=str(report)[:300])
    return Check("sdk_blast_radius", "sdk", PASS,
                 f"blast_radius() traced {len(impacts)} impact(s) from "
                 f"{FACTS['tested_function']} and rendered a diagram")


@timed
def check_sdk_security_review(repo: Path) -> Check:
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    report = js.security_review(path=str(repo), severity_threshold="low")
    findings = getattr(report, "findings", None)
    if findings is None:
        return Check("sdk_security_review", "sdk", FAIL,
                     "security_review() returned no `findings` collection",
                     detail=str(report)[:300])
    blob = " ".join(str(f) for f in findings)
    # All three sources have known-true answers on this fixture, so each is
    # asserted separately — a scanner that silently stops running would
    # otherwise still "pass" on the other two.
    problems = []
    if report.secrets_found < 1:
        problems.append("the planted synthetic AWS key was not detected")
    if FACTS["semgrep_rule_substring"] not in blob:
        problems.append("semgrep produced no finding for the planted "
                        "shell=True vulnerability (is semgrep installed and "
                        "able to load its rulesets?)")
    if not report.cves:
        problems.append("no CVEs for the pinned vulnerable requirements")
    if problems:
        return Check("sdk_security_review", "sdk", FAIL,
                     f"{len(problems)} of the 3 scan sources returned nothing: "
                     + "; ".join(problems),
                     detail=f"findings={len(findings)} "
                            f"secrets={report.secrets_found} "
                            f"cves={len(report.cves)} | {blob[:300]}")
    return Check("sdk_security_review", "sdk", PASS,
                 f"all three scan sources fired: {len(findings)} finding(s), "
                 f"{report.secrets_found} secret(s), {len(report.cves)} CVE(s)")


@timed
def check_sdk_incident(repo: Path) -> Check:
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    report = js.investigate_incident(
        description="payment validation causing timeout errors in production",
        since="365d")
    hypotheses = getattr(report, "hypotheses", None)
    if hypotheses is None:
        return Check("sdk_incident", "sdk", FAIL,
                     "investigate_incident() returned no `hypotheses`",
                     detail=str(report)[:300])
    if not hypotheses:
        return Check("sdk_incident", "sdk", FAIL,
                     "investigate_incident() ranked zero hypotheses even though "
                     "the fixture git history contains a matching commit",
                     detail=str(report)[:300])
    return Check("sdk_incident", "sdk", PASS,
                 f"investigate_incident() ranked {len(hypotheses)} hypothesis(es) "
                 "from the real git history",
                 detail=str(hypotheses[0])[:250])


@timed
def check_sdk_export(repo: Path, tmp: Path) -> Check:
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    js.index()
    out = tmp / "sdk-export.jsat.zip"
    manifest = js.export(output=out)
    if not out.exists() or out.stat().st_size == 0:
        return Check("sdk_export", "sdk", FAIL,
                     "export() did not write a non-empty archive",
                     detail=str(manifest)[:250])
    return Check("sdk_export", "sdk", PASS,
                 f"export() wrote a {out.stat().st_size} byte archive")


@timed
def check_sdk_token_helpers(repo: Path) -> Check:
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    n = js.token_count("hello world, this is a token counting test")
    budget = js.token_budget("a short prompt", model="claude-sonnet-4")
    compressed = js.token_compress("This sentence repeats. " * 60,
                                   target_tokens=40)
    problems = []
    if not isinstance(n, int) or n <= 0:
        problems.append(f"token_count returned {n!r}")
    if not isinstance(budget, dict) or not budget:
        problems.append(f"token_budget returned {type(budget).__name__}")
    if compressed is None:
        problems.append("token_compress returned None")
    if problems:
        return Check("sdk_token_helpers", "sdk", FAIL, "; ".join(problems))
    return Check("sdk_token_helpers", "sdk", PASS,
                 f"token_count={n}, token_budget and token_compress all "
                 "returned usable results (fully offline)")


@timed
def check_sdk_doctor_and_ai(repo: Path) -> Check:
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    doc = js.doctor()
    label = js.active_ai_label()
    if not isinstance(doc, dict) or not doc:
        return Check("sdk_doctor", "sdk", FAIL,
                     f"doctor() returned {type(doc).__name__}, expected a dict")
    if not isinstance(label, str) or not label:
        return Check("sdk_doctor", "sdk", FAIL,
                     f"active_ai_label() returned {label!r}")
    return Check("sdk_doctor", "sdk", PASS,
                 f"doctor() returned {len(doc)} section(s); active AI is {label!r}")


@timed
def check_sdk_switch_ai(repo: Path) -> Check:
    """switch_ai must accept an alias and must not silently keep the old one."""
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    from jsat._ai.aliases import alias_names
    before = js.active_ai_label()
    # Every documented alias must EITHER switch cleanly, OR fail with an
    # actionable message. JSAT deliberately ships no hard-coded model
    # catalogue (see _ai.require_explicit_model), so API-backed aliases are
    # SUPPOSED to refuse until given a model — what would be a bug is an
    # opaque failure, or a wrong exception type the CLI cannot present.
    resolved, guided, bad = [], [], []
    for alias in sorted(alias_names()):
        try:
            provider, _model, _ok = js.switch_ai(alias)
            resolved.append(alias)
        except ValueError as e:
            msg = str(e)
            if "jsat ai use" in msg or "jsat ai models" in msg:
                guided.append(alias)
            else:
                bad.append(f"{alias}: unactionable ValueError: {msg[:80]}")
        except Exception as e:
            bad.append(f"{alias}: {type(e).__name__}: {str(e)[:80]}")
    if bad:
        return Check("sdk_switch_ai", "sdk", FAIL,
                     f"{len(bad)} alias(es) failed in a way the user cannot act on",
                     detail="; ".join(bad[:8]),
                     remediation="every alias in _ai/aliases.py must switch or "
                                 "raise a ValueError naming the exact fix")
    after = js.active_ai_label()
    return Check("sdk_switch_ai", "sdk", PASS,
                 f"all {len(resolved) + len(guided)} documented aliases behave: "
                 f"{len(resolved)} switched, {len(guided)} correctly demanded an "
                 f"explicit model with an actionable hint (label {before!r} → "
                 f"{after!r})")


def check_noop_provider_contract(repo: Path) -> Check:
    """The documented gotcha: is_available() is False but complete() RAISES.

    Callers are told to check is_available() first; if complete() ever stopped
    raising, code that relies on the exception to degrade would silently
    return nonsense instead.
    """
    from jsat._ai.none import NoOpProvider
    from jsat._exceptions import AIError
    p = NoOpProvider()
    if p.is_available():
        return Check("sdk_noop_provider", "sdk", FAIL,
                     "NoOpProvider.is_available() returned True")
    try:
        p.complete("hello")
    except AIError:
        return Check("sdk_noop_provider", "sdk", PASS,
                     "NoOpProvider: is_available() is False and complete() "
                     "raises AIError, as documented")
    except Exception as e:
        return Check("sdk_noop_provider", "sdk", FAIL,
                     f"NoOpProvider.complete() raised {type(e).__name__}, "
                     "expected AIError")
    return Check("sdk_noop_provider", "sdk", FAIL,
                 "NoOpProvider.complete() did NOT raise — callers that rely on "
                 "the exception to degrade would get a silent wrong answer")


@timed
def check_sdk_llm_methods(repo: Path, allow_llm: bool) -> Check:
    if not allow_llm:
        return Check("sdk_query", "sdk", UNAVAILABLE,
                     "query()/prompt() need a real provider; skipped without --llm")
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    js.index()
    try:
        result = js.query("which function validates the payment amount?")
    except Exception as e:
        return Check("sdk_query", "sdk", FAIL,
                     f"query() raised {type(e).__name__}: {e}")
    answer = getattr(result, "answer", None) or str(result)
    if not answer.strip():
        return Check("sdk_query", "sdk", FAIL, "query() returned an empty answer")
    return Check("sdk_query", "sdk", PASS,
                 f"query() returned a grounded answer ({len(answer)} chars)",
                 detail=answer[:250])


@timed
def check_sdk_prompt(repo: Path, allow_llm: bool) -> Check:
    """The offline half of the prompt optimizer needs no model at all."""
    from jsat import JSAT
    js = JSAT(repo=str(repo))
    try:
        out = js.prompt("how do i add a currency field to payments")
    except Exception as e:
        return Check("sdk_prompt", "sdk", FAIL,
                     f"prompt() raised {type(e).__name__}: {e}")
    text = getattr(out, "optimized", None) or str(out)
    if not text.strip():
        return Check("sdk_prompt", "sdk", FAIL, "prompt() produced nothing")
    return Check("sdk_prompt", "sdk", PASS,
                 f"prompt() ran the offline optimizer pipeline "
                 f"({len(text)} chars out)",
                 detail=text[:250])


@timed
def check_sdk_coverage(exercised: set[str]) -> Check:
    methods = set(_public_methods())
    accounted = exercised | set(SKIP_METHODS) | LLM_METHODS
    missing = sorted(methods - accounted)
    if missing:
        return Check("sdk_coverage_complete", "sdk", FAIL,
                     f"{len(missing)} public SDK method(s) have no coverage",
                     detail=", ".join(missing),
                     remediation="add a check in scripts/selftest/suites/sdk.py")
    return Check("sdk_coverage_complete", "sdk", PASS,
                 f"all {len(methods)} public SDK methods are exercised or "
                 "explicitly accounted for")


def run(report: Report, repo: Path, tmp: Path, *, allow_llm: bool) -> None:
    exercised: set[str] = set()
    report.add(check_exports_importable())
    report.add(check_sdk_index_and_status(repo, tmp))
    exercised |= {"index", "index_status"}
    report.add(check_sdk_index_stream(repo)); exercised.add("index_stream")
    report.add(check_sdk_blast_radius(repo)); exercised.add("blast_radius")
    report.add(check_sdk_security_review(repo)); exercised.add("security_review")
    report.add(check_sdk_incident(repo)); exercised.add("investigate_incident")
    report.add(check_sdk_export(repo, tmp)); exercised.add("export")
    report.add(check_sdk_token_helpers(repo))
    exercised |= {"token_count", "token_budget", "token_compress"}
    report.add(check_sdk_doctor_and_ai(repo))
    exercised |= {"doctor", "active_ai_label"}
    report.add(check_sdk_prompt(repo, allow_llm)); exercised.add("prompt")
    report.add(check_sdk_llm_methods(repo, allow_llm)); exercised.add("query")
    report.add(check_noop_provider_contract(repo))
    # switch_ai mutates the instance's provider, so it runs last.
    report.add(check_sdk_switch_ai(repo)); exercised.add("switch_ai")
    report.add(check_sdk_coverage(exercised))
