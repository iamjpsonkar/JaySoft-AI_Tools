---
description: Show flags, params, and examples for any /jsat command. Usage: /jsat-help <command>
---

Parse $ARGUMENTS:
- First word = COMMAND (e.g. `magic`, `crack`, `blast-radius`)
- Everything after = ignored

If $ARGUMENTS is empty: print the **Full Command List** table at the bottom of this file and stop.

Otherwise find the matching `### <COMMAND>` section below and print its help block verbatim.
Format the output as:

```
/jsat <COMMAND> [flags] <args>

<one-line description>

Flags:
  <flag>  —  <what it does>
  ...

Examples:
  <example>
  ...
```

If COMMAND is not found: print `Unknown command: <COMMAND>` and show the Full Command List.

---

### universal-flags
Two flags work on EVERY /jsat command. Extract them from ARGS before routing to the subcommand,
then pass as tool call arguments (_budget=N, _dashboard=True).
```
Universal flags (any command):
  timeout=<N>     → soft time budget in seconds (notification-only; hard kill at 5×N)
  dashboard=true  → open a real-time browser dashboard for this call

How they work:
  timeout=<N>
    • After N seconds: ⏱ progress notification sent to AI (tool still running)
    • After 5×N seconds: ⛔ force-killed (hard limit)
    • Default budgets vary per tool (blast_radius: 30s, crack: 55s, query: 45s, …)
    • Pass as _budget=N in the tool call: jsat__crack(task='...', _budget=300)

  dashboard=true
    • Starts a local HTTP server at http://localhost:7432 (or JSAT_DASHBOARD_PORT)
    • Opens the browser automatically
    • Streams all events in real time: start, progress, checkpoints, over-budget warnings, result, done
    • Server closes 10 s after the call completes (clears on the next dashboard=true call)
    • Pass as _dashboard=True in the tool call: jsat__crack(task='...', _dashboard=True)

Examples:
  /jsat crack timeout=300 redesign the payment retry system
    → jsat__crack(task='redesign the payment retry system', _budget=300)

  /jsat blast-radius dashboard=true src/payment/
    → jsat__blast_radius(target='src/payment/', _dashboard=True)

  /jsat magic timeout=180 dashboard=true --service payments investigate the auth flow
    → jsat__query(…, _budget=180, _dashboard=True)  (and all sub-calls inherit budget)
```

---

### aw
Workflow advisor — classifies your task and runs the optimal tool sequence end-to-end.
```
/jsat aw [--type <type>] [--dry] <task>

Flags:
  --type feature|bugfix|security|understand|incident|refactor|review
                  skip classification, force a specific workflow
  --dry           show the workflow plan without running any tools

Examples:
  /jsat aw add idempotency keys to the payment mutation
  /jsat aw --type security src/auth/
  /jsat aw --dry investigate the checkout 500 errors
```

### blast-radius
Trace downstream impact of a change. Severity-ranked: breaking → degraded → warning → safe.
```
/jsat blast-radius [--file|--diff|--symbol] [--severity <lvl>] <target>

Flags:
  --file <path>      blast radius for a file
  --diff <diff>      blast radius from a raw git diff
  --symbol <name>    blast radius for a single symbol
  --severity breaking|degraded|warning|safe   filter output to one level
  (no flag)          auto-detect from target

Examples:
  /jsat blast-radius src/payment/service.py
  /jsat blast-radius --symbol PaymentService.process
  /jsat blast-radius --severity breaking jsat/cli.py
```

### cohesion
File and function cohesion analysis — flags oversized files, high complexity, mixed responsibilities.
```
/jsat cohesion [--service <name>] [--threshold <N>] [--functions]

Flags:
  --service <name>    scope to one service
  --threshold <N>     flag files with more than N lines (default: 800)
  --functions         show function-level analysis only

Examples:
  /jsat cohesion
  /jsat cohesion --threshold 600
  /jsat cohesion --service PaymentService --functions
```

