"""
jsat.cli — CLI entrypoint: imports sub-modules to register all commands.

All commands are defined in the _cli_* sub-modules. This file only wires
them together so `jsat` resolves to the right Typer app.
"""
from __future__ import annotations

import jsat._cli_ai  # noqa: F401  — registers ai subcommands
import jsat._cli_connect  # noqa: F401  — registers connect subcommands
import jsat._cli_improve  # noqa: F401  — registers the improve command
import jsat._cli_index  # noqa: F401  — registers index/graph commands
import jsat._cli_launchers  # noqa: F401  — registers launcher commands
import jsat._cli_setup  # noqa: F401  — registers setup/config commands
import jsat._cli_skills_data  # noqa: F401  — registers _JSAT_SKILLS
import jsat._cli_tools  # noqa: F401  — registers tool commands
from jsat._cli_common import app  # noqa: F401


def main() -> None:
    """Console-script entry point — wraps `app()` in the crash net.

    Genuine crashes are recorded (JSAT-internal detail only) so `jsat improve` can
    propose a fix, then re-raised unchanged so behaviour is identical.

    `SystemExit`, `KeyboardInterrupt` and click's `Exit`/`Abort` are normal control
    flow — every `typer.Exit(1)` for an ordinary user error raises `SystemExit`, so
    recording them would bury real defects under routine non-zero exits.
    """
    try:
        app()
    except (SystemExit, KeyboardInterrupt):
        raise
    except BaseException as e:
        if type(e).__name__ not in ("Exit", "Abort"):
            try:
                from jsat._improve import record_signal
                record_signal(kind="crash", source="cli", exc=e, op="main")
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()
