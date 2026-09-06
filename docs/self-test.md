# Self-test

`./scripts/jsat-selftest.sh` verifies the **installed** JSAT end to end with
nothing mocked. It exists because the unit suite cannot catch a whole class of
failure: code that type-checks, passes 800+ tests, reads correctly, and does
not work when actually invoked.

Every defect fixed in 0.4.17 was found this way, and several were invisible in
the worst possible manner — a confident empty answer rather than an error. An
export that produced a valid, readable, *empty* archive while its manifest
reported the true node count. A security scan that examined zero files and
reported no findings. Two MCP tools that called a method existing on no
backend, behind a `# type: ignore` that had silenced the warning.

## Running it

```bash
./scripts/jsat-selftest.sh                  # everything available here, no LLM cost
./scripts/jsat-selftest.sh --ci-safe        # no docker, no LLM, no external services
./scripts/jsat-selftest.sh --llm            # also make real AI provider calls
./scripts/jsat-selftest.sh --live-agent     # also drive a real headless `claude -p`
./scripts/jsat-selftest.sh --full           # pytest with no marker filter
./scripts/jsat-selftest.sh --suite mcp,cli  # just these suites
./scripts/jsat-selftest.sh --jobs 8         # up to 8 suites concurrently (default 4)
./scripts/jsat-selftest.sh --sequential     # one suite at a time, in-process
./scripts/jsat-selftest.sh --list-suites
./scripts/jsat-selftest.sh --out /tmp/report
```

It writes a JSON report and a Markdown companion, both structured for an AI
agent to triage.

### Parallel by default

Suites run **concurrently by default**: each suite executes in its own
subprocess with a private workspace (`tmp/ws-<suite>`; its own
`JSAT_DATA_DIR` / `JSAT_SESSIONS_DIR` / `JSAT_IMPROVE_DIR` / `JSAT_RUNTIME_DIR`)
under the shared tempdir. That isolation is what makes this safe — suites
share only the read-only fixture repo and the parent's base environment, so the
suites that mutate `os.environ` for their in-process SDK calls and the
dashboard's fixed port are never in each other's way. The parent merges the
per-suite reports in `SUITES` order, so the report is deterministic and the
wall time is roughly `max(suite)` rather than `sum(suite)`. `--jobs N` bounds
concurrency (default 4 — match your core count); `--sequential` restores the
old in-process one-suite-at-a-time run, which is the mode to debug a suite in.
The `environment` suite, the fixture-repo build and the final state-leak check
always run on the parent, before and after the pool.

## What it covers

| Suite | What it drives |
|---|---|
| `environment` | Real probes for every CLI, module, service and credential; verifies the binary serves this checkout rather than a stale copy |
| `catalog` | Registries, docs and versions in sync — every slash command's `jsat__*` references resolve, every tool has a role, every documented CLI command exists |
| `index` | All seven parsers against a real multi-language fixture, incremental skip/pickup, `INDEX.md`, export→import round trip, zip-slip guard |
| `mcp` | **All 70 MCP tools** over real stdio JSON-RPC |
| `reliability` | Soft-budget progress notifications, the depth cap, bad-token rejection, RBAC scope |
| `cli` | **All 45 CLI commands**, including a real process kill and SARIF output |
| `connect` | All seven connectors round-tripped against seeded configs |
| `sdk` | Every public SDK method, in-process |
| `providers` | All nine AI providers |
| `improve` | The self-improvement privacy invariant, verified independently |
| `backends` | SQLite, LightGraph, Neo4j, and the memory/disk/redis caches |
| `dashboard` | The live dashboard, its SSE stream, and Prometheus metrics |
| `packaging` | Build, `twine check`, wheel contents, and a **clean-venv install of the wheel** |
| `pytest` | Delegates to `local_test.sh` |
| `live` | A real headless agent through the real `/jsat` dispatcher (opt-in; costs tokens) |

## Three properties worth knowing

**Coverage gates.** Adding an MCP tool, a CLI command, or a public SDK method
turns the suite red until it is actually exercised. That is deliberate — cover
it in the same change.

**Only third-party binaries are ever substituted.** Launcher and lifecycle
checks put a recorder stub on `PATH` in place of `claude`/`codex`/… and then
assert against the real argv and the real generated `--mcp-config`, because
"did we invoke claude correctly" cannot be observed without a TTY otherwise.
No JSAT code is stubbed anywhere.

**`unavailable` is not `fail`.** A dependency that genuinely is not on the
machine — Ollama, docker, an API key, a CLI — is reported `unavailable` with a
remediation. It is never a failure and never a silent skip. Assertions are
kept tight enough that a broken tool cannot pass as an empty result: several
real bugs had been hiding behind a lenient "did it return something?" check.

## Interpreting a report

```
✅ 240 passed   ❌ 0 failed   ⚠️  9 unavailable   (249 checks, 1520s)
```

- **failed** — a real defect. The report carries the failing detail and a
  remediation.
- **unavailable** — an absent dependency, with what to install. Expected on any
  machine that does not have all of Ollama, docker, both API keys and all four
  CLIs.
- A run with **zero failures** and every `unavailable` explained is the release
  bar, alongside `local_test.sh --all`, `mkdocs build --strict`, and a wheel
  that installs clean into a fresh virtualenv.

## Extending it

Suites live in `scripts/selftest/suites/`. Add a `Check` returning
`pass`/`fail`/`unavailable`, and register it in that suite's `run()`. The
fixture repo is built by `scripts/selftest/fixtures.py` — its
`scratch_facts()` holds the ground truth assertions compare against, so a
fixture change that invalidates an assertion is a one-file edit.
