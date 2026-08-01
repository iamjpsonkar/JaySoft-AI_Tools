"""
JSAT — JaySoft AI Tools
Codebase intelligence shell and SDK. Lightweight by default.

  pip install jsat           # core only (~80MB)
  pip install jsat[local]    # + Ollama
  pip install jsat[standard] # + analysis tools
  pip install jsat[team]     # + Neo4j, Qdrant, Redis
  pip install jsat[all]      # everything
"""
from __future__ import annotations

from jsat._config import load_config
from jsat._core import JSAT
from jsat._exceptions import (
    AIAuthError,
    AIContextLengthError,
    AIError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
    ConfigError,
    ConfigFileNotFound,
    ConfigSchemaError,
    ExportError,
    ExportPermissionError,
    GraphCapacityError,
    GraphConnectionError,
    GraphError,
    GraphQueryError,
    ImportCorrupted,
    ImportVersionMismatch,
    IndexCorrupted,
    IndexError,
    IndexNotFound,
    IndexOutOfDate,
    JSATError,
    MissingRequiredConfig,
    ProfileError,
    SkillError,
    SkillExecutionError,
    SkillManifestError,
    SkillNotFound,
    UnsupportedLanguage,
)

__version__ = "0.4.7"
__author__ = "Jay Prakash Sonkar"
__email__ = "iamjpsonkar@gmail.com"
__license__ = "MIT"

__all__ = [
    "JSAT",
    "load_config",
    "JSATError",
    "AIAuthError",
    "AIContextLengthError",
    "AIError",
    "AIProviderError",
    "AIRateLimitError",
    "AITimeoutError",
    "ConfigError",
    "ConfigFileNotFound",
    "ConfigSchemaError",
    "ExportError",
    "ExportPermissionError",
    "GraphCapacityError",
    "GraphConnectionError",
    "GraphError",
    "GraphQueryError",
    "ImportCorrupted",
    "ImportVersionMismatch",
    "IndexCorrupted",
    "IndexError",
    "IndexNotFound",
    "IndexOutOfDate",
    "MissingRequiredConfig",
    "ProfileError",
    "SkillError",
    "SkillExecutionError",
    "SkillManifestError",
    "SkillNotFound",
    "UnsupportedLanguage",
    "__version__",
    "__author__",
    "__email__",
]
