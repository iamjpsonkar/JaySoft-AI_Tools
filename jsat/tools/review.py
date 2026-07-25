"""jsat.tools.review — Tool 9: Multi-Model Code Review."""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field

from jsat.tools import BaseTool


@dataclass
class ReviewFinding:
    file: str | None
    line: int | None
    severity: str
    title: str
    description: str
    confidence: str   # "high"|"medium"|"low"
    models_agreed: list[str] = field(default_factory=list)


@dataclass
class ReviewReport:
    findings: list[ReviewFinding]
    high_confidence: list[ReviewFinding]
    total_models_used: int
    duration_ms: int


_CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}


class ReviewTool(BaseTool):
    """Dispatches same diff to multiple AI models, deduplicates, ranks by confidence."""

    def run(self, diff: str | None = None, base: str = "main", head: str = "HEAD",
            models: list[str] | None = None, min_confidence: str = "medium") -> ReviewReport:
        import structlog
        log = structlog.get_logger(__name__)
        log.info("review_start", base=base, head=head)
        t0 = time.monotonic()

        if diff is None:
            diff = self._get_diff(base, head)
        if not diff.strip():
            log.warning("review_empty_diff")
            return ReviewReport(findings=[], high_confidence=[], total_models_used=0, duration_ms=0)

        prompt = self._prompt(diff)
        all_raw: list[tuple[str, dict]] = []

        model_list = models or ["default"]
        for model_name in model_list:
            try:
                resp = self._ai.complete(prompt, max_tokens=2048)  # type: ignore[union-attr]
                parsed = self._parse(resp, model_name)
                all_raw.extend((model_name, f) for f in parsed)
                log.info("review_model_done", model=model_name, findings=len(parsed))
            except Exception as e:
                log.error("review_model_error", model=model_name, error=str(e))

        findings = self._dedup(all_raw)
        min_rank = _CONFIDENCE_ORDER.get(min_confidence, 2)
        findings = [f for f in findings if _CONFIDENCE_ORDER.get(f.confidence, 1) >= min_rank]
        high = [f for f in findings if f.confidence == "high"]
        duration_ms = round((time.monotonic() - t0) * 1000)

        log.info("review_done", findings=len(findings), high=len(high), duration_ms=duration_ms)
        return ReviewReport(findings=findings, high_confidence=high,
                            total_models_used=len(model_list), duration_ms=duration_ms)

    def _get_diff(self, base: str, head: str) -> str:
        try:
            r = subprocess.run(["git", "diff", f"{base}...{head}"],
                               capture_output=True, text=True)
            return r.stdout[:16000]
        except Exception:
            return ""

    def _prompt(self, diff: str) -> str:
        return (
            'Review this code diff for bugs. Return ONLY a JSON array: '
            '[{"file":"...","line":null,"severity":"high|medium|low","title":"...","description":"..."}]\n'
            f'Return [] if no issues.\n\nDIFF:\n{diff}\n\nFINDINGS JSON:'
        )

    def _parse(self, response: str, model: str) -> list[dict]:
        m = re.search(r"\[.*\]", response, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        return []

    def _dedup(self, all_findings: list[tuple[str, dict]]) -> list[ReviewFinding]:
        groups: dict[str, list[tuple[str, dict]]] = {}
        for model, f in all_findings:
            key = f.get("title", "")[:40].lower().strip()
            groups.setdefault(key, []).append((model, f))

        results = []
        for group in groups.values():
            models = [m for m, _ in group]
            best = group[0][1]
            confidence = "high" if len(models) >= 2 else \
                        "medium" if best.get("severity", "") in ("critical", "high") else "low"
            results.append(ReviewFinding(
                file=best.get("file"), line=best.get("line"),
                severity=best.get("severity", "low"), title=best.get("title", ""),
                description=best.get("description", ""),
                confidence=confidence, models_agreed=models,
            ))
        return results
