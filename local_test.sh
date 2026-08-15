#!/usr/bin/env bash
# local_test.sh — configure and run the JSAT test suite locally.
#
# Usage:
#   ./local_test.sh            # lint + CI-safe tests (fast, no external services)
#   ./local_test.sh --all      # every test (needs Neo4j, Qdrant, Redis)
#   ./local_test.sh --lint     # lint only (identical command to CI)
#   ./local_test.sh --fix      # auto-fix lint errors
#   ./local_test.sh --install  # set the environment up, then run
#   ./local_test.sh --doctor   # check the environment without running tests
#   ./local_test.sh --both     # run the suite in every venv that has jsat
#   ./local_test.sh --watch    # re-run on file change (requires entr)

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET} $*"; }
err()  { echo -e "${RED}✗${RESET} $*"; }
info() { echo -e "${CYAN}→${RESET} $*"; }
hr()   { echo -e "${CYAN}──────────────────────────────────────────${RESET}"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# ── Parse args ────────────────────────────────────────────────────────────────
RUN_ALL=false
LINT_ONLY=false
AUTO_FIX=false
INSTALL=false
WATCH=false
DOCTOR=false
BOTH=false

for arg in "$@"; do
  case $arg in
    --all)     RUN_ALL=true ;;
    --lint)    LINT_ONLY=true ;;
    --fix)     AUTO_FIX=true ;;
    --install) INSTALL=true ;;
    --doctor)  DOCTOR=true ;;
    --both)    BOTH=true ;;
    --watch)   WATCH=true ;;
    --no-watch) WATCH=false ;;   # used internally by watch mode re-invocation
    --help|-h)
      sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) err "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ── Find interpreters that have jsat ──────────────────────────────────────────
# Prefer this repo's own venv, then the active one, then anything on PATH.
# Every candidate must import jsat, or the tests are meaningless.
CANDIDATES=()
[[ -x "$REPO_ROOT/.jsat.venv/bin/python" ]] && CANDIDATES+=("$REPO_ROOT/.jsat.venv/bin/python")
[[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]] && CANDIDATES+=("$VIRTUAL_ENV/bin/python")
[[ -x "$HOME/.venv/bin/python" ]] && CANDIDATES+=("$HOME/.venv/bin/python")
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  command -v "$c" &>/dev/null && CANDIDATES+=("$(command -v "$c")")
done

PYTHONS=()
SEEN_PREFIXES=""
for candidate in "${CANDIDATES[@]}"; do
  ver=$("$candidate" -c 'import sys;v=sys.version_info;print(v[0]*100+v[1])' 2>/dev/null || echo 0)
  [[ "$ver" -ge 310 ]] || continue
  "$candidate" -c 'import jsat' &>/dev/null || continue
  # Dedupe by sys.prefix, not path: bin/python and bin/python3 are one environment.
  prefix=$("$candidate" -c 'import sys;print(sys.prefix)' 2>/dev/null || echo "$candidate")
  [[ " $SEEN_PREFIXES " == *" $prefix "* ]] && continue
  SEEN_PREFIXES="$SEEN_PREFIXES $prefix"
  PYTHONS+=("$candidate")
done

