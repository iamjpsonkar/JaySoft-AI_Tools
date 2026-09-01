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

If COMMAND is not an exact match against a `### <COMMAND>` section, do NOT jump
straight to "Unknown command" — a bare miss-list dump is only correct feedback
when the user's input has nothing in common with any real command, and that is
rarely why someone typed the wrong name. Two more likely cases first:

1. RENAMED/MERGED COMMAND: commands get merged or renamed as JSAT evolves. Muscle
   memory for an old name is common and deserves a redirect, not a dead end.
   Maintain this alias table BEFORE falling back to fuzzy match — whenever a
   command is folded into another, add its old name here (this table is
   necessarily hand-maintained since a removed name has no live section to
   introspect; unlike the command list below, it does NOT self-update — review
   it whenever commands are merged):
     think, reflect, audit, estimate  → folded into `ithinking` subcommands
     token-budget                     → folded into `tokens --model`
     knowledge-add                    → folded into `knowledge add`
   If COMMAND matches one of these AND it is not ALSO a `### <COMMAND>` section
   of its own below (check the live list first — this table can lag a moment
   behind an intentional un-merge), print:
   "`/jsat <COMMAND>` was folded into `/jsat <successor>`. Showing that:"
   then print the successor's help block.

2. TYPO / CLOSE MATCH: if COMMAND is not an exact section match and not a known
   alias above, compare it against every command name in the Full Command List
   table using a simple closeness heuristic (shares a long common substring,
   edit distance of 1-2 characters, or a transposition). If exactly one close
   match stands out, respond: "Unknown command: <COMMAND> — did you mean
   `/jsat <closest-match>`?" and print that command's help block underneath, so
   the user isn't forced into a second round trip.
   If nothing is close enough to name with confidence, THEN fall back to plain
   `Unknown command: <COMMAND>` plus the Full Command List — do not guess a match
   you are not reasonably confident in, a wrong suggestion is worse than none.

---

### universal-flags
Two flags work on EVERY /jsat command. Extract them from ARGS before routing to the subcommand,
then pass as tool call arguments (_budget=N, _dashboard=True).
```
Universal flags (any command):
  timeout=<N>     → soft time budget in seconds (notification-only; hard kill at 5×N)
  dashboard=true  → open a real-time browser dashboard for this call
  raw=true        → skip the default input-correction rewrite; use ARGS exactly as typed
```

---

### aw
Workflow advisor — classifies your task and runs the optimal JSAT tool sequence end-to-end.
```
/jsat aw [flags] <args>

Flags:
  --type <type>   → skip classification, force a specific workflow type
  --dry           → show the workflow plan only, do NOT run any tools

Examples:
  /jsat-aw add idempotency keys to the payment mutation endpoint
    → classifies as "feature": lazy → find-function → blast-radius → crack → test-gaps
```

### blast-radius
Trace downstream impact of a change. Supports flags in $ARGUMENTS.
```
/jsat blast-radius [flags] <args>

Flags:
  --file           → call jsat__blast_radius_file with path=<rest>
  --diff           → call jsat__blast_radius_diff with diff=<rest>
  --symbol         → call jsat__blast_radius_symbol with symbol=<rest>
  --severity <lvl> → filter the RESULT to breaking|degraded|warning|safe only (client-side —
  --depth <N>      → override BFS depth (maps to max_depth; default 3 for the bare

Examples:
  /jsat-blast-radius src/payment/service.py
    → jsat__blast_radius(target="src/payment/service.py")
```

### changelog
Generate a changelog between two refs, grouped by service and impact, from commit history and the graph.
```
/jsat changelog [flags] <args>

Flags:
  --service <name>   → scope to one service's changes only
  --breaking-only    → show only changes with a breaking blast-radius impact

Examples:
  /jsat-changelog
    → changelog since the last tag
  /jsat-changelog v1.2.0 v1.3.0
    → changelog between two tags
  /jsat-changelog --service PaymentService main HEAD
```

