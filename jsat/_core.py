"""
jsat._core — JSAT main class.

Thin shell: all tool logic lives in jsat/tools/. Every heavy import is lazy.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator

if TYPE_CHECKING:
    from jsat._ai import AIProvider
    from jsat._graph import GraphClient
    from jsat._models import (
        BlastRadiusReport,
        ExportManifest,
        IncidentReport,
        IndexEvent,
        IndexResult,
        JSATConfig,
        QueryResult,
        SecurityReport,
        SystemProfile,
    )


class JSAT:
    """Main user-facing object for JSAT codebase intelligence.

    All heavy dependencies are loaded lazily on first use.
    Instantiation is fast — only config loading and system detection run.
    """

    def __init__(
        self,
        repo: str | Path = ".",
        config: str | Path | None = None,
        ai_provider: str | None = None,
        model: str | None = None,
        log_level: str = "WARNING",
    ) -> None:
        import structlog

        from jsat._config import auto_configure, detect_system, load_config, setup_logging
        from jsat._models import JSATConfig as _JSATConfig

        # Apply log level FIRST so config/detect INFO logs are suppressed by default.
        # We use a minimal temporary config — reconfigured below with real settings.
        _tmp_cfg = _JSATConfig()
        _tmp_cfg = _tmp_cfg.model_copy(
            update={"log": _tmp_cfg.log.model_copy(update={"level": log_level})}
        )
        setup_logging(_tmp_cfg)

        self._repo = Path(repo).resolve()
        self._cfg: JSATConfig = load_config(config)

        # ── Pin all .jsat/* paths to repo root ───────────────────────────────
        # Without this, SQLiteGraph and system-profile.json are created relative
        # to CWD, which scatters files when indexing a different directory.
        self._cfg = self._pin_paths_to_repo(self._cfg)

        self._sys: SystemProfile = detect_system(repo_root=self._repo)
        self._cfg = auto_configure(self._cfg, self._sys)

        # Caller overrides win over auto-configure
        if ai_provider:
            self._cfg = self._cfg.model_copy(
                update={"ai": self._cfg.ai.model_copy(update={"provider": ai_provider})}
            )
        if model:
            self._cfg = self._cfg.model_copy(
                update={"ai": self._cfg.ai.model_copy(update={"model": model})}
            )

        # Reconfigure logging with actual config (level may differ from tmp)
        self._cfg = self._cfg.model_copy(
            update={"log": self._cfg.log.model_copy(update={"level": log_level})}
        )
        setup_logging(self._cfg)

        self._graph: GraphClient | None = None
        self._ai: AIProvider | None = None
        self._active_provider: str = self._cfg.ai.provider
        self._active_model: str = self._cfg.ai.model

        log = structlog.get_logger(__name__)
        log.info("jsat_init", repo=str(self._repo),
                 jsat_dir=str(self._repo / ".jsat"),
                 profile=self._sys.detected_profile,
                 ai_provider=self._cfg.ai.provider,
                 graph_backend=self._cfg.graph.backend)

    def switch_ai(self, provider: str, model: str | None = None,
                  base_url: str | None = None) -> tuple[str, str]:
        """Switch the AI provider mid-session. Returns (provider, model) that's now active.

        Supported aliases:
          claude, anthropic     → Anthropic API
          gpt, openai, chatgpt  → OpenAI API
          ollama                → local Ollama
          gemini                → Google Gemini (via OpenAI-compat endpoint)
          lmstudio              → LM Studio (localhost:1234)
          codex                 → OpenAI (codex models)
          custom, compat        → any OpenAI-compatible URL (pass base_url=)
        """

        # Resolve provider alias + default model
        import shutil as _shutil
        _claude_cli_available = bool(_shutil.which("claude"))

        _aliases: dict[str, tuple[str, str, str | None]] = {
            # alias → (internal_provider, default_model, base_url)
            # "claude" prefers CLI if installed (no API key needed), else falls back to API
            "claude":     ("claude_cli" if _claude_cli_available else "anthropic",
                           "claude-sonnet-4-6", None),
            "claude-api": ("anthropic",    "claude-sonnet-4-6",             None),
            "claude-cli": ("claude_cli",   "claude-sonnet-4-6",             None),
            "anthropic":  ("anthropic",    "claude-sonnet-4-6",             None),
            "haiku":      ("anthropic",    "claude-haiku-4-5-20251001",     None),
            "opus":       ("anthropic",    "claude-opus-4-8",               None),
            "gpt":        ("openai",       "gpt-4o",                        None),
            "openai":     ("openai",       "gpt-4o",                        None),
            "chatgpt":    ("openai",       "gpt-4o",                        None),
            "gpt4":       ("openai",       "gpt-4o",                        None),
            "gpt4mini":   ("openai",       "gpt-4o-mini",                   None),
            "codex":      ("openai",       "gpt-4o",                        None),
            "ollama":     ("ollama",       "llama3.2",                      None),
            "llama":      ("ollama",       "llama3.2",                      None),
            "phi":        ("ollama",       "phi3:mini",                     None),
            "gemini":     ("openai_compat","gemini-1.5-flash",
                           "https://generativelanguage.googleapis.com/v1beta/openai"),
            "gemini-pro": ("openai_compat","gemini-1.5-pro",
                           "https://generativelanguage.googleapis.com/v1beta/openai"),
            "lmstudio":   ("openai_compat","local-model",                   "http://localhost:1234/v1"),
            "lm-studio":  ("openai_compat","local-model",                   "http://localhost:1234/v1"),
            "custom":     ("openai_compat","local-model",                    base_url or "http://localhost:1234/v1"),
            "compat":     ("openai_compat","local-model",                    base_url or "http://localhost:1234/v1"),
        }

        alias = provider.lower().strip()
        if alias not in _aliases:
            raise ValueError(
                f"Unknown provider '{provider}'.\n"
                f"Available: {', '.join(sorted(_aliases))}"
            )

        internal, default_model, resolved_url = _aliases[alias]
        chosen_model = model or default_model
        chosen_url = base_url or resolved_url

        # Update config
        ai_update: dict = {"provider": internal, "model": chosen_model}
        if chosen_url:
            ai_update["base_url"] = chosen_url
        self._cfg = self._cfg.model_copy(
            update={"ai": self._cfg.ai.model_copy(update=ai_update)}
        )

        # Reset cached AI so _get_ai() rebuilds with new config
        self._ai = None
        self._active_provider = alias
        self._active_model = chosen_model

        # Verify reachability
        try:
            ai = self._get_ai()
            ok = ai.is_available()
        except Exception:
            ok = False

        return alias, chosen_model, ok  # type: ignore[return-value]

    def active_ai_label(self) -> str:
        """Short human-readable label: 'Claude Code (CLI)' or 'GPT (gpt-4o-mini)'"""
        _labels = {
            "claude_cli":   "Claude Code (CLI)",
            "anthropic":    "Claude API",
            "openai":       "GPT",
            "ollama":       "Ollama",
            "openai_compat":"Local/Compat",
            "none":         "No AI",
        }
        provider = self._cfg.ai.provider
        name = _labels.get(provider, provider)
        model = self._cfg.ai.model
        # For claude_cli the model is internal; show just the provider name
        if provider == "claude_cli":
            return name
        return f"{name} ({model})"

    def _pin_paths_to_repo(self, cfg: JSATConfig) -> JSATConfig:
        """Resolve all relative .jsat/* paths against self._repo.

        Prevents files being scattered in CWD when indexing a different directory.
        All JSAT state lives exclusively inside {repo}/.jsat/.
        """
        root = self._repo

        def _abs(p: str) -> str:
            """Make p absolute, rooted at repo if it starts with .jsat."""
            path = Path(p)
            if path.is_absolute():
                return p
            # Re-root .jsat/* paths (and plain relative paths) under the repo
            return str(root / path)

        return cfg.model_copy(update={
            "graph": cfg.graph.model_copy(update={
                "path": _abs(cfg.graph.path),
            }),
            "embeddings": cfg.embeddings.model_copy(update={
                "vector_store": cfg.embeddings.vector_store.model_copy(update={
                    "path": _abs(cfg.embeddings.vector_store.path),
                }),
            }),
            "cache": cfg.cache.model_copy(update={
                "disk_path": _abs(cfg.cache.disk_path),
            }),
            "skills": cfg.skills.model_copy(update={
                "dir": _abs(cfg.skills.dir),
            }),
        })

    # ── Lazy backend accessors ────────────────────────────────────────────────

    def _get_graph(self) -> GraphClient:
        if self._graph is not None:
            return self._graph
        backend = self._cfg.graph.backend
        if backend == "neo4j":
            try:
                from jsat._graph.neo4j import Neo4jGraph  # type: ignore[import]
                self._graph = Neo4jGraph(self._cfg.graph)
            except ImportError as e:
                from jsat._exceptions import ProfileError
                raise ProfileError("Neo4j requires jsat[team].\nInstall: pip install 'jsat[team]'",
                                   required_extra="team") from e
        else:
            from jsat._graph.sqlite import SQLiteGraph
            self._graph = SQLiteGraph(self._cfg.graph)
        return self._graph

    def _get_ai(self) -> AIProvider:
        if self._ai is not None:
            return self._ai
        from jsat._ai import get_ai_provider
        from jsat._ai.none import NoOpProvider
        try:
            provider = get_ai_provider(self._cfg)
            if not provider.is_available():
                import structlog
                structlog.get_logger(__name__).warning(
                    "ai_provider_unavailable",
                    provider=self._cfg.ai.provider,
                    message="Falling back to NoOpProvider",
                )
                provider = NoOpProvider()
            self._ai = provider
        except Exception:
            self._ai = NoOpProvider()
        return self._ai

    # ── Public API ────────────────────────────────────────────────────────────

    def index(
        self,
        path: str | Path | None = None,
        branch: str = "HEAD",
        force: bool = False,
        languages: list[str] | None = None,
    ) -> IndexResult:
        """Build or update the codebase index. Blocks until complete."""
        from jsat.tools.indexer import IndexerTool
        target = Path(path).resolve() if path else self._repo
        return IndexerTool(graph=self._get_graph(), cfg=self._cfg).run(
            target, branch, force, languages
        )

    def index_stream(
        self,
        path: str | Path | None = None,
        branch: str = "HEAD",
    ) -> Generator[IndexEvent, None, IndexResult]:
        """Stream progress events while indexing."""
        from jsat.tools.indexer import IndexerTool
        target = Path(path).resolve() if path else self._repo
        return IndexerTool(graph=self._get_graph(), cfg=self._cfg).run_stream(target, branch)

    def query(
        self,
        question: str,
        context_budget: int = 8192,
        service: str | None = None,
        ithinking: bool = False,
    ) -> QueryResult:
        """Natural language query over the codebase graph."""
        from jsat.tools.query import QueryTool
        return QueryTool(
            graph=self._get_graph(), ai=self._get_ai(), cfg=self._cfg
        ).run(question, context_budget=context_budget, service=service)

    def blast_radius(
        self,
        target: str,
        diff: str | None = None,
        max_depth: int = 5,
        severity_filter: list[str] | None = None,
    ) -> BlastRadiusReport:
        """Trace downstream impact of a change."""
        from jsat.tools.blast_radius import BlastRadiusTool
        return BlastRadiusTool(graph=self._get_graph(), cfg=self._cfg).run(
            target, diff, max_depth, severity_filter
        )

    def security_review(
        self,
        path: str | Path = ".",
        severity_threshold: str = "medium",
        include_deps: bool = True,
    ) -> SecurityReport:
        """Run security analysis. Requires jsat[standard]."""
        try:
            from jsat.tools.security import SecurityTool
        except ImportError as e:
            from jsat._exceptions import ProfileError
            raise ProfileError("Security review requires jsat[standard].\n"
                               "Install: pip install 'jsat[standard]'",
                               required_extra="standard") from e
        return SecurityTool(graph=self._get_graph(), cfg=self._cfg).run(
            Path(path), severity_threshold, include_deps
        )

    def investigate_incident(
        self,
        description: str,
        since: str = "72h",
        services: list[str] | None = None,
    ) -> IncidentReport:
        """Investigate a production incident."""
        from jsat.tools.incident import IncidentTool
        return IncidentTool(
            graph=self._get_graph(), ai=self._get_ai(), cfg=self._cfg
        ).run(description, since, services)

    def export(
        self,
        output: str | Path,
        compress_level: int = 6,
        encrypt: bool = False,
        password: str | None = None,
    ) -> ExportManifest:
        """Export the index as a portable zip."""
        from jsat.tools.export import ExportTool
        return ExportTool(graph=self._get_graph(), cfg=self._cfg).export(
            Path(output), compress_level
        )

    @classmethod
    def from_import(cls, archive: str | Path, password: str | None = None) -> JSAT:
        """Restore a JSAT instance from an exported archive."""
        from jsat.tools.export import ExportTool
        instance = cls(repo=str(Path(archive).parent))
        ExportTool(graph=instance._get_graph(), cfg=instance._cfg).restore(Path(archive))
        return instance

    def prompt(
        self,
        raw_input: str,
        ai_provider: str | None = None,
        output_format: str | None = None,
        cot: bool = False,
        compress: bool = True,
        max_context_tokens: int = 4096,
        few_shot_k: int = 3,
        no_context: bool = False,
        no_examples: bool = False,
    ) -> Any:
        """Optimize a raw query into the best possible prompt via the 7-stage pipeline."""
        from jsat.tools.prompt_optimizer import PromptOptimizer
        optimizer = PromptOptimizer(graph=self._get_graph(), cfg=self._cfg, ai=self._get_ai())
        return optimizer.optimize(
            raw_input, ai_provider=ai_provider, output_format=output_format,
            cot=cot, compress=compress, max_context_tokens=max_context_tokens,
            few_shot_k=few_shot_k, no_context=no_context, no_examples=no_examples,
        )

    def prompt_stream(self, raw_input: str, **kwargs: Any):
        """Optimize a query and stream the AI response token by token.

        Usage:
            async for chunk in js.prompt_stream("improve the retry logic"):
                print(chunk, end="", flush=True)
        """
        from jsat.tools.prompt_optimizer import PromptOptimizer
        result = self.prompt(raw_input, **kwargs)
        ai = self._get_ai()
        optimizer = PromptOptimizer(graph=self._get_graph(), cfg=self._cfg, ai=ai)
        response_chunks: list[str] = []
        for chunk in ai.stream(result.optimized_prompt, max_tokens=2048):
            response_chunks.append(chunk)
            yield chunk
        optimizer.save_to_history(result, "".join(response_chunks))

    def prompt_and_send(self, raw_input: str, **kwargs: Any) -> dict[str, Any]:
        """Optimize a query and send it to the configured AI. Returns {response, prompt_result}."""
        from jsat.tools.prompt_optimizer import PromptOptimizer
        result = self.prompt(raw_input, **kwargs)
        ai = self._get_ai()
        response = ai.complete(result.optimized_prompt, max_tokens=2048)
        optimizer = PromptOptimizer(graph=self._get_graph(), cfg=self._cfg, ai=ai)
        optimizer.save_to_history(result, response)
        return {"response": response, "prompt_result": result}

    @property
    def index_status(self) -> dict[str, Any]:
        """Quick snapshot: nodes, edges, commit, is_fresh."""
        try:
            g = self._get_graph()
            return {
                "nodes": g.node_count(),
                "edges": g.edge_count(),
                "commit": None,
                "is_fresh": True,
            }
        except Exception as e:
            return {"nodes": 0, "edges": 0, "commit": None, "is_fresh": False, "error": str(e)}

    def doctor(self) -> dict[str, Any]:
        """Full health check — what the CLI `jsat doctor` calls."""
        from jsat._config import detect_ai_providers, detect_system
        sys_profile = detect_system(refresh=True, repo_root=self._repo)

        graph_ok, graph_err = False, None
        try:
            g = self._get_graph()
            graph_ok = g.node_count() >= 0
        except Exception as e:
            graph_err = str(e)

        ai_ok, ai_err = False, None
        try:
            ai_ok = self._get_ai().is_available()
        except Exception as e:
            ai_err = str(e)

        return {
            "version": "0.1.8",
            "system": {
                "ram_gb": sys_profile.ram_gb,
                "cpu_arch": sys_profile.cpu_arch,
                "gpu": sys_profile.gpu,
                "is_ci": sys_profile.is_ci,
            },
            "profile": sys_profile.detected_profile,
            "services": {
                "ollama": {"running": sys_profile.ollama_up},
                "neo4j":  {"running": sys_profile.neo4j_up},
                "qdrant": {"running": sys_profile.qdrant_up},
                "redis":  {"running": sys_profile.redis_up},
            },
            "graph": {"ok": graph_ok, "backend": self._cfg.graph.backend, "error": graph_err},
            "ai": {
                "ok": ai_ok,
                "provider": self._cfg.ai.provider,
                "model": self._cfg.ai.model,
                "error": ai_err,
                "available_providers": detect_ai_providers(sys_profile),
            },
            "index": self.index_status,
        }
