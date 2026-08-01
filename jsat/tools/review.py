"""jsat.tools.review — Tool 9: Multi-Model Code Review (true parallel dispatch)."""
from __future__ import annotations

import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from jsat._call_context import checkpoint
from jsat.tools import BaseTool

if TYPE_CHECKING:
    from jsat._ai import AIProvider


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ReviewFinding:
    file: str | None
    line: int | None
    severity: str
    title: str
    description: str
    confidence: str          # "high" | "medium" | "low"
    models_agreed: list[str] = field(default_factory=list)


@dataclass
class ReviewReport:
    findings: list[ReviewFinding]
    high_confidence: list[ReviewFinding]
    total_models_used: int
    duration_ms: int


_CONFIDENCE_ORDER: dict[str, int] = {"high": 3, "medium": 2, "low": 1}

# Provider strings that map to known classes
_KNOWN_PROVIDERS = frozenset(
    {"claude_cli", "anthropic", "openai", "openai_compat", "ollama"}
)


# ── Provider factory ──────────────────────────────────────────────────────────

def _make_provider(entry: dict[str, Any], cfg: Any) -> AIProvider | None:
    """
    Build an AIProvider from a model-list config entry.

    Accepted entry shapes:
        {"provider": "anthropic", "model": "claude-sonnet-4-6"}
        {"provider": "ollama",    "model": "llama3.2"}
        {"provider": "openai",    "model": "gpt-4o"}
        {"provider": "claude_cli","model": "claude-sonnet-4-6"}
        {"provider": "openai_compat", "model": "local-model",
         "base_url": "http://localhost:1234/v1"}

    Returns None if the provider cannot be imported or the entry is invalid.
    The caller logs the failure — this function stays silent except for its own
    import-error guard so that optional extras don't crash the whole review.
    """
    import structlog
    log = structlog.get_logger(__name__)

    provider_key: str = (entry.get("provider") or "").strip().lower()
    model_name: str = entry.get("model") or ""

    if not provider_key or provider_key not in _KNOWN_PROVIDERS:
        log.warning(
            "review_provider_unknown",
            provider=provider_key,
            valid=sorted(_KNOWN_PROVIDERS),
        )
        return None

    # Build a minimal cfg-like object by cloning the original cfg and overriding
    # the ai sub-section so that every provider constructor reads the right model.
    try:
        overrides: dict[str, Any] = {"model": model_name}
        if "base_url" in entry:
            overrides["base_url"] = entry["base_url"]
        if "api_key_env" in entry:
            overrides["api_key_env"] = entry["api_key_env"]

        # Use pydantic model_copy when available (it is, since we always have pydantic)
        patched_ai = cfg.ai.model_copy(update=overrides)
        patched_cfg = cfg.model_copy(update={"ai": patched_ai})
    except Exception as exc:
        log.warning(
            "review_provider_cfg_patch_failed",
            provider=provider_key,
            model=model_name,
            error=str(exc),
        )
        return None

    try:
        if provider_key == "claude_cli":
            from jsat._ai.claude_cli import ClaudeCliProvider
            return ClaudeCliProvider(patched_cfg)

        if provider_key == "anthropic":
            from jsat._ai.anthropic import AnthropicProvider  # type: ignore[import]
            return AnthropicProvider(patched_cfg)

        if provider_key == "openai":
            from jsat._ai.openai import OpenAIProvider  # type: ignore[import]
            return OpenAIProvider(patched_cfg)

        if provider_key == "openai_compat":
            from jsat._ai.openai_compat import OpenAICompatProvider
            return OpenAICompatProvider(patched_cfg)

        if provider_key == "ollama":
            from jsat._ai.ollama import OllamaProvider
            return OllamaProvider(patched_cfg)

    except ImportError as exc:
        log.warning(
            "review_provider_import_failed",
            provider=provider_key,
            model=model_name,
            error=str(exc),
            hint="Install the matching jsat extra, e.g. pip install 'jsat[anthropic]'",
        )
        return None
    except Exception as exc:
        log.warning(
            "review_provider_init_failed",
            provider=provider_key,
            model=model_name,
            error=str(exc),
        )
        return None

    # Unreachable, but satisfies type checker
    return None  # pragma: no cover