### cherry-pick
Cherry-pick a single commit onto the current branch with graph-aware impact analysis and semantic conflict resolution.
```
/jsat cherry-pick [flags] <args>

Flags:
  --dry-run      → show impact + conflict forecast only, do NOT touch git state
  --continue     → resume a cherry-pick already in progress
  --abort        → run `git cherry-pick --abort` and stop
  --allow-dirty  → stash uncommitted changes before starting, restore after (Phase 0)

Examples:
  /jsat-cherry-pick a1b2c3d
  /jsat-cherry-pick --dry-run a1b2c3d
```

### cohesion
File and function cohesion analysis — flags oversized files, high complexity, and mixed responsibilities.
```
/jsat cohesion [flags] <args>

Flags:
  --service <name>    → scope to one service
  --threshold <N>     → flag files with more than N lines (default: 800)
  --functions         → show function-level analysis only (no file-level)

Examples:
(see /jsat <command> for usage)
```

### contract
Check API contract compatibility between branches.
```
/jsat contract [flags] <args>

Flags:
  --score              → show only the numeric compatibility score (0-100)
  --breaking           → show breaking changes only

Examples:
  /jsat-contract
    → diff main...HEAD for all OpenAPI/AsyncAPI specs in the repo
```

### coverage
Show behavioral test coverage estimate. Supports generating tests for gaps.
```
/jsat coverage [flags] <args>

Flags:
  --generate       → after showing gaps, call jsat__generate_unit_test for top uncovered paths
  --service <name> → scope to one service (the ONLY native scoping this tool supports —
  --limit N        → show only top N uncovered paths (default: all for display; see
  --generate; do not rank by whatever order the tool happens to return): rank by, in
  --generate DEFAULT CAP: if --generate is given WITHOUT --limit, do not generate a

Examples:
  /jsat-coverage --service PaymentService
    → jsat__get_behavioral_coverage(service="PaymentService")  (native scoping)
```

### crack
Multi-agent war room with artifact carry-forward — each agent builds on prior findings.
```
/jsat crack [flags] <args>

Flags:
  --phases N   → run in N phases (2-6, default: 6)
  --single     → run all agents at once (original one-shot behavior, may timeout)
  --continue   → resume the most recent in_progress crack session
  --continue will retry it once the backend is fixed, and STOP the war room rather
  --phases value; a phase-number reference that happened to be correct in 6-phase

Examples:
(see /jsat <command> for usage)
```

### dead-code
Find functions and classes with no callers in the codebase — a graph inversion of blast-radius, not a new capability.
```
/jsat dead-code [flags] <args>

Flags:
  --service <name>   → scope to one service (avoids timeout on large codebases)
  --include-private  → also flag private/internal (_prefixed) functions (default: only

Examples:
  /jsat-dead-code
    → scan the whole indexed codebase for unreferenced functions/classes
  /jsat-dead-code --service PaymentService
    → scope to one service
  /jsat-dead-code src/legacy/
    → scope to one path
```

### decide
Decision journal — log architectural decisions and surface them by file, topic, or blast-radius context.
```
/jsat decide [flags] <args>

Flags:
  (no flags — see /jsat <command> for full behavior)

Examples:
  /jsat decide log Switched caching from Redis to in-memory — cost $500/month, latency acceptable
  /jsat decide log --impact h Chose PostgreSQL over MongoDB for ACID compliance on payment records
  /jsat decide context src/payments/service.py
  /jsat decide search caching strategy
```

### doctor
Run a full JSAT system health check.
```
/jsat doctor [flags] <args>

Flags:
  (no flags — see /jsat <command> for full behavior)

Examples:
(see /jsat <command> for usage)
```

### find-class
Find a class in the indexed codebase. Supports service scoping.
```
/jsat find-class [flags] <args>

Flags:
  --service <name>  → scope search to one service

Examples:
(see /jsat <command> for usage)
```

### find-function
Find a function or method in the indexed codebase. Supports service scoping.
```
/jsat find-function [flags] <args>

Flags:
  --service <name>  → scope search to one service

Examples:
(see /jsat <command> for usage)
```

