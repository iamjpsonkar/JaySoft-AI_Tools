"""
jsat._ai.claude_cli — Full Claude CLI integration.

Uses the real 'claude' binary with:
  --resume <session-id>   → multi-turn conversation with full history
  --system-prompt         → inject codebase context
  --add-dir <repo>        → claude can read/write files in the project
  --output-format stream-json → real streaming
  --model <model>         → model selection

This gives ALL claude CLI features inside jsat shell:
  ✓ Multi-turn conversation memory
  ✓ File reading / writing (Claude's Edit/Read tools)
  ✓ Bash execution (Claude's Bash tool)
  ✓ Model selection
  ✓ All claude slash commands
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from collections.abc import Iterator

from jsat._ai import AIProvider


class ClaudeCliProvider(AIProvider):
    """Full-featured Claude CLI provider with session continuity."""

    def __init__(self, cfg=None) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)

        self._binary = shutil.which("claude") or "claude"
        self._model = getattr(getattr(cfg, "ai", None), "model", None) or "claude-sonnet-4-6"
        self._timeout = getattr(getattr(cfg, "ai", None), "timeout_seconds", None) or 180

        # Session state
        self._session_id: str | None = None
        self._call_count: int = 0
        self._repo_dir: str | None = None
        self._system_prompt: str | None = None
        # stateful=False (default): each call independent — for MCP server
        # stateful=True: uses --continue for multi-turn — for interactive shell
        self._stateful: bool = False

        if not shutil.which("claude"):
            self._log.warning(
                "claude_cli_not_found",
                message="'claude' binary not in PATH. Install: https://claude.ai/code",
            )
        else:
            self._log.info("claude_cli_init", binary=self._binary, model=self._model)

    # ── Configuration (called by JSATShell before first message) ─────────────

    def configure(self, repo_dir: str | None = None,
                  system_prompt: str | None = None,
                  stateful: bool = True) -> None:
        """Inject repo context and enable stateful (multi-turn) mode.

        Call this from the interactive shell before the first complete().
        Do NOT call from the MCP server — MCP uses stateless mode by default.
        """
        self._repo_dir = repo_dir
        self._system_prompt = system_prompt
        self._stateful = stateful

    def new_session(self) -> None:
        """Start a fresh conversation (clears history)."""
        self._session_id = None
        self._call_count = 0
        self._log.info("claude_cli_new_session")

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ── AIProvider interface ──────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "claude_cli"

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        return bool(shutil.which("claude"))

    def _build_args(self, prompt: str, stream: bool = False) -> list[str]:
        """Build the full claude CLI command for this call.

        Two modes:
          stateless (default, used by MCP server): each call is independent.
            Claude Code maintains conversation context itself.
          stateful (enabled by configure()): uses --continue to resume the
            last conversation. Used by the interactive jsat shell.
        """
        args = [self._binary]

        # Print mode (non-interactive)
        args += ["-p", prompt]

        # Output format
        if stream:
            args += ["--output-format", "stream-json"]
        else:
            args += ["--output-format", "text"]

        # Model selection — only pass --model for known Claude model names.
        # Never pass Ollama/GPT model names (e.g. "llama3.2") to the claude CLI.
        _CLAUDE_MODELS = {
            "claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-8",
            "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        }
        if self._model and self._model in _CLAUDE_MODELS and self._model != "claude-sonnet-4-6":
            args += ["--model", self._model]

        if self._stateful:
            # Stateful mode (interactive shell): maintain conversation history.
            # Use --continue on calls after the first to resume the last session.
            if self._call_count == 0:
                # First call: inject context
                if self._system_prompt:
                    args += ["--system-prompt", self._system_prompt]
                if self._repo_dir:
                    args += ["--add-dir", self._repo_dir]
            else:
                # Continue the last conversation in this directory
                args += ["--continue"]
        else:
            # Stateless mode (MCP server default): each call is independent.
            # Claude Code handles conversation context via its own history.
            # Do NOT use --session-id or --resume — they cause "Invalid session ID".
            if self._system_prompt:
                args += ["--append-system-prompt", self._system_prompt]
            if self._repo_dir:
                args += ["--add-dir", self._repo_dir]

        return args

    def complete(self, prompt: str, max_tokens: int = 8192,
                 temperature: float = 0.1) -> str:
        import structlog
        log = structlog.get_logger(__name__)

        if not shutil.which("claude"):
            raise RuntimeError(
                "'claude' CLI not found. Install Claude Code: https://claude.ai/code"
            )

        args = self._build_args(prompt, stream=False)
        log.debug("claude_cli_complete",
                  session=self._session_id, call=self._call_count,
                  prompt_len=len(prompt))

        t0 = time.monotonic()
        try:
            result = subprocess.run(
                args,
                capture_output=True, text=True, timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as e:
            from jsat._exceptions import AITimeoutError
            raise AITimeoutError(
                f"claude timed out after {self._timeout}s",
                provider="claude_cli", timeout_seconds=self._timeout,
            ) from e

        elapsed = round((time.monotonic() - t0) * 1000)

        if result.returncode != 0:
            stderr = result.stderr.strip()
            log.error("claude_cli_error", returncode=result.returncode,
                      stderr=stderr[:300], elapsed_ms=elapsed)
            raise RuntimeError(
                f"claude exited {result.returncode}: {stderr[:200]}"
            )

        self._call_count += 1
        text = result.stdout.strip()
        log.info("claude_cli_done", response_len=len(text), elapsed_ms=elapsed,
                 session=self._session_id, turn=self._call_count)
        return text

    async def complete_async(self, prompt: str, max_tokens: int = 8192,
                             temperature: float = 0.1) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 8192) -> Iterator[str]:
        """Stream response using --output-format stream-json (NDJSON events)."""
        import structlog
        log = structlog.get_logger(__name__)

        if not shutil.which("claude"):
            raise RuntimeError("'claude' CLI not found.")

        args = self._build_args(prompt, stream=True)
        log.debug("claude_cli_stream_start",
                  session=self._session_id, call=self._call_count)

        t0 = time.monotonic()
        total_chars = 0

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None

            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                # Parse the stream-json NDJSON event
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # Plain text fallback (some claude versions)
                    yield raw_line
                    total_chars += len(raw_line)
                    continue

                event_type = event.get("type", "")

                # Text delta — the actual streamed content
                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield text
                            total_chars += len(text)

                # assistant message block (non-streaming text)
                elif event_type == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                yield text
                                total_chars += len(text)

                # Result event — session ID may be updated here
                elif event_type == "result":
                    sid = event.get("session_id")
                    if sid:
                        self._session_id = sid

            proc.wait(timeout=10)

        except subprocess.TimeoutExpired as e:
            proc.kill()
            from jsat._exceptions import AITimeoutError
            raise AITimeoutError(
                f"claude stream timed out after {self._timeout}s",
                provider="claude_cli", timeout_seconds=self._timeout,
            ) from e
        except Exception as e:
            log.error("claude_cli_stream_error", error=str(e))
            raise

        self._call_count += 1
        elapsed = round((time.monotonic() - t0) * 1000)
        log.info("claude_cli_stream_done",
                 total_chars=total_chars, elapsed_ms=elapsed,
                 session=self._session_id, turn=self._call_count)