### contract
Check API contract compatibility between branches.
```
/jsat contract [<base> <head>] [--score] [--breaking]

Flags:
  <base> <head>   branches to diff (default: main HEAD)
  --score         show only the numeric compatibility score (0-100)
  --breaking      show breaking changes only

Examples:
  /jsat contract
  /jsat contract main feature/new-payments
  /jsat contract --breaking
```

### coverage
Behavioral test coverage estimate. Optionally generate missing tests.
```
/jsat coverage [--generate] [--service <name>] [--limit N] <path>

Flags:
  --generate          generate unit tests for top uncovered paths
  --service <name>    scope to one service (avoids timeout)
  --limit N           show only top N uncovered paths

Examples:
  /jsat coverage src/payment/
  /jsat coverage --generate --limit 5 src/payment/
  /jsat coverage --service PaymentService
```

### crack
Multi-agent war room — architect → security → implementer → tester → skeptic → moderator.
```
/jsat crack [--phases N] [--single] [--continue] <task>

Flags:
  --phases N    run in N phases: 2-6 (default: 6, one agent per phase)
  --single      run all agents at once (may timeout on complex tasks)
  --continue    resume the most recent in_progress crack session

Phase splits:
  N=2  [arch+sec+impl] / [tester+skeptic+mod]
  N=3  [arch+sec] / [impl+tester] / [skeptic+mod]
  N=6  one agent per phase (default, maximum granularity)

Examples:
  /jsat crack redesign the payment retry system
  /jsat crack --phases 3 add rate limiting to checkout
  /jsat crack --continue
```

### decide
Architectural decision journal. Log decisions; retrieve by file, topic, or blast-radius context.
```
/jsat decide [log [--impact h|m|l]] | [list [<category>]] | [search <query>] | [context <file>]

Subcommands:
  log <text>                  store a decision
  log --impact h|m|l <text>   store with impact rating (high/medium/low)
  list                        show all decisions (recent first)
  list <category>             filter by category
  search <query>              semantic search across decisions
  context <file_or_symbol>    decisions relevant to this file

Examples:
  /jsat decide log --impact h Chose PostgreSQL for ACID compliance on payments
  /jsat decide list
  /jsat decide search caching strategy
  /jsat decide context src/payments/service.py
```

### doctor
Full JSAT system health check.
```
/jsat doctor

No flags. Checks: version, graph backend, AI provider, MCP tools loaded, config profile.

Examples:
  /jsat doctor
```

### find-class
Find a class in the indexed codebase.
```
/jsat find-class [--service <name>] <ClassName>

Flags:
  --service <name>   scope search to one service

Examples:
  /jsat find-class PaymentService
  /jsat find-class --service payments RefundProcessor
```

### find-function
Find a function or method in the indexed codebase.
```
/jsat find-function [--service <name>] <function_name>

Flags:
  --service <name>   scope search to one service

Examples:
  /jsat find-function process_refund
  /jsat find-function --service payments validate_cart
```

### incident
Investigate a production incident with ranked root-cause hypotheses.
```
/jsat incident [hypotheses|recent [path]|runbook <svc>] [--since <time>] [--service <name>] <description>

Subcommands:
  hypotheses          list ranked root-cause hypotheses (after a previous investigation)
  recent [path]       show recent commits in an area
  runbook <svc>       generate an incident runbook

Flags:
  --since 24h|7d      limit commit search window
  --service <name>    scope to one service

Examples:
  /jsat incident 500 errors spiking on checkout since 14:00
  /jsat incident hypotheses
  /jsat incident recent src/payment/
  /jsat incident runbook PaymentService
```

### index
Build or refresh the JSAT codebase graph index.
```
/jsat index [--force] [--languages X,Y] <path>

Flags:
  --force            full re-index (ignores incremental cache)
  --languages X,Y    limit to specific languages (python, go, js, ...)
  (no flag)          incremental index of path (default: .)

Examples:
  /jsat index .
  /jsat index src/ --force
  /jsat index . --languages python,go
```

