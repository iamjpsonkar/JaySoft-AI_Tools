"""Regression tests for AI-provider error-handling consistency (bug audit fixes).

Covers:
  - Ollama `stream()` wrapping non-404 errors as AIProviderError (previously a bare
    `raise` leaked the raw SDK/httpx exception).
  - Ollama `complete()` wrapping a missing "response" key as AIProviderError
    (previously a raw KeyError escaped outside the try/except).
  - Anthropic/OpenAI client construction wrapping failures as AIAuthError instead
    of leaking the raw SDK exception.
  - Anthropic/OpenAI `complete()` wrapping APIConnectionError/APIStatusError as
    AIProviderError instead of leaking the raw SDK exception.
"""
from __future__ import annotations

import sys
import types

import pytest

from jsat._exceptions import AIAuthError, AIProviderError

# ── Ollama ──────────────────────────────────────────────────────────────────


def _ollama_cfg():
    return types.SimpleNamespace(ai=types.SimpleNamespace(
        model="qwen3:8b",
        base_url="http://localhost:11434",
        max_tokens=100,
        timeout_seconds=30,
    ))


@pytest.mark.ci
def test_ollama_stream_wraps_non_404_error_as_ai_provider_error(monkeypatch):
    from jsat._ai.ollama import OllamaProvider

    monkeypatch.setitem(sys.modules, "ollama", None)
    provider = OllamaProvider(_ollama_cfg())

    class BrokenClient:
        def generate(self, **kwargs):
            raise ConnectionError("host unreachable")

    provider._client = BrokenClient()

    with pytest.raises(AIProviderError):
        list(provider.stream("hello"))


@pytest.mark.ci
def test_ollama_complete_missing_response_key_raises_ai_provider_error(monkeypatch):
    """A malformed/version-skewed Ollama response must not leak a raw KeyError."""
    from jsat._ai.ollama import OllamaProvider

    monkeypatch.setitem(sys.modules, "ollama", None)
    provider = OllamaProvider(_ollama_cfg())

    class MalformedClient:
        def generate(self, **kwargs):
            return {"unexpected": "shape"}  # no "response" key

    provider._client = MalformedClient()

    with pytest.raises(AIProviderError):
        provider.complete("hello")


# ── Anthropic (SDK mocked — not an installed dependency in this env) ────────


def _install_fake_anthropic_sdk(monkeypatch):
    mod = types.ModuleType("anthropic")

    class AnthropicError(Exception):
        pass

    class RateLimitError(AnthropicError):
        pass

    class AuthenticationError(AnthropicError):
        pass

    class APITimeoutError(AnthropicError):
        pass

    class APIConnectionError(AnthropicError):
        pass

    class APIStatusError(AnthropicError):
        def __init__(self, message="status error", status_code=500):
            super().__init__(message)
            self.status_code = status_code

    class Anthropic:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.messages = types.SimpleNamespace(create=lambda **kw: None)
            self.models = types.SimpleNamespace(list=lambda: None)

    mod.Anthropic = Anthropic
    mod.RateLimitError = RateLimitError
    mod.AuthenticationError = AuthenticationError
    mod.APITimeoutError = APITimeoutError
    mod.APIConnectionError = APIConnectionError
    mod.APIStatusError = APIStatusError
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return mod


def _ai_cfg(model="claude-x"):
    return types.SimpleNamespace(ai=types.SimpleNamespace(model=model, api_key_env=None))


@pytest.mark.ci
def test_anthropic_client_construction_failure_raises_ai_auth_error(monkeypatch):
    mod = _install_fake_anthropic_sdk(monkeypatch)

    def broken_init(self, api_key=None):
        raise RuntimeError("invalid api key format")

    monkeypatch.setattr(mod.Anthropic, "__init__", broken_init)

    from jsat._ai.anthropic import AnthropicProvider

    with pytest.raises(AIAuthError):
        AnthropicProvider(_ai_cfg())


@pytest.mark.ci
def test_anthropic_complete_wraps_connection_error(monkeypatch):
    mod = _install_fake_anthropic_sdk(monkeypatch)
    from jsat._ai.anthropic import AnthropicProvider

    provider = AnthropicProvider(_ai_cfg())

    def raise_connection_error(**kwargs):
        raise mod.APIConnectionError("network outage")

    provider._client.messages.create = raise_connection_error

    with pytest.raises(AIProviderError):
        provider.complete("hello")


@pytest.mark.ci
def test_anthropic_complete_wraps_status_error(monkeypatch):
    mod = _install_fake_anthropic_sdk(monkeypatch)
    from jsat._ai.anthropic import AnthropicProvider

    provider = AnthropicProvider(_ai_cfg())

    def raise_status_error(**kwargs):
        raise mod.APIStatusError("server error", status_code=503)

    provider._client.messages.create = raise_status_error

    with pytest.raises(AIProviderError):
        provider.complete("hello")


# ── OpenAI (SDK mocked — not an installed dependency in this env) ───────────


def _install_fake_openai_sdk(monkeypatch):
    mod = types.ModuleType("openai")

    class OpenAIError(Exception):
        pass

    class RateLimitError(OpenAIError):
        pass

    class AuthenticationError(OpenAIError):
        pass

    class APITimeoutError(OpenAIError):
        pass

    class APIConnectionError(OpenAIError):
        pass

    class APIStatusError(OpenAIError):
        def __init__(self, message="status error", status_code=500):
            super().__init__(message)
            self.status_code = status_code

    class OpenAI:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **kw: None)
            )
            self.models = types.SimpleNamespace(list=lambda: None)

    mod.OpenAI = OpenAI
    mod.RateLimitError = RateLimitError
    mod.AuthenticationError = AuthenticationError
    mod.APITimeoutError = APITimeoutError
    mod.APIConnectionError = APIConnectionError
    mod.APIStatusError = APIStatusError
    monkeypatch.setitem(sys.modules, "openai", mod)
    return mod


@pytest.mark.ci
def test_openai_client_construction_failure_raises_ai_auth_error(monkeypatch):
    mod = _install_fake_openai_sdk(monkeypatch)

    def broken_init(self, api_key=None):
        raise RuntimeError("invalid api key format")

    monkeypatch.setattr(mod.OpenAI, "__init__", broken_init)

    from jsat._ai.openai import OpenAIProvider

    with pytest.raises(AIAuthError):
        OpenAIProvider(_ai_cfg())


@pytest.mark.ci
def test_openai_complete_wraps_connection_error(monkeypatch):
    mod = _install_fake_openai_sdk(monkeypatch)
    from jsat._ai.openai import OpenAIProvider

    provider = OpenAIProvider(_ai_cfg())

    def raise_connection_error(**kwargs):
        raise mod.APIConnectionError("network outage")

    provider._client.chat.completions.create = raise_connection_error

    with pytest.raises(AIProviderError):
        provider.complete("hello")


@pytest.mark.ci
def test_openai_complete_wraps_status_error(monkeypatch):
    mod = _install_fake_openai_sdk(monkeypatch)
    from jsat._ai.openai import OpenAIProvider

    provider = OpenAIProvider(_ai_cfg())

    def raise_status_error(**kwargs):
        raise mod.APIStatusError("server error", status_code=503)

    provider._client.chat.completions.create = raise_status_error

    with pytest.raises(AIProviderError):
        provider.complete("hello")
