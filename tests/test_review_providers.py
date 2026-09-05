"""Unit tests for review provider construction (`jsat/tools/review.py:_make_provider`).

No LLM calls are made — the point is that every review-model provider string a
user can configure actually maps to a real provider class, including the native
CLI providers (claude_cli / codex_cli / opencode_cli).
"""
from __future__ import annotations

import pytest

from jsat._models import JSATConfig
from jsat.tools.review import _KNOWN_PROVIDERS, _make_provider

_CONFIG = JSATConfig()


@pytest.mark.ci
@pytest.mark.parametrize("provider", ["claude_cli", "codex_cli", "opencode_cli"])
def test_cli_providers_construct(provider):
    prov = _make_provider({"provider": provider, "model": "default"}, _CONFIG)
    assert prov is not None
    assert prov.provider_name == provider


@pytest.mark.ci
def test_unknown_provider_returns_none():
    assert _make_provider({"provider": "not-a-provider", "model": "x"}, _CONFIG) is None


@pytest.mark.ci
def test_known_providers_are_exact_set():
    assert frozenset({
        "claude_cli", "codex_cli", "opencode_cli",
        "anthropic", "openai", "openai_compat", "ollama",
    }) == _KNOWN_PROVIDERS