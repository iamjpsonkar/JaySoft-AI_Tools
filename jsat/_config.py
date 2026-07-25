"""
jsat._config — Config loader, system detector, auto-configurator.

Core deps only: pydantic, pyyaml, psutil, httpx. structlog imported lazily.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import sys
from pathlib import Path
from typing import Any

import httpx
import psutil
import yaml

from jsat._models import (
    AIConfig, CacheConfig, EmbeddingsConfig, GraphConfig, IThinkingConfig,
    IndexerConfig, JSATConfig, LogConfig, SystemProfile, VectorStoreConfig,
)

_PROFILE_CACHE_NAME = Path(".jsat/system-profile.json")  # relative; resolved per-repo at runtime

_PRESETS: dict[str, dict[str, Any]] = {
    "solo": {
        "graph": {"backend": "sqlite"},
        "embeddings": {"provider": "local", "model": "nomic-embed-code",
                       "vector_store": {"backend": "sqlite-vss"}},
        "ai": {"provider": "ollama", "model": "llama3.2"},
        "cache": {"backend": "memory"},
        "ithinking": {"mode": "interactive", "gate_level": "medium"},
    },
    "team": {
        "graph": {"backend": "neo4j"},
        "embeddings": {"provider": "openai", "model": "text-embedding-3-small",
                       "vector_store": {"backend": "qdrant"}},
        "ai": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        "cache": {"backend": "redis"},
        "ithinking": {"mode": "interactive", "gate_level": "high"},
    },
    "ci": {
        "graph": {"backend": "sqlite"},
        "embeddings": {"provider": "none"},
        "ai": {"provider": "none"},
        "cache": {"backend": "memory"},
        "ithinking": {"enabled": False, "mode": "silent"},
        "log": {"level": "WARNING", "format": "json"},
    },
    "raspberry-pi": {
        "graph": {"backend": "sqlite"},
        "embeddings": {"provider": "local", "model": "nomic-embed-code",
                       "dimensions": 384, "batch_size": 8,
                       "vector_store": {"backend": "sqlite-vss"}},
        "ai": {"provider": "ollama", "model": "phi3:mini"},
        "cache": {"backend": "disk"},
        "indexer": {"embedding_batch_size": 8, "max_file_size_kb": 100},
        "ithinking": {"mode": "silent", "gate_level": "low"},
    },
}


# ── 1. load_config ────────────────────────────────────────────────────────────

def load_config(config_path: str | Path | None = None,
                repo: Path | None = None) -> JSATConfig:
    """Load config. Search order (first found wins):
    1. explicit config_path argument
    2. $JSAT_CONFIG env var
    3. {repo}/.jsat/config.yaml   ← canonical location (everything under .jsat/)
    4. {repo}/.jsat.yaml          ← legacy fallback
    5. ./.jsat/config.yaml        ← CWD canonical
    6. ./.jsat.yaml               ← CWD legacy
    7. ~/.config/jsat/config.yaml
    8. /etc/jsat/config.yaml
    """
    import structlog
    log = structlog.get_logger(__name__)

    candidates = []
    if config_path:
        candidates.append(Path(config_path))
    env = os.environ.get("JSAT_CONFIG")
    if env:
        candidates.append(Path(env))

    root = repo or Path.cwd()
    candidates += [
        root / ".jsat" / "config.yaml",     # canonical: everything inside .jsat/
        root / ".jsat.yaml",                 # legacy: project root
        Path(".jsat") / "config.yaml",       # CWD canonical
        Path(".jsat.yaml"),                  # CWD legacy
        Path.home() / ".config" / "jsat" / "config.yaml",
        Path("/etc/jsat/config.yaml"),
    ]

    raw: dict[str, Any] = {}
    for p in candidates:
        if p.exists() and p.is_file():
            with p.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            log.info("config_loaded", path=str(p))
            break
    else:
        log.warning("config_not_found", searched=[str(c) for c in candidates])

    cfg = JSATConfig.model_validate(raw)

    # CI overrides
    if os.environ.get("CI", "").lower() in ("true", "1", "yes"):
        cfg = cfg.model_copy(update={
            "embeddings": cfg.embeddings.model_copy(update={"provider": "none"}),
            "cache": cfg.cache.model_copy(update={"backend": "memory"}),
            "ithinking": cfg.ithinking.model_copy(update={"mode": "silent"}),
        })
        log.info("ci_overrides_applied")

    return cfg


# ── 2. detect_system ──────────────────────────────────────────────────────────

def detect_system(refresh: bool = False, repo_root: Path | None = None) -> SystemProfile:
    """Probe hardware/services. Result cached in {repo}/.jsat/system-profile.json."""
    import structlog
    log = structlog.get_logger(__name__)

    # Resolve cache path to repo root so it never lands in CWD when indexing elsewhere
    _root = repo_root or Path.cwd()
    _PROFILE_CACHE = _root / _PROFILE_CACHE_NAME

    if not refresh and _PROFILE_CACHE.exists():
        try:
            profile = SystemProfile.model_validate_json(_PROFILE_CACHE.read_text())
            log.info("system_detect_cache_hit", profile=profile.detected_profile)
            return profile
        except Exception as e:
            log.warning("system_detect_cache_invalid", error=str(e))

    ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
    cpu_arch = platform.machine().lower().replace("amd64", "x86_64")
    gpu = _detect_gpu(log)
    is_ci = os.environ.get("CI", "").lower() in ("true", "1", "yes")

    ollama_up = _ping_http("http://localhost:11434/api/tags", log, "ollama")
    neo4j_up  = _ping_tcp("localhost", 7687, log, "neo4j")
    qdrant_up = _ping_http("http://localhost:6333/healthz", log, "qdrant")
    redis_up  = _ping_tcp("localhost", 6379, log, "redis")

    detected = _compute_profile(ram_gb, cpu_arch, is_ci, neo4j_up, qdrant_up, redis_up)

    profile = SystemProfile(
        ram_gb=ram_gb, cpu_arch=cpu_arch, gpu=gpu, is_ci=is_ci,
        ollama_up=ollama_up, neo4j_up=neo4j_up, qdrant_up=qdrant_up,
        redis_up=redis_up, detected_profile=detected,
    )

    try:
        _PROFILE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _PROFILE_CACHE.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("system_detect_cache_write_failed", error=str(e))

    log.info("system_detected", profile=detected, ram_gb=ram_gb, gpu=gpu)
    return profile


def _detect_gpu(log: Any) -> str:
    try:
        import torch  # type: ignore[import]
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "metal"
    except Exception:
        pass
    if sys.platform == "darwin" and platform.machine().lower() == "arm64":
        return "metal"
    return "none"


def _ping_http(url: str, log: Any, service: str, timeout: float = 0.5) -> bool:
    try:
        resp = httpx.get(url, timeout=timeout)
        up = resp.status_code < 400
        log.info(f"{service}_ping", up=up, status=resp.status_code)
        return up
    except Exception as e:
        log.info(f"{service}_ping", up=False, error=str(e))
        return False


def _ping_tcp(host: str, port: int, log: Any, service: str, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            log.info(f"{service}_ping", up=True)
            return True
    except Exception as e:
        log.info(f"{service}_ping", up=False, error=str(e))
        return False


def _compute_profile(ram_gb: float, cpu_arch: str, is_ci: bool,
                     neo4j_up: bool, qdrant_up: bool, redis_up: bool) -> str:
    if is_ci:
        return "ci"
    if neo4j_up and qdrant_up and redis_up:
        return "team"
    if cpu_arch in ("arm64", "aarch64") and ram_gb < 4.0:
        return "raspberry-pi"
    return "solo"


# ── 3. auto_configure ────────────────────────────────────────────────────────

def auto_configure(cfg: JSATConfig, sys_profile: SystemProfile) -> JSATConfig:
    """Apply auto-selection matrix. Returns new JSATConfig; original unchanged."""
    import structlog
    log = structlog.get_logger(__name__)
    p = sys_profile.detected_profile
    preset = _PRESETS.get(p, {})
    if not preset:
        log.warning("auto_configure_no_preset", profile=p)
        return cfg

    raw = cfg.model_dump()
    for key, val in preset.items():
        if isinstance(val, dict) and key in raw and isinstance(raw[key], dict):
            raw[key].update(val)
        else:
            raw[key] = val

    new_cfg = JSATConfig.model_validate(raw)
    log.info("auto_configured", profile=p,
             graph=new_cfg.graph.backend, ai=new_cfg.ai.provider, cache=new_cfg.cache.backend)
    return new_cfg


# ── 4. write_profile_preset ──────────────────────────────────────────────────

def write_profile_preset(profile: str, output_path: Path) -> None:
    """Write JSAT config for a given profile. Default path: .jsat/config.yaml."""
    import structlog
    log = structlog.get_logger(__name__)

    if profile not in _PRESETS:
        raise ValueError(f"Unknown profile {profile!r}. Valid: {list(_PRESETS)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        yaml.dump({"version": "1", "project_name": "my-project", **_PRESETS[profile]},
                  f, default_flow_style=False, sort_keys=False)
    log.info("profile_preset_written", profile=profile, path=str(output_path))


# ── 5. setup_logging ─────────────────────────────────────────────────────────

def setup_logging(cfg: JSATConfig) -> None:
    """Configure structlog globally based on cfg.log settings.

    Uses structlog's native (non-stdlib) pipeline with PrintLoggerFactory.
    stdlib.add_logger_name is intentionally excluded — it requires a stdlib
    BoundLogger which is incompatible with PrintLoggerFactory / make_filtering_bound_logger.
    """
    import logging
    import structlog

    level_map = {"DEBUG": logging.DEBUG, "INFO": logging.INFO,
                 "WARNING": logging.WARNING, "ERROR": logging.ERROR}
    level = level_map.get(cfg.log.level.upper(), logging.INFO)

    # Also configure stdlib logging so any library that uses it respects the level
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if cfg.log.file:
        Path(cfg.log.file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(cfg.log.file, encoding="utf-8"))
    logging.basicConfig(level=level, handlers=handlers, force=True)

    # Suppress noisy third-party loggers at WARNING by default
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("git").setLevel(logging.WARNING)

    # Native structlog pipeline — no stdlib.add_logger_name (incompatible with PrintLogger)
    processors: list[Any] = [
        structlog.processors.add_log_level,       # native, works with PrintLogger
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer() if cfg.log.format == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