### ithinking
IThinking meta-cognitive reasoning — plan before acting, reflect after.
```
/jsat ithinking [plan|reflect|audit|execute|estimate] <task>

Subcommands:
  plan <task>       clarify intent, check assumptions, decompose work (default)
  reflect <done>    log what was done and what was learned
  audit <task>      audit assumptions before starting
  execute <plan>    execute a plan step
  estimate <task>   token/complexity estimate for a task

Examples:
  /jsat ithinking refactor the payment retry logic
  /jsat ithinking reflect completed PaymentService.process() refactor
  /jsat ithinking audit migrate users table to add nullable column
```

### knowledge
Query or manage the JSAT knowledge base.
```
/jsat knowledge [add [--category <cat>] | list [<cat>] | search <query> | stale <id>] <query>

Subcommands:
  add <text>                   store a note
  add --category <cat> <text>  store with category: adr|runbook|pattern|decision
  list                         show all entries
  list <category>              filter by category
  search <query>               semantic search
  stale <id>                   flag entry as potentially outdated
  (no subcommand)              semantic query (same as search)

Examples:
  /jsat knowledge what are the payment ADRs?
  /jsat knowledge add --category adr Payments require idempotency keys
  /jsat knowledge list adr
  /jsat knowledge search retry patterns
```

### knowledge-add
Add a single entry to the knowledge base.
```
/jsat knowledge-add [--category <cat>] <text>

Flags:
  --category adr|runbook|pattern|decision|context

Examples:
  /jsat knowledge-add Use tenancy for retry logic per ADR-007
  /jsat knowledge-add --category adr All payment mutations require idempotency keys
```

### lazy
Reuse-first code planning — checks the graph for existing implementations before suggesting new code.
```
/jsat lazy [--audit] [--review] <task>

Flags:
  --audit    scan a diff/file for code that reimplements existing functionality
  --review   check a proposed implementation for duplication
  (no flag)  run the 5-rung reuse ladder for the task

Reuse ladder: exact match → similar pattern → existing service → existing endpoint → minimal new code

Examples:
  /jsat lazy add a retry wrapper for HTTP calls
  /jsat lazy --audit src/payment/retry.py
  /jsat lazy --review add idempotency key validation
```

### list-endpoints
List all API endpoints found in the indexed codebase.
```
/jsat list-endpoints [--service <name>] [--method <METHOD>]

Flags:
  --service <name>    filter to one service
  --method GET|POST|PUT|PATCH|DELETE   filter by HTTP method

Examples:
  /jsat list-endpoints
  /jsat list-endpoints --service payment
  /jsat list-endpoints --method POST
```

### list-services
List all services found in the indexed codebase.
```
/jsat list-services [--language <lang>]

Flags:
  --language python|go|javascript|java|ruby|rust

Examples:
  /jsat list-services
  /jsat list-services --language python
```

### magic
AI-orchestrated skill composer — selects and runs the optimal JSAT skills for any task.
```
/jsat magic [--depth quick|standard|deep] [--budget N] [--service <name>] [--preview] [--continue] <task>

Flags:
  --depth quick       cap at 4 skills (fast, breadth-first)
  --depth standard    cap at 8 skills (default, balanced)
  --depth deep        cap at 15 skills (comprehensive)
  --budget N          explicit skill invocation cap
  --service <name>    scope all skills to one service (avoids timeout)
  --preview           compose plan only, do NOT run any skills
  --continue          resume the most recent in_progress magic session

Examples:
  /jsat magic improve the payment retry logic
  /jsat magic --depth deep analyze and fix the auth flow
  /jsat magic --preview what would you do to refactor the checkout service?
  /jsat magic --continue
```