# ── Per-model worker (runs inside ThreadPoolExecutor) ─────────────────────────

def _call_model(
    ai: AIProvider,
    label: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, list[dict]]:
    """
    Call a single AI provider and return (label, parsed_findings).

    Never raises — any error produces an empty findings list so that failures
    in one model do not abort the review.  The caller already logged the
    warning before we returned from the future.
    """
    import structlog
    log = structlog.get_logger(__name__)

    log.info("review_model_start", label=label, prompt_len=len(prompt))
    t0 = time.monotonic()

    try:
        response = ai.complete(prompt, max_tokens=max_tokens)
        elapsed = round((time.monotonic() - t0) * 1000)
        findings = _parse_response(response, label)
        log.info(
            "review_model_done",
            label=label,
            response_len=len(response),
            findings=len(findings),
            elapsed_ms=elapsed,
        )
        return label, findings

    except Exception as exc:
        elapsed = round((time.monotonic() - t0) * 1000)
        log.warning(
            "review_model_call_failed",
            label=label,
            error=str(exc),
            elapsed_ms=elapsed,
        )
        return label, []


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_response(response: str, label: str) -> list[dict]:
    """
    Extract a JSON array from a model response.

    The models are instructed to emit ONLY a JSON array, but they sometimes
    wrap it in a markdown code fence or add a preamble.  We tolerate both.
    """
    import structlog
    log = structlog.get_logger(__name__)

    # First: try the raw response in case it is already clean JSON
    stripped = response.strip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    # Second: pull the first [...] block out of the text (handles markdown fences)
    m = re.search(r"\[.*?\]", response, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    log.warning(
        "review_parse_failed",
        label=label,
        response_preview=response[:200],
    )
    return []


# ── Deduplication and confidence ranking ──────────────────────────────────────

def _dedup_and_rank(
    all_findings: list[tuple[str, dict]],
) -> list[ReviewFinding]:
    """
    Merge findings from multiple models.

    Deduplication key: first 40 chars of the title, case-folded.
    Confidence:
      - HIGH   → ≥ 2 models reported the same issue
      - MEDIUM → 1 model, severity == "high" or "critical"
      - LOW    → 1 model, any other severity

    Within each group the first occurrence is used as the canonical record.
    """
    groups: dict[str, list[tuple[str, dict]]] = {}
    for model_label, finding in all_findings:
        key = finding.get("title", "")[:40].lower().strip()
        groups.setdefault(key, []).append((model_label, finding))

    results: list[ReviewFinding] = []
    for group in groups.values():
        agreed_models = [m for m, _ in group]
        canonical = group[0][1]
        sev = (canonical.get("severity") or "low").lower()

        if len(agreed_models) >= 2:
            confidence = "high"
        elif sev in ("critical", "high"):
            confidence = "medium"
        else:
            confidence = "low"

        results.append(ReviewFinding(
            file=canonical.get("file"),
            line=canonical.get("line"),
            severity=sev,
            title=canonical.get("title", ""),
            description=canonical.get("description", ""),
            confidence=confidence,
            models_agreed=agreed_models,
        ))

    # Sort: high confidence first, then by severity within tier
    _sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
    results.sort(
        key=lambda f: (
            -_CONFIDENCE_ORDER.get(f.confidence, 1),
            -_sev_order.get(f.severity, 0),
        )
    )
    return results


# ── ReviewTool ────────────────────────────────────────────────────────────────

class ReviewTool(BaseTool):
    """
    Dispatches the same diff to multiple AI models IN PARALLEL,
    deduplicates findings, and ranks by cross-model agreement.

    Config (all under cfg.review if the model supports it, else defaults):
        cfg.review.models                  — list of {provider, model} dicts
        cfg.review.parallel_timeout_seconds — per-model timeout (default 90)
        cfg.review.min_confidence          — "high"|"medium"|"low" (default "medium")
    """

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        diff: str | None = None,
        base: str = "main",
        head: str = "HEAD",
        min_confidence: str = "medium",
    ) -> ReviewReport:
        import structlog
        log = structlog.get_logger(__name__)

        cfg = self._cfg
        t0 = time.monotonic()

        # Resolve configuration for this run
        review_cfg = getattr(cfg, "review", None)
        timeout: int = int(
            getattr(review_cfg, "parallel_timeout_seconds", None) or 90
        )
        configured_models: list[dict] | None = getattr(
            review_cfg, "models", None
        )

        log.info(
            "review_start",
            base=base,
            head=head,
            min_confidence=min_confidence,
            timeout_seconds=timeout,
            model_entries=len(configured_models) if configured_models else "fallback",
        )

        # ── 1. Get diff (once, before dispatching) ────────────────────────────
        checkpoint(f"review: fetching git diff {base}...{head}")
        if diff is None:
            diff = self._get_diff(base, head)

        if not diff.strip():
            log.warning("review_empty_diff", base=base, head=head)
            checkpoint("review: WARNING — empty diff, nothing to review")
            return ReviewReport(
                findings=[],
                high_confidence=[],
                total_models_used=0,
                duration_ms=0,
            )

        log.info("review_diff_ready", diff_bytes=len(diff))
        checkpoint(f"review: diff ready — {len(diff)} bytes")

        # ── 2. Build prompt ───────────────────────────────────────────────────
        checkpoint("review: building review prompt")
        prompt = self._build_prompt(diff)
        checkpoint(f"review: prompt built — {len(prompt)} chars")

        # ── 3. Build model list ───────────────────────────────────────────────
        checkpoint("review: resolving AI providers")
        providers = self._resolve_providers(configured_models, cfg, log)

        if not providers:
            log.error("review_no_providers_available")
            checkpoint("review: ERROR — no AI providers available")
            return ReviewReport(
                findings=[],
                high_confidence=[],
                total_models_used=0,
                duration_ms=round((time.monotonic() - t0) * 1000),
            )

        provider_labels = [lbl for lbl, _ in providers]
        log.info("review_dispatch", providers=provider_labels)
        checkpoint(f"review: dispatching to {len(providers)} model(s): {', '.join(provider_labels)}")

        # ── 4. Parallel dispatch ──────────────────────────────────────────────
        all_raw: list[tuple[str, dict]] = []
        successful_models: list[str] = []

        with ThreadPoolExecutor(max_workers=len(providers)) as pool:
            futures = {
                pool.submit(_call_model, ai, label, prompt, 2048): label
                for label, ai in providers
            }

            for future, label in futures.items():
                try:
                    result_label, findings = future.result(timeout=timeout)
                    successful_models.append(result_label)
                    all_raw.extend((result_label, f) for f in findings)
                    checkpoint(f"review: model '{result_label}' done — {len(findings)} raw finding(s)")
                    log.debug(
                        "review_future_collected",
                        label=label,
                        findings_count=len(findings),
                    )
                except FutureTimeoutError:
                    log.warning(
                        "review_model_timeout",
                        label=label,
                        timeout_seconds=timeout,
                    )
                    checkpoint(f"review: model '{label}' timed out after {timeout}s")
                except Exception as exc:
                    log.warning(
                        "review_future_error",
                        label=label,
                        error=str(exc),
                    )
                    checkpoint(f"review: model '{label}' error — {exc}")

        log.info(
            "review_collection_complete",
            models_attempted=len(providers),
            models_succeeded=len(successful_models),
            raw_findings=len(all_raw),
        )
        checkpoint(
            f"review: all models done — "
            f"{len(successful_models)}/{len(providers)} succeeded, "
            f"{len(all_raw)} raw finding(s)"
        )

        # ── 5. Deduplicate and rank ───────────────────────────────────────────
        checkpoint("review: deduplicating and ranking findings across models")
        findings = _dedup_and_rank(all_raw)

        log.info(
            "review_dedup_complete",
            unique_findings=len(findings),
        )
        checkpoint(f"review: {len(findings)} unique finding(s) after dedup")

        # ── 6. Filter by minimum confidence ──────────────────────────────────
        checkpoint(f"review: filtering by min_confidence='{min_confidence}'")
        min_rank = _CONFIDENCE_ORDER.get(min_confidence, 2)
        findings = [
            f for f in findings
            if _CONFIDENCE_ORDER.get(f.confidence, 1) >= min_rank
        ]

        high = [f for f in findings if f.confidence == "high"]
        duration_ms = round((time.monotonic() - t0) * 1000)

        log.info(
            "review_done",
            findings_after_filter=len(findings),
            high_confidence=len(high),
            models_used=len(successful_models),
            duration_ms=duration_ms,
        )
        checkpoint(
            f"review: DONE — {len(findings)} finding(s) "
            f"({len(high)} high-confidence), "
            f"{len(successful_models)} model(s) used, {duration_ms}ms"
        )

        return ReviewReport(
            findings=findings,
            high_confidence=high,
            total_models_used=len(successful_models),
            duration_ms=duration_ms,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolve_providers(
        self,
        configured_models: list[dict] | None,
        cfg: Any,
        log: Any,
    ) -> list[tuple[str, AIProvider]]:
        """
        Return a list of (label, provider) pairs ready for dispatch.

        Falls back to the single configured self._ai when cfg.review.models
        is absent or empty.
        """
        providers: list[tuple[str, AIProvider]] = []

        if configured_models:
            for entry in configured_models:
                provider_key = entry.get("provider", "unknown")
                model_name = entry.get("model", "")
                label = f"{provider_key}/{model_name}" if model_name else provider_key

                log.debug("review_building_provider", label=label, entry=entry)
                ai = _make_provider(entry, cfg)
                if ai is None:
                    log.warning(
                        "review_provider_skipped",
                        label=label,
                        reason="provider construction failed (see earlier warning)",
                    )
                    continue
                providers.append((label, ai))
        else:
            # No multi-model config — fall back to the single configured AI
            if self._ai is not None:
                label = (
                    f"{self._ai.provider_name}/{self._ai.model_name}"
                    if hasattr(self._ai, "model_name")
                    else getattr(cfg, "ai", {}).provider or "default"
                )
                log.info(
                    "review_fallback_single_provider",
                    label=label,
                )
                providers.append((label, self._ai))
            else:
                log.warning(
                    "review_no_ai_configured",
                    hint="Set cfg.review.models or pass an AIProvider to ReviewTool",
                )

        return providers

    def _get_diff(self, base: str, head: str) -> str:
        """Run git diff once and return the first 16 000 chars."""
        import structlog
        log = structlog.get_logger(__name__)
        try:
            log.debug("review_git_diff", base=base, head=head)
            result = subprocess.run(
                ["git", "diff", f"{base}...{head}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                log.warning(
                    "review_git_diff_nonzero",
                    returncode=result.returncode,
                    stderr=result.stderr.strip()[:300],
                )
            diff = result.stdout[:16_000]
            log.debug("review_git_diff_done", diff_bytes=len(diff))
            return diff
        except subprocess.TimeoutExpired:
            log.error("review_git_diff_timeout")
            return ""
        except Exception as exc:
            log.error("review_git_diff_error", error=str(exc))
            return ""

    def _build_prompt(self, diff: str) -> str:
        """
        Build the review prompt.  All models receive the identical prompt so
        that cross-model deduplication is meaningful.
        """
        return (
            "You are a security-aware code reviewer. Examine the diff for:\n"
            "- Logic bugs (off-by-one errors, wrong conditions, unhandled branches)\n"
            "- Security issues (injection, unvalidated input, auth bypass, secret leaks)\n"
            "- Null/error handling gaps (missing checks on external calls)\n"
            "- API contract violations (changed signatures, removed required fields)\n"
            "Report ONLY confirmed findings — no speculative or style issues.\n"
            'Return ONLY a JSON array: [{"file":"...","line":null,'
            '"severity":"high|medium|low","title":"...","description":"..."}]\n'
            "Return [] if no issues found.\n\n"
            f"DIFF:\n{diff}\n\n"
            "FINDINGS JSON:"
        )
