"""OpenCode CLI AI provider for JSAT MCP tools running in native OpenCode."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

from jsat._ai import AIProvider


def _find_opencode() -> str | None:
    """Find OpenCode on PATH or in the location used by its installer."""
    found = shutil.which("opencode")
    if found:
        return found
    fallback = Path.home() / ".opencode" / "bin" / "opencode"
    return str(fallback) if fallback.is_file() else None


class OpenCodeCliProvider(AIProvider):
    """Stateless provider backed by ``opencode run``."""

    def __init__(self, cfg=None) -> None:
        self._binary = _find_opencode() or "opencode"
        self._model = getattr(getattr(cfg, "ai", None), "model", None)
        self._timeout = getattr(getattr(cfg, "ai", None), "timeout_seconds", None) or 180
        self._repo_dir: str | None = None

    def configure(
        self,
        repo_dir: str | None = None,
        system_prompt: str | None = None,
        stateful: bool = False,
    ) -> None:
        self._repo_dir = repo_dir

    @property
    def provider_name(self) -> str:
        return "opencode_cli"

    @property
    def model_name(self) -> str:
        return self._model or "opencode default"

    def is_available(self) -> bool:
        return _find_opencode() is not None

    def _build_args(self, prompt: str) -> list[str]:
        args = [self._binary, "run", prompt]
        if self._model and self._model != "default":
            args += ["--model", self._model]
        return args

    def _subprocess_env(self) -> dict[str, str]:
        """Disable JSAT in the nested run so the provider cannot invoke itself."""
        env = dict(os.environ)
        content: dict = {}
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            content = json.loads(env.get("OPENCODE_CONFIG_CONTENT", "{}"))
        content.setdefault("mcp", {})["jsat"] = {"enabled": False}
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(content)
        return env

    def complete(
        self, prompt: str, max_tokens: int = 8192, temperature: float = 0.1
    ) -> str:
        if not self.is_available():
            raise RuntimeError("`opencode` CLI not found. Run: ollama launch opencode")
        try:
            result = subprocess.run(
                self._build_args(prompt),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=self._repo_dir,
                env=self._subprocess_env(),
            )
        except subprocess.TimeoutExpired as exc:
            from jsat._exceptions import AITimeoutError

            raise AITimeoutError(
                f"opencode timed out after {self._timeout}s",
                provider="opencode_cli",
                timeout_seconds=self._timeout,
            ) from exc
        if result.returncode != 0:
            from jsat._ai import model_help

            raise RuntimeError(
                f"opencode exited {result.returncode}: {result.stderr.strip()[:200]}\n"
                f"{model_help('opencode_cli')}"
            )
        return result.stdout.strip()

    async def complete_async(
        self, prompt: str, max_tokens: int = 8192, temperature: float = 0.1
    ) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 8192) -> Iterator[str]:
        yield self.complete(prompt, max_tokens=max_tokens)