### migration
Validate a database migration file for lock type, duration, and zero-downtime safety.
```
/jsat migration [--rows <table:N>] <path>

Flags:
  --rows <table:N>   hint row count for lock duration estimation
                     e.g. --rows orders:5000000

Examples:
  /jsat migration db/migrations/0042_add_index.sql
  /jsat migration --rows orders:5000000 db/migrations/0042.sql
```

### plan
Pre-implementation planning gate — six forcing questions + scope/architecture/security review.
```
/jsat plan [--scope] [--architecture] [--security] [--full] <task>

Flags:
  --scope          scope review only (what to build and why)
  --architecture   architecture review (how to build it)
  --security       security review (what can go wrong)
  --full           all three perspectives (default)

Examples:
  /jsat plan add idempotency keys to the payment mutation
  /jsat plan --security add a new admin endpoint
  /jsat plan --scope implement a refund retry mechanism
```

### prompt
Discuss → Plan → Execute → Verify → Synthesize pipeline for any codebase question.
```
/jsat prompt [--rewrite|--agents] [--diff] [--optimize-only] [--phases N] [--service <name>] [--single] [--continue] <query>

Flags:
  --rewrite         Phase 1: single LLM agent rewrite
  --agents          Phase 1: 3 parallel LLM rewrite agents (best output wins)
  --diff            show raw vs optimized prompt diff after Phase 1
  --optimize-only   stop after Phase 1 optimization
  --phases N        run N phases: 2-6 (default: 6)
  --service <name>  scope all queries to one service
  --single          one-shot mode (optimize → one query call)
  --continue        resume most recent in_progress prompt session

Examples:
  /jsat prompt what calls process_refund and what do they pass?
  /jsat prompt --agents redesign the payment retry system
  /jsat prompt --phases 3 how does the checkout flow work?
  /jsat prompt --continue
```

### prompt-diff
Show what you typed vs what JSAT sent to the AI after optimization.
```
/jsat prompt-diff <query>

No flags. Shows two panels: Raw (what you typed) and Optimized (what was sent).

Examples:
  /jsat prompt-diff improve the retry logic
  /jsat prompt-diff what does the checkout service do?
```

### prompt-rewrite
Rewrite a prompt using 3 parallel LLM agents for maximum clarity.
```
/jsat prompt-rewrite <query>

No flags. Runs: clarity rewrite + context expansion + constraint hardening in parallel.
Shows winning rewrite with agent name and score.

Examples:
  /jsat prompt-rewrite add rate limiting to the checkout API
```

### query
Answer any question about this codebase using the graph index.
```
/jsat query [--service <name>] [--short] <question>

Flags:
  --service <name>   scope answer to one service (reduces context, avoids timeout)
  --short            constrain to ≤3 sentences

Examples:
  /jsat query what does the payment service do?
  /jsat query --service PaymentService how is retry handled?
  /jsat query --short what does process_refund return?
```

### recent
Show recent changes in the codebase.
```
/jsat recent [--since <time>] [--author <name>] [--service <name>] [path]

Flags:
  --since 24h|7d|30d   limit to changes since this window
  --author <name>      filter by commit author (substring match)
  --service <name>     scope to one service's files

Examples:
  /jsat recent
  /jsat recent --since 24h src/payment/
  /jsat recent --author jay
```

### reflect
Record what was done after completing a task (IThinking phase 6 log).
```
/jsat reflect <what was done>

No flags. Logs outcome, what worked, what didn't, follow-up actions.

Examples:
  /jsat reflect completed RBAC fail-closed fix in mcp/server.py
  /jsat reflect split cli.py into 8 focused modules, all tests pass
```

### review
Multi-model code review. Confirms bugs when 2+ models agree.
```
/jsat review [--findings] [--bugs] [--min high|medium] <diff>

Flags:
  --findings    show results of the most recent review (no new review)
  --bugs        show confirmed bugs only (2+ model agreement)
  --min high    filter to high-confidence findings only
  --min medium  filter to medium+ (default)
  (no flag)     submit a diff for review

Examples:
  /jsat review <paste diff here>
  /jsat review --bugs
  /jsat review --findings --min high
```

