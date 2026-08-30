"""Shared Ollama model and launcher helpers.

This module stays dependency-light so CLI discovery and ``jsat --help`` remain fast.
"""
from __future__ import annotations

from typing import Literal

DEFAULT_BASE_URL = "http://localhost:11434"

OllamaModelKind = Literal["local", "cloud"]


def model_selection_help(available: list[str] | None = None) -> str:
    """Return provider-neutral commands for discovering and selecting a model."""
    lines = [
        "List models: ollama list",
        "JSAT view:   jsat ai models ollama",
    ]
    if available:
        lines.append("Available:   " + ", ".join(available[:10]))
    lines += [
        "Select one:  jsat ai use ollama --model <model>",
        "Local model: ollama pull <model>",
        "Cloud model: ollama signin, then select its cloud model name",
    ]
    return "\n".join(lines)


def select_ollama_model(requested: str | None, available: list[str]) -> str:
    """Use an explicit model or the sole discoverable model; otherwise ask."""
    if requested and requested.strip():
        return requested.strip()
    if len(available) == 1:
        return available[0]
    reason = "No Ollama model is available." if not available else (
        "More than one Ollama model is available; select one explicitly."
    )
    raise ValueError(f"{reason}\n{model_selection_help(available)}")


def discover_ollama_models(base_url: str = DEFAULT_BASE_URL) -> list[str]:
    """Return model names registered by an Ollama host."""
    import httpx

    response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=1.0)
    response.raise_for_status()
    return [m["name"] for m in response.json().get("models", []) if m.get("name")]


def ollama_model_kind(model: str) -> OllamaModelKind:
    """Classify an Ollama model reference without contacting the server."""
    normalized = model.strip().lower()
    return "cloud" if normalized.endswith((":cloud", "-cloud")) else "local"


def ollama_models_match(installed: str, requested: str) -> bool:
    """Match exact model refs, treating an omitted tag as ``:latest`` only."""
    installed = installed.strip()
    requested = requested.strip()
    if installed == requested:
        return True
    if ":" not in requested:
        return installed == f"{requested}:latest"
    if ":" not in installed:
        return requested == f"{installed}:latest"
    return False


def build_ollama_launch_args(
    tool: str,
    *,
    model: str | None = None,
    configure_only: bool = False,
    yes: bool = False,
    passthrough: list[str] | None = None,
) -> list[str]:
    """Build arguments following Ollama's ``launch`` CLI contract."""
    tool = tool.strip()
    if not tool:
        raise ValueError("an Ollama integration name is required")
    if yes and not model:
        raise ValueError("--yes requires --model so Ollama can skip the selector")

    args = ["launch", tool]
    if model:
        args += ["--model", model]
    if configure_only:
        args.append("--config")
    if yes:
        args.append("--yes")
    if passthrough:
        args += ["--", *passthrough]
    return args
