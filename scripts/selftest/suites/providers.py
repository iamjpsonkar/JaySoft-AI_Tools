"""
Phase H — all nine AI providers.

The CLI-subprocess providers (claude_cli/codex_cli/opencode_cli/bob_cli) can
be tested for real with no API key at all, because they borrow whatever
account the user already configured in that tool. The API providers cannot,
so for those the thing worth asserting is the *failure* path: a missing key
must surface as JSAT's typed AIAuthError, not a raw SDK traceback, or the
"errors degrade, they do not crash" convention is broken where it matters
most.

A coverage gate asserts every provider `get_ai_provider()` knows how to build
is accounted for.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..core import FAIL, PASS, UNAVAILABLE, Check, Report, run_cli, timed

# provider -> the binary it shells out to (None = HTTP API)
CLI_PROVIDERS = {
    "claude_cli": "claude",
    "codex_cli": "codex",
    "opencode_cli": "opencode",
    "bob_cli": "bob",
}
API_PROVIDERS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai_compat": "OPENAI_API_KEY",
}

PROMPT = "Reply with exactly one word: pong"


def _cfg_for(provider: str, model: str | None = None):
    """A full JSATConfig selecting `provider`.

    `get_ai_provider` reads `cfg.ai.provider`, so it needs the whole config.
    Handing it a bare AIConfig silently produced a NoOpProvider, which made
    these checks pass for the wrong reason — NoOpProvider raises AIError, so
    an assertion of "raises a typed error" was satisfied without the real
    provider ever being built.
    """
    from jsat._models import AIConfig, JSATConfig
    cfg = JSATConfig()
    cfg.ai = AIConfig(provider=provider, model=model)  # type: ignore[arg-type]
    return cfg


def _known_providers() -> set[str]:
    """Every provider string get_ai_provider() branches on."""
    import inspect

    from jsat import _ai
    src = inspect.getsource(_ai.get_ai_provider)
    import re
    return set(re.findall(r'==\s*"([a-z_]+)"', src)) | \
        set(re.findall(r'in\s*\(\s*"([a-z_]+)"', src))


@timed
def check_ai_status(jsat_bin: str, env: dict[str, str]) -> Check:
    r = run_cli(jsat_bin, ["ai", "status"], env, timeout=60)
    if r.returncode != 0:
        return Check("ai_status", "ai_provider", FAIL, "jsat ai status failed",
                     detail=f"rc={r.returncode} {r.stderr[:300]}")
    return Check("ai_status", "ai_provider", PASS,
                 "jsat ai status enumerated the detected providers",
                 detail=r.stdout[:300])


@timed
def check_ai_models(jsat_bin: str, env: dict[str, str]) -> Check:
    r = run_cli(jsat_bin, ["ai", "models"], env, timeout=90)
    if r.returncode != 0:
        return Check("ai_models", "ai_provider", FAIL, "jsat ai models failed",
                     detail=f"rc={r.returncode} {r.stderr[:300]}")
    return Check("ai_models", "ai_provider", PASS, "jsat ai models ran",
                 detail=r.stdout[:250])


@timed
def check_cli_provider_completion(provider: str, binary: str, tmp: Path,
                                  allow_llm: bool) -> Check:
    """A real completion through a real locally-installed CLI tool."""
    if not shutil.which(binary):
        return Check(f"provider_{provider}", "ai_provider", UNAVAILABLE,
                     f"`{binary}` is not installed, so {provider} cannot be tested",
                     remediation=f"install {binary} to cover this provider")
    if not allow_llm:
        return Check(f"provider_{provider}", "ai_provider", UNAVAILABLE,
                     f"{binary} is installed but a real completion costs tokens; "
                     "skipped without --llm")
    from jsat._ai import get_ai_provider
    try:
        p = get_ai_provider(_cfg_for(provider))
    except Exception as e:
        return Check(f"provider_{provider}", "ai_provider", FAIL,
                     f"could not construct {provider}: {type(e).__name__}: {e}")
    if not p.is_available():
        return Check(f"provider_{provider}", "ai_provider", UNAVAILABLE,
                     f"{provider} reports itself unavailable even though "
                     f"`{binary}` is on PATH")
    try:
        out = p.complete(PROMPT)
    except Exception as e:
        return Check(f"provider_{provider}", "ai_provider", FAIL,
                     f"{provider}.complete() raised {type(e).__name__}: "
                     f"{str(e)[:200]}")
    if not (out or "").strip():
        return Check(f"provider_{provider}", "ai_provider", FAIL,
                     f"{provider}.complete() returned an empty string")
    return Check(f"provider_{provider}", "ai_provider", PASS,
                 f"{provider} answered a real completion via the local "
                 f"`{binary}` binary",
                 detail=out.strip()[:200])


@timed
def check_api_provider_error_path(provider: str, key_env: str) -> Check:
    """With no credential, the failure must be JSAT's typed error."""
    if os.environ.get(key_env, "").strip():
        return Check(f"provider_{provider}_error_path", "ai_provider", UNAVAILABLE,
                     f"{key_env} IS set, so the missing-credential path cannot "
                     "be exercised here")
    from jsat._ai import get_ai_provider
    from jsat._exceptions import JSATError
    try:
        p = get_ai_provider(_cfg_for(provider, model="some-model"))
    except JSATError as e:
        return Check(f"provider_{provider}_error_path", "ai_provider", PASS,
                     f"constructing {provider} without {key_env} raised a typed "
                     f"{type(e).__name__}", detail=str(e)[:200])
    except Exception as e:
        return Check(f"provider_{provider}_error_path", "ai_provider", FAIL,
                     f"constructing {provider} raised untyped "
                     f"{type(e).__name__}: {str(e)[:150]}",
                     remediation="wrap it in a jsat._exceptions type")
    try:
        p.complete(PROMPT)
    except JSATError as e:
        return Check(f"provider_{provider}_error_path", "ai_provider", PASS,
                     f"{provider}.complete() without {key_env} raised a typed "
                     f"{type(e).__name__}", detail=str(e)[:200])
    except Exception as e:
        return Check(f"provider_{provider}_error_path", "ai_provider", FAIL,
                     f"{provider}.complete() without a key raised untyped "
                     f"{type(e).__name__} — callers cannot degrade on it",
                     detail=str(e)[:250],
                     remediation="translate SDK errors into AIAuthError/"
                                 "AIProviderError in jsat/_ai/"
                                 f"{provider}.py")
    return Check(f"provider_{provider}_error_path", "ai_provider", FAIL,
                 f"{provider}.complete() SUCCEEDED with no {key_env} set — "
                 "that should be impossible")


