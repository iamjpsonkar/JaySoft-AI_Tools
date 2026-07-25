#!/usr/bin/env bash
# local_test.sh — Run JSAT tests locally
# Usage:
#   ./local_test.sh           # CI-safe tests only (fast, no external services)
#   ./local_test.sh --all     # all tests (requires Neo4j, Qdrant, Redis)
#   ./local_test.sh --lint    # lint only (ruff)
#   ./local_test.sh --fix     # auto-fix lint errors
#   ./local_test.sh --install # install deps before running tests
#   ./local_test.sh --watch   # re-run on file changes (requires entr)

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET} $*"; }
err()  { echo -e "${RED}✗${RESET} $*"; }
info() { echo -e "${CYAN}→${RESET} $*"; }
hr()   { echo -e "${CYAN}──────────────────────────────────────────${RESET}"; }

# ── Parse args ────────────────────────────────────────────────────────────────
RUN_ALL=false
LINT_ONLY=false
AUTO_FIX=false
INSTALL=false
WATCH=false

for arg in "$@"; do
  case $arg in
    --all)     RUN_ALL=true ;;
    --lint)    LINT_ONLY=true ;;
    --fix)     AUTO_FIX=true ;;
    --install) INSTALL=true ;;
    --watch)   WATCH=true ;;
    --help|-h)
      echo "Usage: ./local_test.sh [--all] [--lint] [--fix] [--install] [--watch]"
      echo ""
      echo "  (no flags)  Run CI-safe tests (fast, no external services needed)"
      echo "  --all       Run all tests including integration (needs Neo4j/Qdrant/Redis)"
      echo "  --lint      Run ruff lint only"
      echo "  --fix       Auto-fix ruff lint errors"
      echo "  --install   Install/upgrade dependencies before running"
      echo "  --watch     Re-run on file change (requires: brew install entr)"
      exit 0 ;;
    *) err "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ── Find Python ───────────────────────────────────────────────────────────────
PYTHON=""

# Prefer a Python that already has jsat installed (correct environment)
for candidate in \
    "$HOME/.pyenv/shims/python3" \
    "$HOME/.pyenv/versions/3.12.0/bin/python3" \
    "$HOME/.pyenv/versions/3.11.0/bin/python3" \
    "$HOME/.pyenv/versions/3.10.0/bin/python3" \
    "/opt/homebrew/anaconda3/envs/.jsat.venv/bin/python3" \
    python3.12 python3.11 python3.10 python3 \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3"; do
  if command -v "$candidate" &>/dev/null || [[ -x "$candidate" ]]; then
    version=$("$candidate" -c "import sys; v=sys.version_info; print(v[0]*100+v[1])" 2>/dev/null || echo 0)
    if [[ "$version" -ge 310 ]]; then
      # Prefer Python that has jsat installed
      if "$candidate" -c "import jsat" &>/dev/null; then
        PYTHON="$candidate"
        break
      elif [[ -z "$PYTHON" ]]; then
        PYTHON="$candidate"   # fallback to first valid Python >= 3.10
      fi
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  err "Python 3.10+ not found. Install via pyenv or homebrew."
  exit 1
fi

PYTHON_VERSION=$("$PYTHON" --version 2>&1)
ok "Using $PYTHON_VERSION"

# ── Install deps ──────────────────────────────────────────────────────────────
if $INSTALL; then
  hr
  info "Installing dependencies..."
  "$PYTHON" -m pip install -e "." -q
  "$PYTHON" -m pip install pytest pytest-asyncio ruff -q
  ok "Dependencies installed"
fi

# Ensure pytest is available
if ! "$PYTHON" -m pytest --version &>/dev/null; then
  warn "pytest not found — installing..."
  "$PYTHON" -m pip install pytest pytest-asyncio -q
fi

# ── Lint ──────────────────────────────────────────────────────────────────────
run_lint() {
  hr
  info "Running ruff lint..."
  RUFF_ARGS="jsat/ --select E,F,I --ignore E501,E402,E701,E702,E741,F841,F401"
  if $AUTO_FIX; then
    "$PYTHON" -m ruff check $RUFF_ARGS --fix
    ok "Lint errors auto-fixed"
  else
    if "$PYTHON" -m ruff check $RUFF_ARGS; then
      ok "Lint passed"
    else
      err "Lint failed — run ./local_test.sh --fix to auto-fix"
      return 1
    fi
  fi
}

if $LINT_ONLY || $AUTO_FIX; then
  run_lint
  exit $?
fi

# ── Watch mode ────────────────────────────────────────────────────────────────
if $WATCH; then
  if ! command -v entr &>/dev/null; then
    err "'entr' not found. Install: brew install entr"
    exit 1
  fi
  info "Watching for changes... (Ctrl+C to stop)"
  find jsat/ tests/ -name "*.py" | entr -c bash "$0" "$@" --no-watch 2>/dev/null || true
  exit 0
fi

# ── Tests ─────────────────────────────────────────────────────────────────────
hr
echo -e "${BOLD}JSAT Local Test Runner${RESET}"
hr

START=$(date +%s)

if $RUN_ALL; then
  info "Running ALL tests (including integration)..."
  warn "Integration tests require: Neo4j, Qdrant, Redis"
  PYTEST_ARGS="-v --tb=short"
else
  info "Running CI-safe tests only (no external services needed)..."
  PYTEST_ARGS="-m ci --tb=short -q"
fi

# Run lint first (fast fail)
if ! run_lint; then
  exit 1
fi

hr
info "Running pytest..."
echo ""

if "$PYTHON" -m pytest $PYTEST_ARGS; then
  END=$(date +%s)
  ELAPSED=$((END - START))
  hr
  ok "${BOLD}All tests passed${RESET} in ${ELAPSED}s"
  echo ""
  echo -e "  ${CYAN}Full suite:${RESET}   ./local_test.sh --all"
  echo -e "  ${CYAN}Auto-fix:${RESET}     ./local_test.sh --fix"
  echo -e "  ${CYAN}Watch mode:${RESET}   ./local_test.sh --watch"
  echo ""
else
  END=$(date +%s)
  ELAPSED=$((END - START))
  hr
  err "${BOLD}Tests failed${RESET} after ${ELAPSED}s"
  echo ""
  echo -e "  ${YELLOW}Run with -v for full output:${RESET}"
  echo -e "  $PYTHON -m pytest $PYTEST_ARGS -v"
  echo ""
  exit 1
fi
