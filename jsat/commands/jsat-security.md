---
description: Run a security scan. Supports flags in $ARGUMENTS.
---

Parse $ARGUMENTS for optional flags, then call the right security tool:

Supported flags:
  --file <path>          → call jsat__security_scan_file with file=<path>
                            (--severity has NO effect on this call — the tool
                            takes no severity_threshold param; if combined,
                            say so and show unfiltered results)
  --secrets              → call jsat__list_secrets to find hardcoded credentials
                            (--severity has NO effect here either — same reason)
  --auth                 → call jsat__get_auth_coverage to show auth gaps
                            (--severity has NO effect here either — same reason)
  --cves [path]          → CVE check (see "CVE check" below — does NOT call
                            jsat__get_dependency_cves directly). --severity DOES
                            apply here, because this path reads
                            jsat__security_review's output under the hood.
  --severity critical    → filter to critical only (pass severity_threshold="critical").
                            Only takes effect on the default path scan and --cves
                            (both go through jsat__security_review); has no effect
                            when combined with --file, --secrets, or --auth.
  --severity high        → filter to high+ (default: medium). Same scope limit as above.
  (no flag / path only)  → call jsat__security_review with path=<rest or ".">

Flags are independent scans over different data, not composable filters on each
other: --severity only has an effect on tools that accept severity_threshold
(currently jsat__security_review and, by extension, --cves since it reads
security_review's output — --file/--secrets/--auth ignore it, so state that
plainly if the user combines --severity with one of those rather than silently
dropping it).

Examples:
  /jsat-security
    → jsat__security_review(path=".")
  /jsat-security src/payment/
    → jsat__security_review(path="src/payment/")
  /jsat-security --file src/auth/login.py
    → jsat__security_scan_file(file="src/auth/login.py")
  /jsat-security --secrets
    → jsat__list_secrets()
  /jsat-security --cves src/payment/
    → jsat__security_review(path="src/payment/") → read its `cves` field

CVE check (--cves):
  Do NOT call jsat__get_dependency_cves directly — as of this writing it
  unconditionally returns `status: "not_implemented"` regardless of the repo or
  package, so it will never produce real data and a command built only on it
  would silently report "0 CVEs" forever, which is worse than an error because
  it looks like a clean bill of health. Instead call
  jsat__security_review(path=<path or ".">) and read its `cves` field — that is
  the actual working CVE data path (same fix as /jsat-upgrade-impact Phase 2).
  If the `cves` field is itself empty/absent from the response, report that
  explicitly as "no CVE data returned" rather than as "0 vulnerabilities found" —
  those are different claims and conflating them overstates confidence.

Group findings by severity: Critical → High → Medium → Low.
For each finding: file, line, rule ID, description, remediation.

LARGE REPO STRATEGY: For repos >10k files, scan one directory at a time:
  /jsat-security src/auth/    then   /jsat-security src/payment/


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