@timed
def check_ollama_provider(allow_llm: bool) -> Check:
    from ..core import http_get
    status, body = http_get("http://localhost:11434/api/tags", timeout=3)
    if status != 200:
        return Check("provider_ollama", "ai_provider", UNAVAILABLE,
                     "ollama is not reachable at localhost:11434")
    import json
    models = json.loads(body).get("models", [])
    if not models:
        return Check("provider_ollama", "ai_provider", UNAVAILABLE,
                     "ollama is running but has no models pulled, so no "
                     "completion is possible",
                     remediation="ollama pull qwen2.5:0.5b")
    if not allow_llm:
        return Check("provider_ollama", "ai_provider", UNAVAILABLE,
                     "ollama has models but completion is skipped without --llm")
    from jsat._ai import get_ai_provider
    name = models[0]["name"]
    p = get_ai_provider(_cfg_for("ollama", model=name))
    try:
        out = p.complete(PROMPT)
    except Exception as e:
        return Check("provider_ollama", "ai_provider", FAIL,
                     f"ollama.complete() raised {type(e).__name__}: {str(e)[:200]}")
    return Check("provider_ollama", "ai_provider", PASS,
                 f"ollama answered a real completion with {name}",
                 detail=(out or "").strip()[:200])


@timed
def check_none_provider() -> Check:
    from jsat._ai import get_ai_provider
    from jsat._exceptions import AIError
    p = get_ai_provider(_cfg_for("none"))
    if p.is_available():
        return Check("provider_none", "ai_provider", FAIL,
                     "the `none` provider reports itself available")
    try:
        p.complete(PROMPT)
    except AIError:
        return Check("provider_none", "ai_provider", PASS,
                     "the `none` provider is unavailable and raises AIError on "
                     "use, as the SDK contract documents")
    except Exception as e:
        return Check("provider_none", "ai_provider", FAIL,
                     f"`none` raised {type(e).__name__}, expected AIError")
    return Check("provider_none", "ai_provider", FAIL,
                 "`none`.complete() did not raise")