### runbook
Generate an incident runbook for a service or component.
```
/jsat runbook [sections] <target>

Subcommands:
  sections <target>   show section outline only (no full content)
  (no subcommand)     full runbook with symptoms, diagnosis, rollback, escalation, monitoring

Examples:
  /jsat runbook PaymentService
  /jsat runbook sections PaymentService
```

### security
Security scan — OWASP, secrets, auth gaps, CVEs.
```
/jsat security [--file <path>] [--secrets] [--auth] [--cves] [--severity critical|high] [path]

Flags:
  --file <path>        scan a single file
  --secrets            find hardcoded credentials (key names only, values redacted)
  --auth               show endpoints missing auth middleware
  --cves               check dependencies for CVEs above threshold
  --severity critical  filter to critical only
  --severity high      filter to high+ (default: medium)
  (no flag / path)     full OWASP scan of path

Examples:
  /jsat security
  /jsat security src/payment/
  /jsat security --file src/auth/login.py
  /jsat security --secrets
  /jsat security --cves
```

### short
Ask any question — get the briefest possible correct answer (≤3 sentences).
```
/jsat short [--one-line] <question>

Flags:
  --one-line   constrain to exactly one sentence

Examples:
  /jsat short what does process_refund return?
  /jsat short --one-line where is the retry logic?
```

### smart
Terse compression mode — fragment-based answers, filler stripped, code intact.
```
/jsat smart [--lite|--full|--ultra] <question>

Flags:
  --lite    remove filler phrases only (~30% compression)
  --full    convert to fragments, remove preamble (~55%, default)
  --ultra   one bullet per fact, ≤8 words each (~70% compression)

Examples:
  /jsat smart what does the payment service do?
  /jsat smart --ultra what does process_refund return?
  /jsat smart --lite explain the checkout flow
```

### sprint
Seven-stage delivery workflow — Think → Plan → Build → Review → Test → Ship → Reflect.
```
/jsat sprint [--stage N] [--dry] [--continue] <task>

Flags:
  --stage N     resume from a specific stage (1-7, skips earlier stages)
  --dry         show the sprint plan without running any tools
  --continue    resume the most recent in_progress sprint session

Stages: 1-Think  2-Plan  3-Build  4-Review  5-Test  6-Ship  7-Reflect

Examples:
  /jsat sprint add rate limiting to the checkout API
  /jsat sprint --dry refactor the payment retry system
  /jsat sprint --stage 5 add rate limiting to the checkout API
  /jsat sprint --continue
```

### status
Show JSAT index statistics and health.
```
/jsat status

No flags. Shows: node/edge counts, graph backend, JSAT version, index freshness.

Examples:
  /jsat status
```

### test-gaps
Find untested code paths; optionally generate tests.
```
/jsat test-gaps [--generate] [--integration] [--contract <A> <B>] [--untested] [--service <name>] [path]

Flags:
  --generate               generate unit tests for each gap after finding them
  --integration            generate integration tests (instead of unit)
  --contract <A> <B>       generate a contract test between two services
  --untested               flat list of highest-risk untested paths
  --service <name>         scope to one service (avoids timeout)

Examples:
  /jsat test-gaps src/payment/
  /jsat test-gaps --generate src/payment/
  /jsat test-gaps --untested
  /jsat test-gaps --contract PaymentService RefundService
```

### think
Think carefully before acting — IThinking planning shortcut.
```
/jsat think <task>

No flags. Clarifies intent, checks assumptions, and decomposes the task before proceeding.

Examples:
  /jsat think refactor the payment retry logic
  /jsat think add idempotency keys to all payment mutations
```