### improve
Diagnose problems JSAT hit in itself and draft a patch to JSAT's own source.
```
/jsat improve [flags] <args>

Flags:
  --list          → only show what has been recorded, analyse nothing
  --id <fp8>      → work on one specific recorded issue
  --report        → open a pre-filled GitHub issue in the browser after diagnosing

Examples:
(see /jsat <command> for usage)
```

### incident
Investigate a production incident. Supports subcommands in $ARGUMENTS.
```
/jsat incident [flags] <args>

Flags:
  --since <time>      → limit commit search to window (24h, 7d)
  --service <name>    → scope graph correlation to one service

Examples:
  /jsat-incident 500 errors spiking on checkout since 14:00
    → jsat__investigate_incident(description="500 errors spiking on checkout since 14:00")
```

### index
Build or refresh the JSAT codebase graph index. Supports flags in $ARGUMENTS.
```
/jsat index [flags] <args>

Flags:
  --force          → pass force=true  (full re-index, ignores incremental cache)
  --languages X,Y  → pass languages=["X","Y"]  (limit to specific languages)

Examples:
  /jsat-index .                    → jsat__index_repo(path=".")
  /jsat-index src/ --force         → jsat__index_repo(path="src/", force=true)
  /jsat-index . --languages python,go  → jsat__index_repo(path=".", languages=["python","go"])
```

### internet
Query the live internet for up-to-date facts (docs, versions, CVEs, best practices) and optionally ground the answer in this codebase. The one sanctioned exception to JSAT's "jsat__* tools only" rule, since no jsat__* tool reaches the internet.
```
/jsat internet [flags] <args>

Flags:
  --fetch <url>        → skip search, WebFetch this exact URL directly (use when
  --site <domain>      → restrict search to one domain (passed as
  --context             → also call jsat__query(question=<question>) to ground the
  --context forces it on even without that wording.
  --no-context          → skip codebase grounding even if the heuristic above

Examples:
  /jsat internet query what is the current stable version of pydantic
    → WebSearch(query="pydantic current stable version 2026")
```

### ithinking
IThinking meta-cognitive reasoning. Supports subcommands in $ARGUMENTS.
```
/jsat ithinking [flags] <args>

Flags:
  (no flags — see /jsat <command> for full behavior)

Examples:
  /jsat-ithinking refactor the payment retry logic
    → jsat__ithinking_plan(task="refactor the payment retry logic")
```

### knowledge
Query or manage the JSAT knowledge base. Supports subcommands in $ARGUMENTS.
```
/jsat knowledge [flags] <args>

Flags:
  (no flags — see /jsat <command> for full behavior)

Examples:
  /jsat-knowledge what are the payment service ADRs?
    → jsat__knowledge_query(question="what are the payment service ADRs?")
```

### lazy
Reuse-first code planning — runs a 5-rung ladder against the graph before suggesting new code.
```
/jsat lazy [flags] <args>

Flags:
  --audit   → scan a diff/file for over-engineering (code that reimplements existing)
  --review  → check a proposed implementation against the graph for duplication

Examples:
(see /jsat <command> for usage)
```

### list-endpoints
List all API endpoints found in the indexed codebase. Supports filtering.
```
/jsat list-endpoints [flags] <args>

Flags:
  --service <name>    → filter to one service's endpoints
  --method <METHOD>   → filter by HTTP method (GET, POST, PUT, PATCH, DELETE)

Examples:
(see /jsat <command> for usage)
```

### list-services
List all services found in the indexed codebase. Supports language filtering.
```
/jsat list-services [flags] <args>

Flags:
  --language <lang>  → filter by language (python, go, javascript, java, ruby, rust)

Examples:
(see /jsat <command> for usage)
```

### magic
AI-orchestrated skill composer — analyzes any task and dynamically selects, orders, and runs the optimal JSAT skills to complete it.
```
/jsat magic [flags] <args>

Flags:
  --depth quick     → cap at 4 skills (fast pass, breadth-first)
  --depth standard  → cap at 8 skills (default, balanced)
  --depth deep      → cap at 15 skills (comprehensive)
  --budget N        → explicit cap on skill invocations (overrides --depth's cap)
  --service <name>  → scope all skills to one service (avoids timeout)
  --preview         → compose plan only, do NOT run any skills
  --continue        → resume the most recent in_progress magic session
  --generate to Layer 5). When you add a skill this way, ALSO append it to the

Examples:
(see /jsat <command> for usage)
```

