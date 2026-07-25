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

from jsat._core import JSAT
from jsat._config import load_config
from jsat._exceptions import (
    JSATError, ConfigError, ConfigFileNotFound, ConfigSchemaError,
    MissingRequiredConfig, IndexError, IndexNotFound, IndexCorrupted,
    IndexOutOfDate, UnsupportedLanguage, AIError, AIProviderError,
    AIRateLimitError, AITimeoutError, AIContextLengthError, AIAuthError,
    GraphError, GraphConnectionError, GraphQueryError, GraphCapacityError,
    ProfileError, ExportError, ExportPermissionError, ImportVersionMismatch,
    ImportCorrupted, SkillError, SkillNotFound, SkillManifestError,
    SkillExecutionError,
)

__version__ = "0.1.0"
__author__ = "Jay Prakash Sonkar"
__email__ = "iamjpsonkar@gmail.com"
__license__ = "MIT"

__all__ = [
    "JSAT",
    "load_config",
    "JSATError",
    "__version__",
    "__author__",
    "__email__",
]
