#!/usr/bin/env python3
"""
jsat_selftest.py — entry point for the no-mocking JSAT self-test.

The suites live in `scripts/selftest/`; this file stays as the documented
entry point so `scripts/jsat-selftest.sh`, AGENTS.md and the README keep
working. Run `python3 scripts/jsat_selftest.py --help` for the options, or
`--list-suites` to see what can be run in isolation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from selftest.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