### merge
Merge a source branch into a target branch with graph-aware impact analysis, semantic conflict resolution, and post-merge verification.
```
/jsat merge [flags] <args>

Flags:
  --dry-run          → run Phases 0-2 only (context + blast-radius + plan). Do NOT touch git state.
  --strategy ours|theirs|manual  → tie-breaker for PURELY NON-SEMANTIC conflicts only
  --no-verify        → skip Phase 5 (test-gaps/review) after the merge — NOT recommended
  --continue         → resume a merge that is already in progress (working tree has an in-progress merge)
  --allow-dirty      → stash uncommitted changes before starting, restore after (Phase 0)
  --dry-run was combined with a would-be-FF merge — report "would fast-forward" instead.

Examples:
  /jsat-merge feature/checkout-retry main
    → merge feature/checkout-retry into main, full flow
```

### migration
Validate a database migration file for safety. Supports row count hints.
```
/jsat migration [flags] <args>

Flags:
  --rows <table:N>[,<table:N>...]   → hint row count(s) for lock duration estimation.

Examples:
  /jsat-migration db/migrations/0042_add_index.sql
    → jsat__validate_migration(path="db/migrations/0042_add_index.sql")
```

### plan
Pre-implementation planning — six forcing questions + scope/architecture/security review before writing code.
```
/jsat plan [flags] <args>

Flags:
  --scope          → scope review only: what to build and why
  --architecture   → architecture review: how to build it
  --security       → security review: what can go wrong
  --full           → run all three perspectives (default)

Examples:
(see /jsat <command> for usage)
```

### pr-describe
Compose a ready-to-post PR description from review findings, contract diff, and test coverage — pure recombination, no new analysis.
```
/jsat pr-describe [flags] <args>

Flags:
  --no-tests    → skip the test-gaps section (for docs-only / trivial PRs)

Examples:
  /jsat-pr-describe
    → describe the diff between main and the current branch
```

### prompt-diff
Show what you typed vs what JSAT sent to the AI after optimization.
```
/jsat prompt-diff [flags] <args>

Flags:
  (no flags — see /jsat <command> for full behavior)

Examples:
(see /jsat <command> for usage)
```

### prompt-rewrite
Rewrite a prompt using offline pipeline + parallel LLM agents for maximum clarity.
```
/jsat prompt-rewrite [flags] <args>

Flags:
  (no flags — see /jsat <command> for full behavior)

Examples:
(see /jsat <command> for usage)
```

### prompt
Discuss → Plan → Execute → Verify → Synthesize — uses the right tool per query type and checks its own answers.
```
/jsat prompt [flags] <args>

Flags:
  --rewrite or --agent  → Phase 1 optimizer: jsat__prompt_rewrite  (1 LLM agent)
  --agents              → Phase 1 optimizer: jsat__prompt_multi_agent (3 parallel agents)
  --diff                → ALSO show raw vs optimized diff after Phase 1
  --optimize-only       → Stop after Phase 1; show optimized prompt only
  --phases N            → Run N phases (2-6, default: 6)
  --service <name>      → Scope all query phases to this one service
  --single              → Original one-shot flow (optimize → one jsat__query call)
  --continue            → Resume most recent in_progress prompt session

Examples:
(see /jsat <command> for usage)
```

### query
Answer a question about this codebase using JSAT's graph index. Supports service scoping.
```
/jsat query [flags] <args>

Flags:
  --service <name>  → scope answer to one service (reduces context, avoids timeout)
  --short           → prepend brevity constraint (≤3 sentences)
  --service SCOPE SEMANTICS (unverified against tool internals — flag this

Examples:
  /jsat-query what does the payment service do?
    → jsat__query(question="what does the payment service do?")
```

