"""Resolve the AI backend owned by the process that launched JSAT MCP."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LaunchAIContext:
    """An explicit provider/model selection inherited from the host AI tool."""

    provider: str
    model: str | None = None
    base_url: str | None = None
    source: str = ""


def detect_launch_ai_context(environ: Mapping[str, str]) -> LaunchAIContext | None:
    """Detect an Ollama-managed OpenCode or Claude launch from inherited env vars."""
    opencode_content = environ.get("OPENCODE_CONFIG_CONTENT", "").strip()
    if opencode_content:
        try:
            content = json.loads(opencode_content)
            selected = content.get("model", "")
            if isinstance(selected, str) and selected.startswith("ollama/"):
                model = selected.removeprefix("ollama/")
                provider = content.get("provider", {}).get("ollama", {})
                base_url = provider.get("options", {}).get("baseURL")
                base_url = base_url.removesuffix("/v1") if isinstance(base_url, str) else None
                if model:
                    return LaunchAIContext("ollama", model, base_url, "ollama-opencode")
        except (AttributeError, json.JSONDecodeError, TypeError):
            pass

    base_url = environ.get("ANTHROPIC_BASE_URL", "").strip()
    auth_token = environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    if base_url and auth_token == "ollama":
        # `ollama launch claude` documents only ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN,
        # and ANTHROPIC_API_KEY — no model-carrying env var. ANTHROPIC_DEFAULT_SONNET_MODEL
        # is read as a best-effort extra signal (harmless if unset), but detection must not
        # depend on it, or an Ollama-launched Claude session is never recognized at all.
        model = environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "").strip() or None
        return LaunchAIContext("ollama", model, base_url, "ollama-claude")

    return None


def explicit_provider_context(environ: Mapping[str, str]) -> LaunchAIContext | None:
    """Resolve only values explicitly pinned by a JSAT MCP connector.

    Native clients own their default model. Leaving the model unset is intentional:
    forwarding a model inherited from another provider is invalid and was the cause
    of Codex receiving Ollama model names.
    """
    provider = environ.get("JSAT_AI_PROVIDER", "").strip()
    if not provider or provider == "none":
        return None
    model = environ.get("JSAT_AI_MODEL", "").strip() or None
    return LaunchAIContext(provider, model, source="jsat-connector")


def resolve_process_ai_context(environ: Mapping[str, str]) -> LaunchAIContext | None:
    """Choose launch-owned routing before the connector's native-tool fallback."""
    return detect_launch_ai_context(environ) or explicit_provider_context(environ)


def apply_launch_ai_context(ai_config: Any, context: LaunchAIContext) -> Any:
    """Replace all provider-owned fields with the launcher's authoritative values."""
    updates: dict[str, Any] = {
        "provider": context.provider,
        "model": context.model,
        "base_url": context.base_url,
        "api_key_env": None,
    }
    return ai_config.model_copy(update=updates)
