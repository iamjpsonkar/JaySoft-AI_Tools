"""jsat.tools.security — Tool 6: Security Review Agent."""
from __future__ import annotations

import json
import math
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from jsat._call_context import checkpoint
from jsat.tools import BaseTool

_SCAN_EXTS = frozenset({".py", ".js", ".ts", ".go", ".yaml", ".env", ".json"})
_SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_SEMGREP_MAP = {"ERROR": "critical", "WARNING": "high", "INFO": "medium"}

_SECRET_PATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    "aws_access_key_id":    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), "critical"),
    "github_token":         (re.compile(r'\bgh[ps]_[A-Za-z0-9]{36}\b'), "critical"),
    "github_fine_grained":  (re.compile(r'\bgithub_pat_[A-Za-z0-9_]{82}\b'), "critical"),
    "google_api_key":       (re.compile(r'\bAIza[0-9A-Za-z\-_]{35}\b'), "high"),
    "slack_token":          (re.compile(r'\bxox[baprs]-[0-9A-Za-z\-]{10,48}\b'), "high"),
    "stripe_live_key":      (re.compile(r'\bsk_live_[0-9A-Za-z]{24}\b'), "critical"),
    "private_key_header":   (re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'), "critical"),
    "jwt_token":            (re.compile(r'\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.'), "medium"),
    "generic_token":        (re.compile(
        r'(?i)(?:api[_\-]?key|access[_\-]?token|auth[_\-]?token|secret[_\-]?key)\s*[=:]\s*["\']([A-Za-z0-9_\-]{20,64})["\']'
    ), "high"),
}


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
    """Runs Semgrep static analysis + secret detection + dependency CVE checks."""

    def run(self, path: Path, severity_threshold: str = "medium",
            include_deps: bool = True) -> Any:
        import structlog

        from jsat._models import SecurityReport

        log = structlog.get_logger(__name__)
        log.info("security_start", path=str(path), threshold=severity_threshold,
                 include_deps=include_deps)
        t0 = time.monotonic()

        checkpoint(f"security: starting semgrep scan on '{path}'")
        findings = self._run_semgrep(path, severity_threshold, log)
        checkpoint(f"security: semgrep done — {len(findings)} finding(s) at threshold={severity_threshold}")

        checkpoint(f"security: starting secret detection scan on '{path}'")
        secrets_count, secret_findings = self._detect_secrets(path, log)
        checkpoint(f"security: secret scan done — {secrets_count} potential secret(s)")

        if include_deps:
            checkpoint("security: starting CVE check for dependencies")
            cve_list = self._check_cves(path, log)
            checkpoint(f"security: CVE check done — {len(cve_list)} CVE(s)")
        else:
            cve_list = []
            checkpoint("security: CVE check skipped (include_deps=False)")

        checkpoint(
            f"security: all checks complete — "
            f"semgrep={len(findings)} secrets={secrets_count} cves={len(cve_list)}"
        )
        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("security_done", semgrep_findings=len(findings),
                 secrets=secrets_count, cves=len(cve_list), duration_ms=duration_ms)

        return SecurityReport(
            findings=findings + secret_findings,
            cves=cve_list,
            secrets_found=secrets_count,
            duration_ms=duration_ms,
        )

    def _run_semgrep(self, path: Path, threshold: str, log: Any) -> list:
        import json

        from jsat._models import SecurityFinding

        try:
            checkpoint("security: launching semgrep (owasp-top-ten + secrets rules, timeout=120s)")
            result = subprocess.run(
                ["semgrep", "--json", "--config=p/owasp-top-ten",
                 "--config=p/secrets", str(path)],
                capture_output=True, text=True, timeout=120,
            )
            checkpoint("security: semgrep process returned")
            raw = json.loads(result.stdout or "{}")
            findings = []
            for item in raw.get("results", []):
                sev = _SEMGREP_MAP.get(
                    item.get("extra", {}).get("severity", "INFO").upper(), "medium"
                )
                if _SEVERITY_ORDER.get(sev, 0) >= _SEVERITY_ORDER.get(threshold, 0):
                    findings.append(SecurityFinding(
                        file=item.get("path", ""), line=item.get("start", {}).get("line", 0),
                        category=item.get("check_id", ""), severity=sev,  # type: ignore[arg-type]
                        title=item.get("check_id", ""),
                        description=item.get("extra", {}).get("message", ""),
                    ))
            log.info("semgrep_done", findings=len(findings), threshold=threshold)
            return findings
        except FileNotFoundError:
            log.warning("semgrep_not_found",
                        detail="Install jsat[standard] for static analysis")
            return []
        except Exception as e:
            log.warning("semgrep_error", error=str(e))
            return []

    def _detect_secrets(self, path: Path, log: Any) -> tuple[int, list]:
        from jsat._models import SecurityFinding

        findings: list[SecurityFinding] = []
        entropy_threshold = 4.8   # raised from 4.5 — eliminates false positives on CLI help text / test fixtures
        min_token_len = 24         # raised from 20 — further reduces noise from short high-entropy identifiers
        files_scanned = 0
        all_files = [f for f in path.rglob("*") if f.is_file() and f.suffix in _SCAN_EXTS]
        checkpoint(f"security: scanning {len(all_files)} file(s) for secrets")

        for fpath in all_files:
            try:
                lines = fpath.read_text(errors="ignore").splitlines()
            except Exception:
                continue

            files_scanned += 1
            if files_scanned % 50 == 0:
                checkpoint(f"security: secret scan progress — {files_scanned}/{len(all_files)} files")
            for lineno, line in enumerate(lines, 1):
                # Regex-based patterns — precise, with file + line context
                for pattern_name, (pattern, severity) in _SECRET_PATTERNS.items():
                    if pattern.search(line):
                        rel = str(fpath.relative_to(path) if path in fpath.parents else fpath)
                        log.debug("secret_pattern_match", pattern=pattern_name,
                                  file=rel, line=lineno, severity=severity)
                        findings.append(SecurityFinding(
                            file=rel, line=lineno,
                            category="secret_detection",
                            severity=severity,  # type: ignore[arg-type]
                            title=f"Potential secret: {pattern_name}",
                            description=f"Pattern '{pattern_name}' matched on line {lineno}",
                            remediation="Remove secret from source. Use environment variables or a secrets manager.",
                            rule_id=f"jsat.secret.{pattern_name}",
                        ))
                # Entropy fallback for unlabelled high-entropy tokens
                for tok in line.split():
                    if len(tok) >= min_token_len and _entropy(tok) > entropy_threshold:
                        rel = str(fpath.relative_to(path) if path in fpath.parents else fpath)
                        findings.append(SecurityFinding(
                            file=rel, line=lineno,
                            category="secret_detection",
                            severity="medium",
                            title="High-entropy token",
                            description=f"Token of length {len(tok)} with entropy {_entropy(tok):.2f}",
                            remediation="Verify this is not a hardcoded secret.",
                            rule_id="jsat.secret.high_entropy",
                        ))

        log.info("secret_detection_done", findings=len(findings), files_scanned=files_scanned)
        return len(findings), findings

    def _parse_requirements(self, path: Path) -> list[tuple[str, str]]:
        """Return (package_name, version) pairs from requirements*.txt files."""
        packages: list[tuple[str, str]] = []
        for req_file in list(path.rglob("requirements*.txt"))[:5]:
            for line in req_file.read_text(errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                m = re.match(r'^([A-Za-z0-9_\-\.]+)\s*(?:[>=<!~^]+\s*([A-Za-z0-9_\-\.]+))?', line)
                if m:
                    packages.append((m.group(1), m.group(2) or ""))
        return packages

    def _check_cves(self, path: Path, log: Any) -> list:
        from jsat._models import CVEFinding

        packages = self._parse_requirements(path)
        if not packages:
            log.debug("security_cve_no_packages",
                      detail="No requirements*.txt found; skipping CVE lookup")
            checkpoint("security: no requirements*.txt found — CVE check skipped")
            return []

        cves: list[CVEFinding] = []
        log.info("security_cve_start", packages=len(packages))
        capped = packages[:30]
        checkpoint(f"security: querying osv.dev for {len(capped)} package(s)")

        for i, (pkg_name, version) in enumerate(capped, 1):  # cap to avoid rate limits
            if i % 5 == 0 or i == 1:
                checkpoint(f"security: CVE check {i}/{len(capped)} — {pkg_name} {version}")
            try:
                query: dict = {"package": {"name": pkg_name, "ecosystem": "PyPI"}}
                if version:
                    query["version"] = version
                data = json.dumps(query).encode()
                req = urllib.request.Request(
                    "https://api.osv.dev/v1/query",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    result = json.loads(resp.read())

                for vuln in result.get("vulns", []):
                    # Extract CVSS score if present
                    cvss = 0.0
                    for sev in vuln.get("severity", []):
                        if sev.get("type") == "CVSS_V3":
                            try:
                                cvss = float(sev.get("score", 0))
                            except (ValueError, TypeError):
                                pass
                    sev_label = (
                        "critical" if cvss >= 9.0 else
                        "high" if cvss >= 7.0 else
                        "medium" if cvss >= 4.0 else
                        "low"
                    )
                    fix_versions: list[str] = []
                    for affected in vuln.get("affected", []):
                        for rng in affected.get("ranges", []):
                            for ev in rng.get("events", []):
                                if "fixed" in ev:
                                    fix_versions.append(ev["fixed"])
                    cve_id = vuln.get("id", "unknown")
                    log.debug("security_cve_found", package=pkg_name, version=version,
                              cve_id=cve_id, cvss=cvss, severity=sev_label)
                    cves.append(CVEFinding(
                        package=pkg_name,
                        version=version,
                        cve_id=cve_id,
                        cvss=cvss,
                        severity=sev_label,
                        fix_version=fix_versions[0] if fix_versions else None,
                        description=vuln.get("summary", "")[:200],
                    ))
            except Exception as e:
                log.debug("security_cve_lookup_failed", package=pkg_name, error=str(e))

        log.info("security_cve_done", cves=len(cves), packages_checked=min(len(packages), 30))
        return cves
