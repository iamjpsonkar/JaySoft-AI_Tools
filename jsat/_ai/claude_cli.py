"""
jsat._ai.claude_cli — Uses the 'claude' CLI binary as an AI provider.

If you have Claude Code (claude CLI) installed globally, JSAT can use it
directly — no ANTHROPIC_API_KEY required. It uses the same session/auth
that Claude Code already has.

Usage in JSAT:
  jsat ai use claude-cli
  switch claude-cli   (inside jsat shell)
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from typing import Iterator

from jsat._ai import AIProvider


class ClaudeCliProvider(AIProvider):
    """AI provider backed by the 'claude' CLI binary (Claude Code)."""

    def __init__(self, cfg=None) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)

        self._binary = shutil.which("claude") or "claude"
        self._model = getattr(getattr(cfg, "ai", None), "model", None) or "claude-sonnet-4-6"
        self._timeout = getattr(getattr(cfg, "ai", None), "timeout_seconds", None) or 120

        if not shutil.which("claude"):
            self._log.warning(
                "claude_cli_not_found",
                message="'claude' binary not in PATH — install Claude Code: https://claude.ai/code",
            )
        else:
            self._log.info("claude_cli_init", binary=self._binary, model=self._model)

    @property
    def provider_name(self) -> str:
        return "claude_cli"

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        return bool(shutil.which("claude"))

    def complete(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        import structlog
        log = structlog.get_logger(__name__)

        if not shutil.which("claude"):
            raise RuntimeError(
                "'claude' CLI not found. Install Claude Code: https://claude.ai/code\n"
                "Or switch to API: switch anthropic"
            )

        log.debug("claude_cli_complete", prompt_len=len(prompt), model=self._model)
        t0 = time.monotonic()

        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            from jsat._exceptions import AITimeoutError
            raise AITimeoutError(
                f"claude CLI timed out after {self._timeout}s",
                provider="claude_cli",
                timeout_seconds=self._timeout,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "'claude' command not found.\n"
                "Install: https://claude.ai/code or switch provider: switch anthropic"
            )

        elapsed = round((time.monotonic() - t0) * 1000)

        if result.returncode != 0:
            stderr = result.stderr.strip()
            log.error("claude_cli_error", returncode=result.returncode,
                      stderr=stderr[:500], elapsed_ms=elapsed)
            raise RuntimeError(f"claude CLI failed (exit {result.returncode}): {stderr[:300]}")

        text = result.stdout.strip()
        log.info("claude_cli_complete_done", response_len=len(text), duration_ms=elapsed)
        return text

    async def complete_async(self, prompt: str, max_tokens: int = 2048,
                             temperature: float = 0.1) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 2048) -> Iterator[str]:
        """Stream output from claude CLI line by line."""
        import structlog
        log = structlog.get_logger(__name__)

        if not shutil.which("claude"):
            raise RuntimeError("'claude' CLI not found.")

        log.debug("claude_cli_stream_start", prompt_len=len(prompt))
        total = 0

        try:
            proc = subprocess.Popen(
                ["claude", "-p", prompt, "--output-format", "text"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                total += len(line)
                yield line
            proc.wait(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            from jsat._exceptions import AITimeoutError
            raise AITimeoutError(
                f"claude CLI stream timed out after {self._timeout}s",
                provider="claude_cli",
                timeout_seconds=self._timeout,
            )
        except Exception as e:
            log.error("claude_cli_stream_error", error=str(e))
            raise

        log.info("claude_cli_stream_done", total_chars=total)
