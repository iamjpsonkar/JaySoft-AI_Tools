"""jsat.ui.tui — terminal UI for JSAT Studio (optional dependency).

Requires the ``studio`` extra (``pip install jsat[studio]`` → ``textual``).
Every screen runs the same ``StudioAPI`` the web app uses, so the terminal and
the browser expose identical behaviours.
"""
from __future__ import annotations

from typing import Any


def _textual_available() -> bool:
    try:
        import textual  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def run_tui(js: Any, port: int = 7434) -> int:
    """Run the Textual app in the terminal. Returns a process exit code."""
    if not _textual_available():
        print("The terminal UI needs the `studio` extra — install it with:\n\n"
              "    pip install 'jsat[studio]'")
        return 2

    from jsat.ui._api import StudioAPI

    try:
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Horizontal, VerticalScroll
        from textual.widgets import Footer, Header, Input, Static
    except Exception as e:  # noqa: BLE001
        print(f"Textual import failed ({e}) — try `pip install 'jsat[studio]'`")
        return 2

    api = StudioAPI(js)

    class StudioApp(App[None]):
        CSS = """
        #prompt { margin: 0 1; }
        #out { border: tall $primary; padding: 0 1; }
        #tabs { height: 3; }
        #tabs > Button { width: auto; }
        .hint { color: $text-muted; }
        """
        BINDINGS = [
            Binding("ctrl+q", "quit", "Quit"),
            Binding("/", "focus_prompt", "Prompt"),
            Binding("s", "switch('status')", "Status"),
            Binding("t", "switch('tools')", "Tools"),
            Binding("g", "switch('graph')", "Graph"),
            Binding("i", "improve", "Improve"),
        ]

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Horizontal(
                Static("", id="out-caption", classes="hint"),
                id="tabs",
            )
            yield VerticalScroll(Static("Ready.", id="out"))
            yield Input(placeholder="Ask JSAT anything (e.g. what breaks if I change refund()?)",
                        id="prompt")
            yield Footer()

        def on_mount(self) -> None:
            self.action_switch("status")

        def action_focus_prompt(self) -> None:
            self.query_one(Input).focus()

        def action_switch(self, name: str) -> None:
            self._show(name if name in ("status", "tools", "graph") else "status")

        def _show(self, name: str) -> None:
            out = self.query_one("#out", Static)
            cap = self.query_one("#out-caption", Static)
            try:
                if name == "status":
                    cap.update("STATUS — index + provider")
                    out.update(str(api.status()) + "\n" + str(api.index()))
                elif name == "tools":
                    cap.update(f"TOOLS — all {len(api.catalog())} registered")
                    out.update("\n".join(t["name"] for t in api.catalog()))
                elif name == "graph":
                    cap.update("GRAPH — first 12 functions")
                    rows = api.nodes("function", limit=12).get("rows", [])
                    out.update("\n".join(
                        f"{r.get('name','')}  {r.get('file','')}" for r in rows))
            except Exception as e:  # noqa: BLE001
                out.update(f"error: {e}")

        def on_input_submitted(self, event: Input.Submitted) -> None:
            text = event.value.strip()
            event.input.value = ""
            if not text:
                return
            out = self.query_one("#out", Static)
            out.update(f"▸ {text}\n…")
            try:
                res = api.prompt(text)
                body = res.get("result") or res.get("error") or ""
                intent = res.get("intent", "?")
                msg = f"▸ {text}\n  intent: {intent} (conf {res.get('confidence')})\n\n{body}"
                out.update(msg)
            except Exception as e:  # noqa: BLE001
                out.update(f"▸ {text}\n  error: {e}")

        def action_improve(self) -> None:
            out = self.query_one("#out", Static)
            out.update(str(api.run_tool("improve_status", {})))

    StudioApp().run()
    return 0


__all__ = ["run_tui"]