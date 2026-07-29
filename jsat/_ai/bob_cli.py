"""
jsat._ai.bob_cli — Full Bob Shell CLI integration.

Uses the real 'bob' binary with:
  --resume <session-id>   → multi-turn conversation with full history
  --chat-mode <mode>      → mode selection (plan, code, advanced, ask)
  --prompt                → inject prompt
  --yolo                  → auto-approve all actions
  --output-format stream-json → real streaming

This gives ALL Bob Shell features inside jsat shell:
  ✓ Multi-turn conversation memory
  ✓ File reading / writing (Bob's tools)
  ✓ Bash execution (Bob's execute_command tool)
  ✓ Mode selection (plan, code, advanced, ask)
  ✓ All Bob Shell capabilities
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from collections.abc import Iterator

from jsat._ai import AIProvider


class BobCliProvider(AIProvider):
    """Full-featured Bob Shell CLI provider with session continuity."""

    def __init__(self, cfg=None) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)

        self._binary = shutil.which("bob") or "bob"
        self._model = getattr(getattr(cfg, "ai", None), "model", None) or "premium"
        self._mode = getattr(getattr(cfg, "ai", None), "chat_mode", None) or "advanced"
        self._timeout = getattr(getattr(cfg, "ai", None), "timeout_seconds", None) or 180

        # Session state
        self._session_id: str | None = None
        self._call_count: int = 0
        self._repo_dir: str | None = None
        self._system_prompt: str | None = None
        # stateful=False (default): each call independent — for MCP server
        # stateful=True: uses --resume for multi-turn — for interactive shell
        self._stateful: bool = False

        if not shutil.which("bob"):
            self._log.warning(
                "bob_cli_not_found",
                message="'bob' binary not in PATH — install Bob Shell (npm i -g @ibm/bob-shell)",
            )
        else:
            self._log.info("bob_cli_init", binary=self._binary, model=self._model, mode=self._mode)

    # ── Configuration (called by JSATShell before first message) ─────────────

    def configure(self, repo_dir: str | None = None,
                  system_prompt: str | None = None,
                  stateful: bool = True,
                  chat_mode: str | None = None) -> None:
        """Inject repo context and enable stateful (multi-turn) mode.

        Call this from the interactive shell before the first complete().
        Do NOT call from the MCP server — MCP uses stateless mode by default.
        """
        self._repo_dir = repo_dir
        self._system_prompt = system_prompt
        self._stateful = stateful
        if chat_mode:
            self._mode = chat_mode

    def new_session(self) -> None:
        """Start a fresh conversation (clears history)."""
        self._session_id = None
        self._call_count = 0
        self._log.info("bob_cli_new_session")

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ── AIProvider interface ──────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "bob_cli"

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        return bool(shutil.which("bob"))

    def _build_args(self, prompt: str, stream: bool = False) -> list[str]:
        """Build the full bob CLI command for this call.

        Two modes:
          stateless (default, used by MCP server): each call is independent.
            Bob Shell maintains conversation context itself.
          stateful (enabled by configure()): uses --resume to resume the
            last conversation. Used by the interactive jsat shell.
        """
        args = [self._binary]

        # Chat mode selection
        if self._mode:
            args += ["--chat-mode", self._mode]

        # Output format
        if stream:
            args += ["--output-format", "stream-json"]
        else:
            args += ["--output-format", "text"]

        # Model selection
        if self._model and self._model != "premium":
            args += ["--model", self._model]

        # Auto-approve mode for non-interactive usage
        args += ["--yolo"]

        if self._stateful:
            # Stateful mode (interactive shell): maintain conversation history.
            # Use --resume on calls after the first to resume the last session.
            if self._call_count > 0 and self._session_id:
                args += ["--resume", self._session_id]
        else:
            # Stateless mode (MCP server default): each call is independent.
            # Bob Shell handles conversation context via its own history.
            pass

        # Add the prompt last
        args += ["--prompt", prompt]

        return args

    def complete(self, prompt: str, max_tokens: int = 8192,
                 temperature: float = 0.1) -> str:
        import structlog
        log = structlog.get_logger(__name__)

        if not shutil.which("bob"):
            raise RuntimeError(
                "'bob' CLI not found. Install Bob Shell: npm install -g @ibm/bob-shell"
            )

        args = self._build_args(prompt, stream=False)
        log.debug("bob_cli_complete",
                  session=self._session_id, call=self._call_count,
                  prompt_len=len(prompt))

        t0 = time.monotonic()
        try:
            result = subprocess.run(
                args,
                capture_output=True, text=True, timeout=self._timeout,
                cwd=self._repo_dir,
            )
        except subprocess.TimeoutExpired as e:
            from jsat._exceptions import AITimeoutError
            raise AITimeoutError(
                f"bob timed out after {self._timeout}s",
                provider="bob_cli", timeout_seconds=self._timeout,
            ) from e

        elapsed = round((time.monotonic() - t0) * 1000)

        if result.returncode != 0:
            stderr = result.stderr.strip()
            log.error("bob_cli_error", returncode=result.returncode,
                      stderr=stderr[:300], elapsed_ms=elapsed)
            raise RuntimeError(
                f"bob exited {result.returncode}: {stderr[:200]}"
            )

        self._call_count += 1
        text = result.stdout.strip()
        
        # Try to extract session ID and unwrap result from JSON output.
        # Bob Shell may wrap its response in a JSON envelope.
        if text.startswith("{"):
            try:
                data = json.loads(text)
                sid = data.get("session_id")
                if sid:
                    self._session_id = sid
                result = data.get("result")
                if result:
                    text = str(result)
                # If no "result" key, keep original text — it may be a JSON-formatted answer.
                log.debug("bob_cli_json_response", has_result=bool(result),
                          has_session=bool(sid))
            except json.JSONDecodeError:
                pass  # not JSON, use raw text as-is

        log.info("bob_cli_done", response_len=len(text), elapsed_ms=elapsed,
                 session=self._session_id, turn=self._call_count)
        return text

    async def complete_async(self, prompt: str, max_tokens: int = 8192,
                             temperature: float = 0.1) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 8192) -> Iterator[str]:
        """Stream response using --output-format stream-json (NDJSON events)."""
        import structlog
        log = structlog.get_logger(__name__)

        if not shutil.which("bob"):
            raise RuntimeError("'bob' CLI not found.")

        args = self._build_args(prompt, stream=True)
        log.debug("bob_cli_stream_start",
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
                cwd=self._repo_dir,
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
                    # Plain text fallback
                    yield raw_line
                    total_chars += len(raw_line)
                    continue

                # Generic content extractor — handles Bob Shell's actual stream-json
                # format without assuming Anthropic-style event names.
                # Checks common field names in order of likelihood.
                # TODO: verify exact event schema against real Bob Shell output
                text = (
                    event.get("content")
                    or event.get("result")
                    or event.get("text")
                    or (event.get("delta") or {}).get("text")  # covers Anthropic & Bob delta
                    or ""
                )
                if text:
                    yield str(text)
                    total_chars += len(str(text))

                # Capture session ID if present
                sid = event.get("session_id")
                if sid:
                    self._session_id = sid

            proc.wait(timeout=10)

        except subprocess.TimeoutExpired as e:
            proc.kill()
            from jsat._exceptions import AITimeoutError
            raise AITimeoutError(
                f"bob stream timed out after {self._timeout}s",
                provider="bob_cli", timeout_seconds=self._timeout,
            ) from e
        except Exception as e:
            log.error("bob_cli_stream_error", error=str(e))
            raise

        self._call_count += 1
        elapsed = round((time.monotonic() - t0) * 1000)
        log.info("bob_cli_stream_done",
                 total_chars=total_chars, elapsed_ms=elapsed,
                 session=self._session_id, turn=self._call_count)