### token-budget
Check how much of a model's context window a text uses.
```
/jsat token-budget [--model <name>] <text>

Flags:
  --model claude-sonnet-4-6|gpt-4o|gpt-4o-mini|claude-haiku-4-5   (default: current session model)

Shows: tokens used, limit, % used, headroom. Warns at ≥80%, critical at ≥95%.

Examples:
  /jsat token-budget <paste large context here>
  /jsat token-budget --model gpt-4o <paste context here>
```

### tokens
Count, compress, or check token budget for any text.
```
/jsat tokens [--compress] [--model <name>] <text>

Flags:
  --compress         apply offline compression (dedup, whitespace, import collapse)
  --model <name>     check % of model's context window used

Examples:
  /jsat tokens explain the payment service
  /jsat tokens --compress <paste large context here>
  /jsat tokens --model gpt-4o <paste context here>
```

### trace
Trace a call chain from a symbol through the codebase.
```
/jsat trace [--depth N] [--upstream] <symbol>

Flags:
  --depth N     limit trace depth to N levels
  --upstream    show callers of this symbol (who calls it), not what it calls

Examples:
  /jsat trace PaymentService.process
  /jsat trace --depth 3 PaymentService.process
  /jsat trace --upstream process_refund
```

---

## Full Command List

| Command | One-line description |
|---------|---------------------|
| `aw` | Workflow advisor — classifies task, runs optimal tool sequence end-to-end |
| `blast-radius` | Trace downstream impact of a file/symbol change |
| `cohesion` | Oversized file, high complexity, mixed responsibility analysis |
| `contract` | API contract diff — breaking vs non-breaking changes between branches |
| `coverage` | Behavioral test coverage estimate with optional test generation |
| `crack` | Multi-agent war room: arch → sec → impl → tester → skeptic → mod |
| `decide` | Architectural decision journal — log, search, surface by blast-radius |
| `doctor` | Full JSAT system health check |
| `find-class` | Find a class in the indexed codebase |
| `find-function` | Find a function or method in the indexed codebase |
| `incident` | Investigate a production incident with ranked root-cause hypotheses |
| `index` | Build or refresh the codebase graph index |
| `ithinking` | Meta-cognitive plan/reflect/audit/estimate (IThinking) |
| `knowledge` | Query or manage the JSAT knowledge base |
| `knowledge-add` | Add a single entry to the knowledge base |
| `lazy` | Reuse-first planning — checks graph before suggesting new code |
| `list-endpoints` | List all API endpoints, filterable by service or HTTP method |
| `list-services` | List all services found in the indexed codebase |
| `magic` | AI-orchestrated skill composer — picks and runs the right skills |
| `migration` | Validate DB migration for lock type, duration, zero-downtime safety |
| `plan` | Pre-implementation gate: forcing questions + scope/arch/security review |
| `prompt` | Discuss → Plan → Execute → Verify → Synthesize pipeline |
| `prompt-diff` | Show raw vs optimized prompt diff |
| `prompt-rewrite` | Rewrite prompt with 3 parallel LLM agents |
| `query` | Answer any codebase question using the graph index |
| `recent` | Show recent commits, filterable by time, author, service |
| `reflect` | Log what was done (IThinking phase 6) |
| `review` | Multi-model code review — confirms bugs when 2+ models agree |
| `runbook` | Generate incident runbook for a service or component |
| `security` | OWASP scan, secrets detection, auth gaps, CVE check |
| `short` | Briefest correct answer (≤3 sentences) |
| `smart` | Terse fragment mode — strips filler, preserves code |
| `sprint` | Seven-stage delivery: Think→Plan→Build→Review→Test→Ship→Reflect |
| `status` | Index node/edge counts, graph backend, JSAT version |
| `test-gaps` | Find untested code paths, optionally generate tests |
| `think` | Think and plan before acting (IThinking shortcut) |
| `token-budget` | Check text size against a model's context limit |
| `tokens` | Count, compress, or budget-check tokens |
| `trace` | Trace call chain from a symbol, supports --upstream |

Run `/jsat-help <command>` for flags and examples on any specific command.

BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

