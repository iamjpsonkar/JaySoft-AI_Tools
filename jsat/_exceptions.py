"""
jsat._exceptions
~~~~~~~~~~~~~~~~
All JSAT exception classes. Zero external dependencies — stdlib only.
Every exception stores structured context via **kwargs as self.context dict.
"""
from __future__ import annotations

__all__ = [
    "JSATError", "ConfigError", "ConfigFileNotFound", "ConfigSchemaError",
    "MissingRequiredConfig", "IndexError", "IndexNotFound", "IndexCorrupted",
    "IndexOutOfDate", "UnsupportedLanguage", "AIError", "AIProviderError",
    "AIRateLimitError", "AITimeoutError", "AIContextLengthError", "AIAuthError",
    "GraphError", "GraphConnectionError", "GraphQueryError", "GraphCapacityError",
    "ProfileError", "ExportError", "ExportPermissionError", "ImportVersionMismatch",
    "ImportCorrupted", "SkillError", "SkillNotFound", "SkillManifestError",
    "SkillExecutionError",
]


class JSATError(Exception):
    """Root exception for all JSAT errors."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message)
        self.message: str = message
        self.context: dict[str, object] = context

    def __repr__(self) -> str:
        ctx = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
        return f"{type(self).__name__}({self.message!r}{', ' + ctx if ctx else ''})"


# ── Config ────────────────────────────────────────────────────────────────────

class ConfigError(JSATError):
    """Raised for any configuration-related problem."""


class ConfigFileNotFound(ConfigError):
    def __init__(self, message: str = "", *, path: object, **ctx: object) -> None:
        if not message:
            message = f"Config file not found: {path}"
        super().__init__(message, path=path, **ctx)
        self.path = path


class ConfigSchemaError(ConfigError):
    def __init__(self, message: str, *, field: str, expected: str, got: object, **ctx: object) -> None:
        super().__init__(message, field=field, expected=expected, got=got, **ctx)
        self.field = field
        self.expected = expected
        self.got = got


class MissingRequiredConfig(ConfigError):
    def __init__(self, message: str = "", *, key: str, **ctx: object) -> None:
        if not message:
            message = f"Required config key missing: {key}"
        super().__init__(message, key=key, **ctx)
        self.key = key


# ── Index ─────────────────────────────────────────────────────────────────────

class IndexError(JSATError):
    """Raised for problems with the JSAT codebase index."""


class IndexNotFound(IndexError):
    def __init__(self, message: str = "", *, repo_path: object, **ctx: object) -> None:
        if not message:
            message = f"No JSAT index found for '{repo_path}'. Run: jsat index ."
        super().__init__(message, repo_path=repo_path, **ctx)
        self.repo_path = repo_path


class IndexCorrupted(IndexError):
    def __init__(self, message: str, *, path: object, detail: str, **ctx: object) -> None:
        super().__init__(message, path=path, detail=detail, **ctx)
        self.path = path
        self.detail = detail


class IndexOutOfDate(IndexError):
    def __init__(self, message: str = "", *, current_commit: str, index_commit: str, **ctx: object) -> None:
        if not message:
            message = (
                f"Index is stale (indexed at {index_commit[:8]}, HEAD is {current_commit[:8]}). "
                "Run: jsat index . --incremental"
            )
        super().__init__(message, current_commit=current_commit, index_commit=index_commit, **ctx)
        self.current_commit = current_commit
        self.index_commit = index_commit


class UnsupportedLanguage(IndexError):
    def __init__(self, message: str = "", *, language: str, file: object, **ctx: object) -> None:
        if not message:
            message = f"Unsupported language '{language}' in file: {file}"
        super().__init__(message, language=language, file=file, **ctx)
        self.language = language
        self.file = file


# ── AI ────────────────────────────────────────────────────────────────────────

class AIError(JSATError):
    """Base class for errors from AI provider interactions."""


class AIProviderError(AIError):
    def __init__(self, message: str, *, provider: str, status_code: int, **ctx: object) -> None:
        super().__init__(message, provider=provider, status_code=status_code, **ctx)
        self.provider = provider
        self.status_code = status_code


class AIRateLimitError(AIError):
    def __init__(self, message: str = "", *, provider: str, retry_after: int | None = None, **ctx: object) -> None:
        if not message:
            message = f"Rate limited by {provider}. Retry after {retry_after}s."
        super().__init__(message, provider=provider, retry_after=retry_after, **ctx)
        self.provider = provider
        self.retry_after = retry_after


class AITimeoutError(AIError):
    def __init__(self, message: str = "", *, provider: str, timeout_seconds: float, **ctx: object) -> None:
        if not message:
            message = f"{provider} request timed out after {timeout_seconds}s."
        super().__init__(message, provider=provider, timeout_seconds=timeout_seconds, **ctx)
        self.provider = provider
        self.timeout_seconds = timeout_seconds


class AIContextLengthError(AIError):
    def __init__(self, message: str = "", *, model: str, tokens_used: int, max_tokens: int, **ctx: object) -> None:
        if not message:
            message = f"{model}: {tokens_used} tokens exceeds {max_tokens} limit."
        super().__init__(message, model=model, tokens_used=tokens_used, max_tokens=max_tokens, **ctx)
        self.model = model
        self.tokens_used = tokens_used
        self.max_tokens = max_tokens


class AIAuthError(AIError):
    def __init__(self, message: str = "", *, provider: str, **ctx: object) -> None:
        if not message:
            message = f"Authentication failed for '{provider}'. Check API key."
        super().__init__(message, provider=provider, **ctx)
        self.provider = provider


# ── Graph ─────────────────────────────────────────────────────────────────────

class GraphError(JSATError):
    """Base class for graph storage errors."""


class GraphConnectionError(GraphError):
    def __init__(self, message: str, *, uri: str, detail: str, **ctx: object) -> None:
        super().__init__(message, uri=uri, detail=detail, **ctx)
        self.uri = uri
        self.detail = detail


class GraphQueryError(GraphError):
    def __init__(self, message: str, *, query: str, detail: str, **ctx: object) -> None:
        super().__init__(message, query=query, detail=detail, **ctx)
        self.query = query
        self.detail = detail


class GraphCapacityError(GraphError):
    def __init__(self, message: str, *, current_nodes: int, max_nodes: int, **ctx: object) -> None:
        super().__init__(message, current_nodes=current_nodes, max_nodes=max_nodes, **ctx)
        self.current_nodes = current_nodes
        self.max_nodes = max_nodes


# ── Profile (optional dep gating) ────────────────────────────────────────────

class ProfileError(JSATError):
    """Raised when a feature requires an optional dependency not installed."""

    def __init__(self, message: str = "", *, required_extra: str, **ctx: object) -> None:
        if not message:
            message = (
                f"This feature requires the '{required_extra}' extra.\n"
                f"Install: pip install 'jsat[{required_extra}]'"
            )
        super().__init__(message, required_extra=required_extra, **ctx)
        self.required_extra = required_extra


# ── Export / Import ───────────────────────────────────────────────────────────

class ExportError(JSATError):
    """Base class for export/import errors."""


class ExportPermissionError(ExportError):
    def __init__(self, message: str, *, path: object, **ctx: object) -> None:
        super().__init__(message, path=path, **ctx)
        self.path = path


class ImportVersionMismatch(ExportError):
    def __init__(self, message: str = "", *, export_version: str, current_version: str, **ctx: object) -> None:
        if not message:
            message = (
                f"Archive from JSAT {export_version}, installed is {current_version}. "
                "Use: jsat import --migrate"
            )
        super().__init__(message, export_version=export_version, current_version=current_version, **ctx)
        self.export_version = export_version
        self.current_version = current_version


class ImportCorrupted(ExportError):
    def __init__(self, message: str, *, path: object, detail: str, **ctx: object) -> None:
        super().__init__(message, path=path, detail=detail, **ctx)
        self.path = path
        self.detail = detail


# ── Skills ────────────────────────────────────────────────────────────────────

class SkillError(JSATError):
    """Base class for skill subsystem errors."""


class SkillNotFound(SkillError):
    def __init__(self, message: str = "", *, name: str, **ctx: object) -> None:
        if not message:
            message = f"No skill registered with name '{name}'."
        super().__init__(message, name=name, **ctx)
        self.name = name


class SkillManifestError(SkillError):
    def __init__(self, message: str, *, path: object, detail: str, **ctx: object) -> None:
        super().__init__(message, path=path, detail=detail, **ctx)
        self.path = path
        self.detail = detail


class SkillExecutionError(SkillError):
    def __init__(self, message: str, *, name: str, detail: str, **ctx: object) -> None:
        super().__init__(message, name=name, detail=detail, **ctx)
        self.name = name
        self.detail = detail
