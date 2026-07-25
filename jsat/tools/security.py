"""jsat.tools.security — Tool 6: Security Review Agent."""
from __future__ import annotations

import math
import subprocess
import time
from pathlib import Path
from typing import Any

from jsat.tools import BaseTool

_SCAN_EXTS = frozenset({".py", ".js", ".ts", ".go", ".yaml", ".env", ".json"})
_SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_SEMGREP_MAP = {"ERROR": "critical", "WARNING": "high", "INFO": "medium"}


def _entropy(s: str) -> float:
    """Shannon entropy of a string. Exported for tests."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((f / n) * math.log2(f / n) for f in freq.values())


class SecurityTool(BaseTool):
    """Runs Semgrep static analysis + secret detection + dependency count."""

    def run(self, path: Path, severity_threshold: str = "medium",
            include_deps: bool = True) -> Any:
        import structlog

        from jsat._models import SecurityReport

        log = structlog.get_logger(__name__)
        log.info("security_start", path=str(path), threshold=severity_threshold)
        t0 = time.monotonic()

        findings = self._run_semgrep(path, severity_threshold, log)
        secrets = self._detect_secrets(path, log)
        if include_deps:
            log.info("security_deps_stub",
                     note="CVE check via osv.dev planned for v0.2")

        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("security_done", findings=len(findings),
                 secrets=secrets, duration_ms=duration_ms)

        return SecurityReport(findings=findings, cves=[], secrets_found=secrets,
                              duration_ms=duration_ms)

    def _run_semgrep(self, path: Path, threshold: str, log: Any) -> list:
        import json

        from jsat._models import SecurityFinding

        try:
            result = subprocess.run(
                ["semgrep", "--json", "--config=p/owasp-top-ten",
                 "--config=p/secrets", str(path)],
                capture_output=True, text=True, timeout=120,
            )
            raw = json.loads(result.stdout or "{}")
            findings = []
            for item in raw.get("results", []):
                sev = _SEMGREP_MAP.get(item.get("extra", {}).get("severity", "INFO").upper(), "medium")
                if _SEVERITY_ORDER.get(sev, 0) >= _SEVERITY_ORDER.get(threshold, 0):
                    findings.append(SecurityFinding(
                        file=item.get("path", ""), line=item.get("start", {}).get("line", 0),
                        category=item.get("check_id", ""), severity=sev,  # type: ignore[arg-type]
                        title=item.get("check_id", ""),
                        description=item.get("extra", {}).get("message", ""),
                    ))
            return findings
        except FileNotFoundError:
            log.warning("semgrep_not_found",
                        detail="Install jsat[standard] for static analysis")
            return []
        except Exception as e:
            log.warning("semgrep_error", error=str(e))
            return []

    def _detect_secrets(self, path: Path, log: Any) -> int:
        threshold = 4.5
        count = 0
        for fpath in path.rglob("*"):
            if not fpath.is_file() or fpath.suffix not in _SCAN_EXTS:
                continue
            try:
                for line in fpath.read_text(errors="ignore").splitlines():
                    for tok in line.split():
                        if len(tok) >= 16 and _entropy(tok) > threshold:
                            count += 1
            except Exception:
                pass
        return count