### rebase
Rebase the current branch onto a target using the same graph-aware, semantic conflict resolution engine as /jsat merge.
```
/jsat rebase [flags] <args>

Flags:
  --dry-run      → show impact + conflict forecast only, do NOT touch git state
  --continue     → resume a rebase already in progress (conflict markers in the tree)
  --abort        → run `git rebase --abort` and stop (escape hatch, no analysis)
  --no-verify    → skip Phase 3 (test-gaps/breaking check) after the rebase — NOT recommended
  --allow-dirty  → stash uncommitted changes before starting, restore after (Phase 0)
  --continue` — do not bypass with git's own `--no-verify` unless the user

Examples:
  /jsat-rebase main
    → rebase current branch onto main
```

### recent
Show recent changes in the codebase. Supports time range and author filters.
```
/jsat recent [flags] <args>

Flags:
  --since <time>    → limit to changes since (24h, 7d, 30d)
  --author <name>   → filter by commit author name (substring match)
  --service <name>  → scope to one service's files (takes precedence over a

Examples:
  /jsat-recent
    → jsat__get_recent_changes(target=".")   — see SCOPE WARNING below
```

### review
Multi-model code review. Supports flags in $ARGUMENTS.
```
/jsat review [flags] <args>

Flags:
  --findings        → call jsat__get_review_findings to show results of last review
  --bugs            → call jsat__get_high_confidence_bugs to list confirmed bugs only
  --min high        → filter to high-confidence findings only (applies to whichever
  --min medium      → filter to medium+ (default)

Examples:
  /jsat-review <paste diff here>
    → jsat__submit_for_review(diff="<diff>")
```

### runbook
Generate an incident runbook for a service or component.
```
/jsat runbook [flags] <args>

Flags:
  (no flags — see /jsat <command> for full behavior)

Examples:
  /jsat-runbook PaymentService
    → jsat__generate_runbook(target="PaymentService")
```

### security
Run a security scan. Supports flags in $ARGUMENTS.
```
/jsat security [flags] <args>

Flags:
  --file <path>          → call jsat__security_scan_file with file=<path>
  --secrets              → call jsat__list_secrets to find hardcoded credentials
  --auth                 → call jsat__get_auth_coverage to show auth gaps
  --cves [path]          → CVE check (see "CVE check" below — does NOT call
  --severity critical    → filter to critical only (pass severity_threshold="critical").
  --severity high        → filter to high+ (default: medium). Same scope limit as above.

Examples:
  /jsat-security
    → jsat__security_review(path=".")
  /jsat-security src/payment/
    → jsat__security_review(path="src/payment/")
  /jsat-security --file src/auth/login.py
    → jsat__security_scan_file(file="src/auth/login.py")
  /jsat-security --secrets
    → jsat__list_secrets()
  /jsat-security --cves src/payment/
    → jsat__security_review(path="src/payment/") → read its `cves` field
```

### service-health-check
Validate one service's readiness — CLAUDE.md completeness, catalog registration, auth coverage, test gaps, and index freshness for that service.
```
/jsat service-health-check [flags] <args>

Flags:
  (no flags — see /jsat <command> for full behavior)

Examples:
  /jsat-service-health-check PaymentService
  /jsat-service-health-check jsat
```

### short
Ask any question — get the briefest possible correct answer (≤3 sentences).
```
/jsat short [flags] <args>

Flags:
  --one-line  → request exactly one sentence

Examples:
(see /jsat <command> for usage)
```

### smart
Terse compression mode — answers in fragments, no filler, code intact. Supports --lite / --full / --ultra.
```
/jsat smart [flags] <args>

Flags:
  --lite    → remove filler phrases only (~30% reduction)
  --full    → fragments + no explanatory preamble (~55% reduction, default)
  --ultra   → one bullet per fact, ≤8 words each (~70% reduction)

Examples:
  /jsat-smart what does the payment service do?
    → full mode: fragment bullets, no filler
```

### sprint
Seven-stage delivery workflow — Think → Plan → Build → Review → Test → Ship → Reflect, each stage fast and focused.
```
/jsat sprint [flags] <args>

Flags:
  --stage <1-7>    → resume from a specific stage (skip earlier stages)
  --dry            → show the sprint plan without running any tools
  --continue       → resume most recent in_progress sprint session
  --continue, since that would run without the task the user originally gave
  --stage <N> skips stages 1..N-1 entirely, but stages 2-7 all reference outputs
  --stage both read ## Findings for prior-stage context, so it must exist from

Examples:
(see /jsat <command> for usage)
```

### status
Show JSAT index statistics and health.
```
/jsat status [flags] <args>

Flags:
  (no flags — see /jsat <command> for full behavior)

Examples:
(see /jsat <command> for usage)
```

### test-gaps
Find untested code paths and optionally generate tests. Supports flags in $ARGUMENTS.
```
/jsat test-gaps [flags] <args>

Flags:
  --generate         → after finding gaps, call jsat__generate_unit_test for each gap
  --integration      → call jsat__generate_integration_test instead of unit tests
  --contract <A> <B> → call jsat__generate_contract_test between two services;
  --untested         → call jsat__list_untested_paths for a flat list
  --service <name>   → scope to one service (avoids timeout on large codebases)

Examples:
  /jsat-test-gaps src/payment/
    → jsat__get_test_gaps(path="src/payment/")
```

### tokens
Count, compress, or check token budget. Supports flags in $ARGUMENTS.
```
/jsat tokens [flags] <args>

Flags:
  --compress           → call jsat__token_compress with text=<rest>  (apply compression)
  --model <name>       → call jsat__token_budget with text=<rest>, model=<name>
  --budget <model>     → same as --model  (alias)

Examples:
  /jsat-tokens explain the payment service
    → jsat__token_count(text="explain the payment service")
```

### trace
Trace a call chain from a symbol through the codebase. Supports depth and direction.
```
/jsat trace [flags] <args>

Flags:
  --upstream         → find who calls <source> (see below — different tool, not

Examples:
  /jsat-trace PaymentService.process RefundService.issue
    → jsat__trace_call_chain(from="PaymentService.process", to="RefundService.issue")
      → shortest path between the two, up to 10 hops; {"found": false, ...} if none
```

### upgrade-impact
Assess the blast radius of bumping a dependency — which files import it, how critical those paths are, and whether the current version has known CVEs.
```
/jsat upgrade-impact [flags] <args>

Flags:
  --service <name>   → scope the import search to one service
  --to <version>     → the target version being considered (used only for the summary

Examples:
  /jsat-upgrade-impact requests
  /jsat-upgrade-impact --to 3.0.0 --service PaymentService pydantic
```

### verify
Prove a code change actually works by driving it end-to-end, prioritized by graph impact rather than blind manual testing.
```
/jsat verify [flags] <args>

Flags:
  --service <name>   → scope graph lookups to one service (avoids timeout on large repos)
  --claim <text>     → the specific behavior to verify ("returns 402 on insufficient funds")

Examples:
  /jsat-verify src/payment/service.py
    → blast-radius + test-gaps on that file, then drive the affected behavior live
```

---

## Full Command List

| Command | One-line description |
|---------|---------------------|
| `aw` | Workflow advisor — classifies your task and runs the optimal JSAT tool sequence end-to-end. |
| `blast-radius` | Trace downstream impact of a change. Supports flags in $ARGUMENTS. |
| `changelog` | Generate a changelog between two refs, grouped by service and impact, from commit history and the graph. |
| `cherry-pick` | Cherry-pick a single commit onto the current branch with graph-aware impact analysis and semantic conflict resolution. |
| `cohesion` | File and function cohesion analysis — flags oversized files, high complexity, and mixed responsibilities. |
| `contract` | Check API contract compatibility between branches. |
| `coverage` | Show behavioral test coverage estimate. Supports generating tests for gaps. |
| `crack` | Multi-agent war room with artifact carry-forward — each agent builds on prior findings. |
| `dead-code` | Find functions and classes with no callers in the codebase — a graph inversion of blast-radius, not a new capability. |
| `decide` | Decision journal — log architectural decisions and surface them by file, topic, or blast-radius context. |
| `doctor` | Run a full JSAT system health check. |
| `find-class` | Find a class in the indexed codebase. Supports service scoping. |
| `find-function` | Find a function or method in the indexed codebase. Supports service scoping. |
| `help` | Show flags, params, and examples for any /jsat command. Usage: /jsat-help <command> |
| `improve` | Diagnose problems JSAT hit in itself and draft a patch to JSAT's own source. |
| `incident` | Investigate a production incident. Supports subcommands in $ARGUMENTS. |
| `index` | Build or refresh the JSAT codebase graph index. Supports flags in $ARGUMENTS. |
| `internet` | Query the live internet for up-to-date facts (docs, versions, CVEs, best practices) and optionally ground the answer in this codebase. The one sanctioned exception to JSAT's "jsat__* tools only" rule, since no jsat__* tool reaches the internet. |
| `ithinking` | IThinking meta-cognitive reasoning. Supports subcommands in $ARGUMENTS. |
| `knowledge` | Query or manage the JSAT knowledge base. Supports subcommands in $ARGUMENTS. |
| `lazy` | Reuse-first code planning — runs a 5-rung ladder against the graph before suggesting new code. |
| `list-endpoints` | List all API endpoints found in the indexed codebase. Supports filtering. |
| `list-services` | List all services found in the indexed codebase. Supports language filtering. |
| `magic` | AI-orchestrated skill composer — analyzes any task and dynamically selects, orders, and runs the optimal JSAT skills to complete it. |
| `merge` | Merge a source branch into a target branch with graph-aware impact analysis, semantic conflict resolution, and post-merge verification. |
| `migration` | Validate a database migration file for safety. Supports row count hints. |
| `plan` | Pre-implementation planning — six forcing questions + scope/architecture/security review before writing code. |
| `pr-describe` | Compose a ready-to-post PR description from review findings, contract diff, and test coverage — pure recombination, no new analysis. |
| `prompt-diff` | Show what you typed vs what JSAT sent to the AI after optimization. |
| `prompt-rewrite` | Rewrite a prompt using offline pipeline + parallel LLM agents for maximum clarity. |
| `prompt` | Discuss → Plan → Execute → Verify → Synthesize — uses the right tool per query type and checks its own answers. |
| `query` | Answer a question about this codebase using JSAT's graph index. Supports service scoping. |
| `rebase` | Rebase the current branch onto a target using the same graph-aware, semantic conflict resolution engine as /jsat merge. |
| `recent` | Show recent changes in the codebase. Supports time range and author filters. |
| `review` | Multi-model code review. Supports flags in $ARGUMENTS. |
| `runbook` | Generate an incident runbook for a service or component. |
| `security` | Run a security scan. Supports flags in $ARGUMENTS. |
| `service-health-check` | Validate one service's readiness — CLAUDE.md completeness, catalog registration, auth coverage, test gaps, and index freshness for that service. |
| `short` | Ask any question — get the briefest possible correct answer (≤3 sentences). |
| `smart` | Terse compression mode — answers in fragments, no filler, code intact. Supports --lite / --full / --ultra. |
| `sprint` | Seven-stage delivery workflow — Think → Plan → Build → Review → Test → Ship → Reflect, each stage fast and focused. |
| `status` | Show JSAT index statistics and health. |
| `test-gaps` | Find untested code paths and optionally generate tests. Supports flags in $ARGUMENTS. |
| `tokens` | Count, compress, or check token budget. Supports flags in $ARGUMENTS. |
| `trace` | Trace a call chain from a symbol through the codebase. Supports depth and direction. |
| `upgrade-impact` | Assess the blast radius of bumping a dependency — which files import it, how critical those paths are, and whether the current version has known CVEs. |
| `verify` | Prove a code change actually works by driving it end-to-end, prioritized by graph impact rather than blind manual testing. |

Run `/jsat-help <command>` for flags and examples on any specific command.

BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
  raw=true        → skip the default AI input-correction rewrite for this call
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)
