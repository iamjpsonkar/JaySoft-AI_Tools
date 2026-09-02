#!/usr/bin/env bash
# jsat-selftest.sh — run the full, no-mocking self-test of the installed jsat.
#
# Thin wrapper: picks a Python that actually has jsat installed (same
# discovery logic as local_test.sh) and execs scripts/jsat_selftest.py with
# whatever args you pass through.
#
# Usage:
#   ./scripts/jsat-selftest.sh              # full run
#   ./scripts/jsat-selftest.sh --quick      # skip the heavy --all pytest pass
#   ./scripts/jsat-selftest.sh --full       # also run local_test.sh --all
#   ./scripts/jsat-selftest.sh --out /tmp/x # custom report path prefix

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON=""
for candidate in "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/.jsat.venv/bin/python" \
                 "${VIRTUAL_ENV:-}/bin/python" \
                 python3.13 python3.12 python3.11 python3.10 python3; do
  [[ -z "$candidate" ]] && continue
  path=$(command -v "$candidate" 2>/dev/null || true)
  [[ -z "$path" ]] && continue
  "$path" -c 'import jsat' &>/dev/null || continue
  PYTHON="$path"
  break
done

if [[ -z "$PYTHON" ]]; then
  echo "✗ No Python with jsat installed found. Run: pip install -e . (from $REPO_ROOT)" >&2
  exit 1
fi

exec "$PYTHON" "$REPO_ROOT/scripts/jsat_selftest.py" "$@"
