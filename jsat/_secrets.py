"""jsat._secrets — secret-detection primitives.

Extracted from ``jsat.tools.security`` so low-level code (the self-improvement
privacy filter) can scan for secrets without importing ``BaseTool`` or any graph
types. ``jsat.tools.security`` re-exports these for backward compatibility.
"""
from __future__ import annotations

import math
import re

_SECRET_PATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    "aws_access_key_id":    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), "critical"),
    "github_token":         (re.compile(r'\bgh[ps]_[A-Za-z0-9]{36}\b'), "critical"),
    "github_fine_grained":  (re.compile(r'\bgithub_pat_[A-Za-z0-9_]{82}\b'), "critical"),
    "google_api_key":       (re.compile(r'\bAIza[0-9A-Za-z\-_]{35}\b'), "high"),
    "slack_token":          (re.compile(r'\bxox[baprs]-[0-9A-Za-z\-]{10,48}\b'), "high"),
    "stripe_live_key":      (re.compile(r'\bsk_live_[0-9A-Za-z]{24}\b'), "critical"),
    "private_key_header":   (re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'), "critical"),  # noqa: E501
    "jwt_token":            (re.compile(r'\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.'), "medium"),  # noqa: E501
    "generic_token":        (re.compile(
        r'(?i)(?:api[_\-]?key|access[_\-]?token|auth[_\-]?token|secret[_\-]?key)\s*[=:]\s*["\']([A-Za-z0-9_\-]{20,64})["\']'
    ), "high"),
}

# Tokens at or above this entropy, and at least this long, are treated as secrets.
_ENTROPY_THRESHOLD = 4.8
_ENTROPY_MIN_LEN = 24

_TOKEN_RE = re.compile(rf'[A-Za-z0-9+/=_\-]{{{_ENTROPY_MIN_LEN},}}')


def _entropy(s: str) -> float:
    """Shannon entropy of a string. Exported for tests."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((f / n) * math.log2(f / n) for f in freq.values())


def looks_secret(text: str) -> bool:
    """True if ``text`` contains a known secret pattern or a high-entropy token.

    Deliberately biased toward false positives — callers drop the record entirely
    rather than trying to redact, so over-rejecting costs only a lost signal.
    """
    if not text:
        return False
    for pattern, _severity in _SECRET_PATTERNS.values():
        if pattern.search(text):
            return True
    return any(_entropy(t) >= _ENTROPY_THRESHOLD for t in _TOKEN_RE.findall(text))
