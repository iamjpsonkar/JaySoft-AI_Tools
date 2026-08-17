"""jsat._ai.aliases — single source of truth for AI provider aliases.

Both the SDK (``JSAT.switch_ai``), the shell (``switch <provider>``) and the CLI
(``jsat ai use <provider>``) resolve provider names through this module, so a name
documented in one surface always works in the others.
"""
from __future__ import annotations

# Tools that `jsat connect` wires in as MCP clients — NOT AI providers.
MCP_TOOLS = ("claude", "codex", "cursor", "windsurf", "continue", "zed", "gemini", "bob")


def normalize_alias(name: str) -> str:
    """Canonicalize a provider name: case, surrounding space, and ``_`` vs ``-``.

    ``claude_cli``, ``Claude-CLI`` and ``claude cli`` all resolve to ``claude-cli``.
    """
    return name.strip().lower().replace("_", "-").replace(" ", "-")


def provider_aliases(base_url: str | None = None) -> dict[str, tuple[str, str, str | None]]:
    """alias → (internal_provider, default_model, base_url).

    ``claude`` prefers the CLI when the ``claude`` binary is installed (no API key
    needed) and falls back to the Anthropic API otherwise — so this is resolved at
    call time rather than import time.
    """
    import shutil

    claude_cli_available = bool(shutil.which("claude"))
    gemini_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    lmstudio_url = "http://localhost:1234/v1"

    return {
        "claude":     ("claude_cli" if claude_cli_available else "anthropic",
                       "claude-sonnet-4-6", None),
        "claude-api": ("anthropic",     "claude-sonnet-4-6",         None),
        "claude-cli": ("claude_cli",    "claude-sonnet-4-6",         None),
        "anthropic":  ("anthropic",     "claude-sonnet-4-6",         None),
        "haiku":      ("anthropic",     "claude-haiku-4-5-20251001", None),
        "opus":       ("anthropic",     "claude-opus-4-8",           None),
        "bob":        ("bob_cli",       "premium",                   None),
        "bob-cli":    ("bob_cli",       "premium",                   None),
        "codex-cli":  ("codex_cli",     "gpt-5.6-sol",               None),
        "gpt":        ("openai",        "gpt-4o",                    None),
        "openai":     ("openai",        "gpt-4o",                    None),
        "chatgpt":    ("openai",        "gpt-4o",                    None),
        "gpt4":       ("openai",        "gpt-4o",                    None),
        "gpt4mini":   ("openai",        "gpt-4o-mini",               None),
        "codex":      ("openai",        "gpt-4o",                    None),
        "ollama":     ("ollama",        "llama3.2",                  None),
        "llama":      ("ollama",        "llama3.2",                  None),
        "phi":        ("ollama",        "phi3:mini",                 None),
        "gemini":     ("openai_compat", "gemini-1.5-flash",          gemini_url),
        "gemini-pro": ("openai_compat", "gemini-1.5-pro",            gemini_url),
        "lmstudio":   ("openai_compat", "local-model",               lmstudio_url),
        "lm-studio":  ("openai_compat", "local-model",               lmstudio_url),
        "custom":     ("openai_compat", "local-model",  base_url or lmstudio_url),
        "compat":     ("openai_compat", "local-model",  base_url or lmstudio_url),
    }


def alias_names() -> list[str]:
    """Every accepted provider alias, sorted."""
    return sorted(provider_aliases())


def is_provider_alias(name: str) -> bool:
    """True if ``name`` names an AI provider (rather than an MCP tool)."""
    return normalize_alias(name) in provider_aliases()


def resolve_alias(
    name: str, base_url: str | None = None
) -> tuple[str, str, str | None] | None:
    """Resolve a provider alias to (internal_provider, default_model, base_url).

    Returns ``None`` when the alias is unknown — callers decide how to report it.
    """
    return provider_aliases(base_url).get(normalize_alias(name))


def suggest(name: str, candidates: tuple[str, ...] | list[str], n: int = 1) -> list[str]:
    """Closest matches for a mistyped name (``claud`` → ``claude``)."""
    import difflib

    return difflib.get_close_matches(normalize_alias(name), list(candidates), n=n, cutoff=0.6)
