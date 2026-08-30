"""jsat._ai.aliases — single source of truth for AI provider aliases.

Both the SDK (``JSAT.switch_ai``), the shell (``switch <provider>``) and the CLI
(``jsat ai use <provider>``) resolve provider names through this module, so a name
documented in one surface always works in the others.
"""
from __future__ import annotations

# Tools that `jsat connect` wires in as MCP clients — NOT AI providers.
MCP_TOOLS = (
    "claude", "codex", "opencode", "ollama", "cursor", "windsurf", "continue", "zed",
    "gemini", "bob",
)


def normalize_alias(name: str) -> str:
    """Canonicalize a provider name: case, surrounding space, and ``_`` vs ``-``.

    ``claude_cli``, ``Claude-CLI`` and ``claude cli`` all resolve to ``claude-cli``.
    """
    return name.strip().lower().replace("_", "-").replace(" ", "-")


def provider_aliases(
    base_url: str | None = None,
) -> dict[str, tuple[str, str | None, str | None]]:
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
        "claude":     ("claude_cli" if claude_cli_available else "anthropic", None, None),
        "claude-api": ("anthropic",     None,                          None),
        "claude-cli": ("claude_cli",    None,                          None),
        "anthropic":  ("anthropic",     None,                          None),
        "haiku":      ("anthropic",     None,                          None),
        "opus":       ("anthropic",     None,                          None),
        "bob":        ("bob_cli",       None,                          None),
        "bob-cli":    ("bob_cli",       None,                          None),
        "codex-cli":  ("codex_cli",     None,                          None),
        "opencode":   ("opencode_cli",  None,                          None),
        "opencode-cli": ("opencode_cli", None,                         None),
        "gpt":        ("openai",        None,                          None),
        "openai":     ("openai",        None,                          None),
        "chatgpt":    ("openai",        None,                          None),
        "gpt4":       ("openai",        None,                          None),
        "gpt4mini":   ("openai",        None,                          None),
        "codex":      ("codex_cli",     None,                          None),
        "ollama":     ("ollama",        None,                          None),
        "llama":      ("ollama",        None,                          None),
        "phi":        ("ollama",        None,                          None),
        "gemini":     ("openai_compat", None,                          gemini_url),
        "gemini-pro": ("openai_compat", None,                          gemini_url),
        "lmstudio":   ("openai_compat", None,                          lmstudio_url),
        "lm-studio":  ("openai_compat", None,                          lmstudio_url),
        "custom":     ("openai_compat", None,             base_url or lmstudio_url),
        "compat":     ("openai_compat", None,             base_url or lmstudio_url),
    }


def alias_names() -> list[str]:
    """Every accepted provider alias, sorted."""
    return sorted(provider_aliases())


def is_provider_alias(name: str) -> bool:
    """True if ``name`` names an AI provider (rather than an MCP tool)."""
    return normalize_alias(name) in provider_aliases()


def resolve_alias(
    name: str, base_url: str | None = None
) -> tuple[str, str | None, str | None] | None:
    """Resolve a provider alias to (internal_provider, default_model, base_url).

    Returns ``None`` when the alias is unknown — callers decide how to report it.
    """
    return provider_aliases(base_url).get(normalize_alias(name))


def suggest(name: str, candidates: tuple[str, ...] | list[str], n: int = 1) -> list[str]:
    """Closest matches for a mistyped name (``claud`` → ``claude``)."""
    import difflib

    return difflib.get_close_matches(normalize_alias(name), list(candidates), n=n, cutoff=0.6)