if [[ ${#PYTHONS[@]} -eq 0 ]]; then
  if $INSTALL; then
    PYTHONS=("${CANDIDATES[0]}")   # nothing has jsat yet; --install will fix that
  else
    err "No Python 3.10+ with jsat installed."
    echo "   Set one up:  ./local_test.sh --install"
    exit 1
  fi
fi

PYTHON="${PYTHONS[0]}"

# ── Environment checks ────────────────────────────────────────────────────────
# These exist because two real bugs cost hours: a stale non-editable copy
# shadowing the repo, and two venvs on different typer versions (typer 0.27
# vendors click, so `jsat connect <unknown>` broke only where the CLI ran).
check_env() {
  local py="$1" label="$2" problems=0

  local ver src
  ver=$("$py" -c 'import importlib.metadata as m;print(m.version("jsat"))' 2>/dev/null || echo "?")
  # MUST run from a neutral directory. `python -c` puts cwd on sys.path[0], so running
  # this from the repo root makes ./jsat shadow site-packages and a plain copied
  # install looks editable. Console scripts do NOT get cwd on the path, which is how a
  # stale copy can silently serve the `jsat` binary while every check here says fine.
  src=$(cd /tmp && "$py" -c 'import jsat,pathlib;print(pathlib.Path(jsat.__file__).resolve().parent)' 2>/dev/null || echo "?")

  echo -e "  ${BOLD}$label${RESET}"
  echo "    jsat     $ver"
  echo "    loaded   $src"

  if [[ "$src" != "$REPO_ROOT/jsat" ]]; then
    warn "    not running this checkout — a stale copy is shadowing it"
    echo "      fix: $py -m pip install -e ."
    problems=1
  else
    ok "    editable — running this checkout"
  fi

  local declared
  declared=$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)"/\1/')
  if [[ "$ver" != "$declared" && "$ver" != "?" ]]; then
    warn "    installed $ver but pyproject declares $declared — reinstall"
    problems=1
  fi

  for pkg in typer click rich pydantic; do
    printf "    %-9s%s\n" "$pkg" \
      "$("$py" -c "import importlib.metadata as m;print(m.version('$pkg'))" 2>/dev/null || echo '-')"
  done
  return $problems
}

# Any two environments that disagree on typer/click will disagree on CLI behaviour.
check_drift() {
  [[ ${#PYTHONS[@]} -lt 2 ]] && return 0
  local base_sig="" sig
  for py in "${PYTHONS[@]}"; do
    sig=$("$py" -c "
import importlib.metadata as m
print(','.join(m.version(p) for p in ('typer','click')))" 2>/dev/null || echo "?")
    if [[ -z "$base_sig" ]]; then base_sig="$sig"
    elif [[ "$sig" != "$base_sig" ]]; then
      warn "Version drift between environments: typer/click $base_sig vs $sig"
      echo "   The CLI behaves differently across these — align them:"
      echo "     $py -m pip install 'typer==${base_sig%%,*}' 'click==${base_sig##*,}'"
      return 1
    fi
  done
  ok "All environments agree on typer/click ($base_sig)"
}

if $DOCTOR; then
  hr; echo -e "${BOLD}JSAT environment${RESET}"; hr
  status=0
  for py in "${PYTHONS[@]}"; do check_env "$py" "$py" || status=1; echo; done
  check_drift || status=1
  hr
  [[ $status -eq 0 ]] && ok "Environment looks good" || warn "Environment needs attention (above)"
  exit $status
fi

# ── Install / configure ───────────────────────────────────────────────────────
if $INSTALL; then
  hr; info "Configuring environment(s)..."
  for py in "${PYTHONS[@]}"; do
    info "  $py"
    "$py" -m pip install -e . -q
    "$py" -m pip install pytest pytest-asyncio ruff mypy -q
  done
  ok "Dependencies installed (editable)"
fi

if ! "$PYTHON" -m pytest --version &>/dev/null; then
  warn "pytest not found — installing..."
  "$PYTHON" -m pip install pytest pytest-asyncio -q
fi

# ── Lint ──────────────────────────────────────────────────────────────────────
# No inline rule list — ruff reads [tool.ruff] from pyproject.toml, and CI runs
# the identical command. One source of truth, so green here means green there.
CI_RUFF_ARGS=(jsat/ tests/)

run_lint() {
  hr
  info "Running ruff (same command as CI)..."
  if $AUTO_FIX; then
    "$PYTHON" -m ruff check "${CI_RUFF_ARGS[@]}" --fix
    ok "Lint errors auto-fixed"
  elif "$PYTHON" -m ruff check "${CI_RUFF_ARGS[@]}"; then
    ok "Lint passed (same rules as CI)"
  else
    err "Lint failed — run ./local_test.sh --fix"
    return 1
  fi
}

if $LINT_ONLY || $AUTO_FIX; then
  run_lint
  exit $?
fi

# ── Watch mode ────────────────────────────────────────────────────────────────
if $WATCH; then
  command -v entr &>/dev/null || { err "'entr' not found. Install: apt install entr"; exit 1; }
  info "Watching jsat/ and tests/ ... (Ctrl+C to stop)"
  find jsat/ tests/ -name '*.py' | entr -c bash "$0" --no-watch
  exit 0
fi

# ── Tests ─────────────────────────────────────────────────────────────────────
hr; echo -e "${BOLD}JSAT Local Test Runner${RESET}"; hr
START=$(date +%s)

if $RUN_ALL; then
  info "Running ALL tests (integration included)"
  warn "Integration tests require Neo4j, Qdrant, Redis"
  PYTEST_ARGS=(--tb=short -q)
else
  info "Running CI-safe tests (no external services)"
  PYTEST_ARGS=(-m ci --tb=short -q)
fi

for py in "${PYTHONS[@]}"; do
  check_env "$py" "$py" || true
  echo
  $BOTH || break
done
check_drift || true

if ! run_lint; then exit 1; fi

RUN_ON=("$PYTHON")
$BOTH && RUN_ON=("${PYTHONS[@]}")

FAILED=0
for py in "${RUN_ON[@]}"; do
  hr; info "pytest — $py"; echo
  # Isolate improve/session state so a local run never touches real user data.
  if ! JSAT_IMPROVE_DIR="$(mktemp -d)" JSAT_SESSIONS_DIR="$(mktemp -d)" \
       "$py" -m pytest "${PYTEST_ARGS[@]}"; then
    FAILED=1
  fi
done

ELAPSED=$(( $(date +%s) - START ))
hr
if [[ $FAILED -eq 0 ]]; then
  ok "${BOLD}All tests passed${RESET} in ${ELAPSED}s"
  echo
  echo -e "  ${CYAN}Full suite:${RESET}   ./local_test.sh --all"
  echo -e "  ${CYAN}Every venv:${RESET}   ./local_test.sh --both"
  echo -e "  ${CYAN}Environment:${RESET}  ./local_test.sh --doctor"
  echo
else
  err "${BOLD}Tests failed${RESET} after ${ELAPSED}s"
  echo
  echo -e "  ${YELLOW}Re-run verbosely:${RESET} $PYTHON -m pytest ${PYTEST_ARGS[*]} -v"
  echo
  exit 1
fi
