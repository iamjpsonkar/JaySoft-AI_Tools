"""
jsat.cli — CLI entrypoint: imports sub-modules to register all commands.

All commands are defined in the _cli_* sub-modules. This file only wires
them together so `jsat` resolves to the right Typer app.
"""
from __future__ import annotations

from jsat._cli_common import app  # noqa: F401
import jsat._cli_skills_data   # noqa: F401  — registers _JSAT_SKILLS
import jsat._cli_launchers     # noqa: F401  — registers launcher commands
import jsat._cli_connect       # noqa: F401  — registers connect subcommands
import jsat._cli_ai            # noqa: F401  — registers ai subcommands
import jsat._cli_tools         # noqa: F401  — registers tool commands
import jsat._cli_index         # noqa: F401  — registers index/graph commands
import jsat._cli_setup         # noqa: F401  — registers setup/config commands


def main() -> None:
    app()


if __name__ == "__main__":
    main()
