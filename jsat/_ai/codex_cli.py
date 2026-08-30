"""
jsat._ai.codex_cli — OpenAI Codex CLI integration.

Uses `codex exec` for non-interactive completions so JSAT MCP tools can use the
same local Codex installation that launched the session. Streaming falls back to a
single complete() call because Codex's JSONL event stream is agent-oriented rather
than a stable token-delta contract for JSAT.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from collections.abc import Iterator

from jsat._ai import AIProvider


class CodexCliProvider(AIProvider):
    """Stateless AIProvider backed by `codex exec`."""

    def __init__(self, cfg=None) -> None:
        import structlog

        self._log = structlog.get_logger(__name__)
        self._binary = shutil.which("codex") or "codex"
        # No fallback model: Codex owns its configured/default model. Only an
        # explicit user selection is forwarded to ``codex exec``.
        self._model = getattr(getattr(cfg, "ai", None), "model", None)
        self._timeout = getattr(getattr(cfg, "ai", None), "timeout_seconds", None) or 180
        self._repo_dir: str | None = None

        if not shutil.which("codex"):
            self._log.warning(
                "codex_cli_not_found",
                message="'codex' binary not in PATH. Install Codex CLI first.",
            )
        else:
            self._log.info("codex_cli_init", binary=self._binary, model=self._model)

    def configure(
        self,
        repo_dir: str | None = None,
        system_prompt: str | None = None,
        stateful: bool = False,
    ) -> None:
        """Accept the same hook shape as other CLI providers.

        `codex exec` is intentionally stateless here; the host Codex session owns
        conversation history.
        """
        self._repo_dir = repo_dir

    @property
    def provider_name(self) -> str:
        return "codex_cli"

    @property
    def model_name(self) -> str:
        return self._model or "codex default"

    def is_available(self) -> bool:
        return bool(shutil.which("codex"))

    def _build_args(self) -> list[str]:
        """Build a non-interactive, read-only Codex command.

        Use a config override for the approval policy instead of the
        ``--ask-for-approval`` flag.  The config key is stable across Codex CLI
        releases, while the flag is absent from some versions.  The prompt is
        read from stdin (the trailing ``-``) so large graph contexts do not hit
        command-line length limits or appear in process listings.
        """
        args = [
            self._binary,
            "exec",
            "--config",
            'approval_policy="never"',
            "--sandbox",
            "read-only",
            "--ephemeral",
        ]
        if self._repo_dir:
            args += ["--cd", self._repo_dir]
        if self._model:
            args += ["--model", self._model]
        args.append("-")
        return args

    def complete(self, prompt: str, max_tokens: int = 8192, temperature: float = 0.1) -> str:
        import structlog

        log = structlog.get_logger(__name__)
        if not shutil.which("codex"):
            raise RuntimeError("`codex` CLI not found. Install Codex CLI first.")

        args = self._build_args()
        log.debug("codex_cli_complete", prompt_len=len(prompt))
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                input=prompt,
                timeout=self._timeout,
                cwd=self._repo_dir,
            )
        except subprocess.TimeoutExpired as e:
            from jsat._exceptions import AITimeoutError

            raise AITimeoutError(
                f"codex timed out after {self._timeout}s",
                provider="codex_cli",
                timeout_seconds=self._timeout,
            ) from e

        elapsed = round((time.monotonic() - t0) * 1000)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            log.error(
                "codex_cli_error",
                returncode=result.returncode,
                stderr=stderr[:300],
                elapsed_ms=elapsed,
            )
            from jsat._ai import model_help

            raise RuntimeError(
                f"codex exited {result.returncode}: {stderr[:200]}\n{model_help('codex_cli')}"
            )

        text = result.stdout.strip()
        log.info("codex_cli_done", response_len=len(text), elapsed_ms=elapsed)
        return text

    async def complete_async(
        self, prompt: str, max_tokens: int = 8192, temperature: float = 0.1
    ) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 8192) -> Iterator[str]:
        yield self.complete(prompt, max_tokens=max_tokens)