@timed
def check_ai_use_persists(jsat_bin: str, tmp: Path, env: dict[str, str]) -> Check:
    """`jsat ai use` must write the choice where the next process reads it."""
    home = tmp / "ai-use-home"
    home.mkdir(parents=True, exist_ok=True)
    scoped = {**env, "HOME": str(home),
              "JSAT_DATA_DIR": str(tmp / "ai-use-data")}
    use = run_cli(jsat_bin, ["ai", "use", "claude_cli"], scoped,
                  cwd=str(tmp), timeout=90)
    if use.returncode != 0:
        return Check("ai_use_persists", "ai_provider", FAIL,
                     "jsat ai use claude_cli failed",
                     detail=f"rc={use.returncode} {r_err(use)}")
    status = run_cli(jsat_bin, ["ai", "status"], scoped, cwd=str(tmp), timeout=90)
    blob = (status.stdout + status.stderr).lower()
    if "claude" not in blob:
        return Check("ai_use_persists", "ai_provider", FAIL,
                     "a provider chosen with `jsat ai use` was not reflected by "
                     "a later `jsat ai status` in the same environment",
                     detail=status.stdout[:400],
                     remediation="the choice is not being persisted to the "
                                 "config the next process loads")
    return Check("ai_use_persists", "ai_provider", PASS,
                 "`jsat ai use` persisted the provider across processes")


def r_err(proc: object) -> str:
    return getattr(proc, "stderr", "")[:250]


@timed
def check_provider_coverage(exercised: set[str]) -> Check:
    known = _known_providers()
    if not known:
        return Check("provider_coverage", "ai_provider", UNAVAILABLE,
                     "could not introspect get_ai_provider's branches")
    missing = sorted(known - exercised)
    if missing:
        return Check("provider_coverage", "ai_provider", FAIL,
                     f"{len(missing)} provider(s) get_ai_provider knows are "
                     "never exercised",
                     detail=", ".join(missing),
                     remediation="add them to CLI_PROVIDERS/API_PROVIDERS in "
                                 "scripts/selftest/suites/providers.py")
    return Check("provider_coverage", "ai_provider", PASS,
                 f"all {len(known)} providers get_ai_provider supports are "
                 "exercised")


def run(report: Report, jsat_bin: str, tmp: Path, env: dict[str, str], *,
        allow_llm: bool) -> None:
    exercised: set[str] = set()
    report.add(check_ai_status(jsat_bin, env))
    report.add(check_ai_models(jsat_bin, env))
    report.add(check_ai_use_persists(jsat_bin, tmp, env))

    for provider, binary in CLI_PROVIDERS.items():
        report.add(check_cli_provider_completion(provider, binary, tmp, allow_llm))
        exercised.add(provider)
    for provider, key_env in API_PROVIDERS.items():
        report.add(check_api_provider_error_path(provider, key_env))
        exercised.add(provider)
    report.add(check_ollama_provider(allow_llm)); exercised.add("ollama")
    report.add(check_none_provider()); exercised.add("none")
    report.add(check_provider_coverage(exercised))
