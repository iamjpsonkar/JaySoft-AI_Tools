"""Documentation contracts for the distinct AI execution paths."""
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
INTEGRATIONS = ROOT / "docs" / "integrations"

GUIDES = {
    "codex.md": ("jsat connect codex", "jsat start codex --via native"),
    "claude.md": ("jsat connect claude --global", "jsat start claude --via native"),
    "opencode.md": ("jsat connect opencode", "jsat start opencode --via native"),
    "ollama-local.md": ("jsat ai use ollama", "jsat ai test"),
    "ollama-claude.md": (
        "jsat connect ollama tool=claude",
        "jsat start claude --via ollama",
    ),
    "ollama-opencode.md": (
        "jsat connect ollama tool=opencode",
        "jsat start opencode --via ollama",
    ),
    "ollama-codex.md": (
        "jsat connect ollama tool=codex",
        "jsat start codex --via ollama",
    ),
}


@pytest.mark.ci
@pytest.mark.parametrize(("filename", "commands"), GUIDES.items())
def test_integration_guide_is_complete(filename: str, commands: tuple[str, str]) -> None:
    text = (INTEGRATIONS / filename).read_text(encoding="utf-8")

    for command in commands:
        assert command in text
    assert "verify" in text.lower()
    assert "troubleshooting" in text.lower()
    assert "model" in text.lower()


@pytest.mark.ci
def test_tabbed_chooser_and_mkdocs_nav_link_every_guide() -> None:
    chooser = (INTEGRATIONS / "index.md").read_text(encoding="utf-8")
    nav = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    assert '=== "Codex"' in chooser
    assert '=== "Claude"' in chooser
    assert '=== "Ollama local"' in chooser
    assert '=== "Ollama + Claude"' in chooser
    for filename in GUIDES:
        assert f"({filename})" in chooser
        assert f"integrations/{filename}" in nav


@pytest.mark.ci
def test_readme_explains_provider_isolation_and_links_the_chooser() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "### Choose your execution path" in readme
    assert "docs/integrations/index.md" in readme
    assert "does not silently become the provider" in readme
    for filename in GUIDES:
        assert f"docs/integrations/{filename}" in readme


# Bob and DeepSeek are intentionally NOT in GUIDES: that dict (and the two tests above)
# specifically cover the native-vs-Ollama-launched execution-path story for tools Ollama
# can launch (claude/codex/opencode). Bob isn't Ollama-launchable and DeepSeek isn't a
# coding-agent CLI at all (it's a hosted-API provider) — neither fits that chooser.

@pytest.mark.ci
def test_bob_guide_is_complete() -> None:
    text = (INTEGRATIONS / "bob.md").read_text(encoding="utf-8")

    assert "jsat connect bob --global" in text
    assert "jsat bob" in text
    assert "verify" in text.lower()
    assert "troubleshooting" in text.lower()
    assert "model" in text.lower()


@pytest.mark.ci
def test_deepseek_guide_is_complete_and_distinguishes_from_the_harness() -> None:
    text = (INTEGRATIONS / "deepseek.md").read_text(encoding="utf-8")

    assert "DEEPSEEK_API_KEY" in text
    assert "jsat ai use deepseek" in text
    assert "verify" in text.lower()
    assert "troubleshooting" in text.lower()
    assert "model" in text.lower()
    # Must explicitly disclaim being a launchable coding-agent CLI, not just omit it.
    assert "no `jsat connect deepseek`" in text
    assert "harness" in text.lower()
