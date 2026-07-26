"""
jsat._config — Config loader, system detector, auto-configurator.

Core deps only: pydantic, pyyaml, psutil, httpx. structlog imported lazily.
"""
from __future__ import annotations

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
    JSATConfig,
    SystemProfile,
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

def detect_ai_providers(sys_profile: SystemProfile | None = None) -> list[dict]:
    """Probe every AI provider and return a list of availability dicts.

    Each entry: {name, provider_key, available, model, reason, free}
    Ordered: available first, then by preference.
    """
    import os
    import shutil

    results = []

    # 1. Claude CLI (Claude Code) — no key needed if installed
    claude_bin = shutil.which("claude")
    results.append({
        "name":         "Claude Code (CLI)",
        "alias":        "claude-cli",
        "provider_key": "claude_cli",
        "available":    bool(claude_bin),
        "model":        "claude-sonnet-4-6",
        "reason":       "claude binary found" if claude_bin else "claude CLI not installed",
        "free":         False,
        "requires":     "Install Claude Code: claude.ai/code",
    })

    # 2. Bob Shell CLI — no key needed if installed
    bob_bin = shutil.which("bob")
    results.append({
        "name":         "Bob Shell (CLI)",
        "alias":        "bob",
        "provider_key": "bob_cli",
        "available":    bool(bob_bin),
        "model":        "premium",
        "reason":       "bob binary found" if bob_bin else "bob CLI not installed",
        "free":         False,
        "requires":     "Install Bob Shell: npm install -g @ibm/bob-shell",
    })

    # 3. Anthropic API
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    results.append({
        "name":         "Anthropic API",
        "alias":        "claude-api",
        "provider_key": "anthropic",
        "available":    bool(anthropic_key),
        "model":        "claude-sonnet-4-6",
        "reason":       "ANTHROPIC_API_KEY set" if anthropic_key else "ANTHROPIC_API_KEY not set",
        "free":         False,
        "requires":     "export ANTHROPIC_API_KEY=sk-ant-...",
    })

    # 3. OpenAI API
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    results.append({
        "name":         "OpenAI API",
        "alias":        "gpt",
        "provider_key": "openai",
        "available":    bool(openai_key),
        "model":        "gpt-4o",
        "reason":       "OPENAI_API_KEY set" if openai_key else "OPENAI_API_KEY not set",
        "free":         False,
        "requires":     "export OPENAI_API_KEY=sk-...",
    })

    # 4. Gemini API
    gemini_key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
    results.append({
        "name":         "Google Gemini",
        "alias":        "gemini",
        "provider_key": "openai_compat",
        "available":    bool(gemini_key),
        "model":        "gemini-1.5-flash",
        "reason":       "GEMINI_API_KEY set" if gemini_key else "GEMINI_API_KEY not set",
        "free":         False,
        "requires":     "export GEMINI_API_KEY=...",
    })

    # 5. Ollama (local)
    ollama_up = sys_profile.ollama_up if sys_profile else False
    if not sys_profile:
        try:
            import httpx
            ollama_up = httpx.get("http://localhost:11434/api/tags", timeout=0.5).status_code < 400
        except Exception:
            ollama_up = False
    ollama_models: list[str] = []
    if ollama_up:
        try:
            import httpx
            r = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
            ollama_models = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
    results.append({
        "name":         "Ollama (local)",
        "alias":        "ollama",
        "provider_key": "ollama",
        "available":    ollama_up,
        "model":        ollama_models[0] if ollama_models else "llama3.2",
        "models":       ollama_models,
        "reason":       f"running — {len(ollama_models)} model(s)" if ollama_up else "not running",
        "free":         True,
        "requires":     "brew install ollama && ollama serve && ollama pull llama3.2",
    })

    # 6. LM Studio / any OpenAI-compat local server
    lm_up = False
    lm_models: list[str] = []
    try:
        import httpx
        r = httpx.get("http://localhost:1234/v1/models", timeout=0.5)
        if r.status_code < 400:
            lm_up = True
            lm_models = [m["id"] for m in r.json().get("data", [])]
    except Exception:
        pass
    results.append({
        "name":         "LM Studio (local)",
        "alias":        "lmstudio",
        "provider_key": "openai_compat",
        "available":    lm_up,
        "model":        lm_models[0] if lm_models else "local-model",
        "models":       lm_models,
        "reason":       f"running at localhost:1234 — {len(lm_models)} model(s)" if lm_up else "not running",
        "free":         True,
        "requires":     "Download LM Studio from lmstudio.ai → load model → start server",
    })

    # Sort: available first, then by documented preference order
    # (Claude CLI → Bob CLI → Anthropic → OpenAI → Gemini → Ollama → LM Studio),
    # falling back to name for anything not explicitly ranked.
    _priority = {
        "claude_cli": 0, "bob_cli": 1, "anthropic": 2,
        "openai": 3, "openai_compat": 4, "ollama": 5,
    }
    results.sort(
        key=lambda x: (not x["available"], _priority.get(x["provider_key"], 99), x["name"]))
    return results


def _provider_reachable(provider_key: str, sys_profile: SystemProfile | None) -> bool:
    """Quick check whether a provider is currently usable."""
    import os
    import shutil
    if provider_key == "claude_cli":
        return bool(shutil.which("claude"))
    if provider_key == "bob_cli":
        return bool(shutil.which("bob"))
    if provider_key == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if provider_key == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    if provider_key == "openai_compat":
        return True   # assume configured manually; don't block
    if provider_key == "ollama":
        return sys_profile.ollama_up if sys_profile else False
    if provider_key == "none":
        return False
    return False


def best_available_ai_provider(sys_profile: SystemProfile | None = None) -> str:
    """Return the provider_key of the best available AI provider."""
    for p in detect_ai_providers(sys_profile):
        if p["available"]:
            return p["provider_key"]
    return "none"


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

    # Auto-select best available AI provider when the configured one is unreachable.
    # Priority: claude_cli > anthropic API > openai API > gemini > ollama > lmstudio
    configured = new_cfg.ai.provider
    provider_is_up = _provider_reachable(configured, sys_profile)
    if not provider_is_up:
        providers = detect_ai_providers(sys_profile)
        best_entry = next((p for p in providers if p["available"]), None)
        if best_entry and best_entry["provider_key"] != configured:
            new_cfg = new_cfg.model_copy(update={
                "ai": new_cfg.ai.model_copy(update={
                    "provider": best_entry["provider_key"],
                    "model":    best_entry["model"],
                })
            })
            log.info("auto_configure_ai_fallback",
                     was=configured, now=best_entry["provider_key"],
                     model=best_entry["model"],
                     reason=f"'{configured}' not reachable, using {best_entry['name']}")

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
