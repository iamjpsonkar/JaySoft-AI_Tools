"""
jsat._cli_skills_data — Static skill definitions and command writers.
"""
from __future__ import annotations

from pathlib import Path

import structlog

_log = structlog.get_logger(__name__)

# ── Shared skill definitions (reused by Claude, Continue, and docs) ────────────

# Each entry: skill-name → (description, instruction)
# $ARGUMENTS is replaced by {input} for Continue's customCommands format.
_JSAT_SKILLS: dict[str, tuple[str, str]] = {
        # ── Graph exploration ─────────────────────────────────────────────────
        "jsat-query": (
            "Answer a question about this codebase using JSAT's graph index. Supports service scoping.",
            """Parse $ARGUMENTS for optional flags, then call jsat__query:

Supported flags:
  --service <name>  → scope answer to one service (reduces context, avoids timeout)
  --short           → prepend brevity constraint (≤3 sentences)
  (no flag)         → full graph query

Examples:
  /jsat-query what does the payment service do?
    → jsat__query(question="what does the payment service do?")

  /jsat-query --service PaymentService how is retry handled?
    → jsat__query(question="how is retry handled?", service="PaymentService")

TIMEOUT RECOVERY: If jsat__query times out or returns "[AI unavailable]":
  1. Narrow scope: add --service <name> to limit context
  2. Use /jsat-short for a briefer answer (≤3 sentences)
  3. Break complex questions into smaller focused queries"""
        ),
        "jsat-index": (
            "Build or refresh the JSAT codebase graph index. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call jsat__index_repo:

Supported flags (strip from path before passing):
  --force          → pass force=true  (full re-index, ignores incremental cache)
  --languages X,Y  → pass languages=["X","Y"]  (limit to specific languages)
  (no flag)        → incremental index of path (or "." if empty)

Examples:
  /jsat-index .                    → jsat__index_repo(path=".")
  /jsat-index src/ --force         → jsat__index_repo(path="src/", force=true)
  /jsat-index . --languages python,go  → jsat__index_repo(path=".", languages=["python","go"])

After indexing, show: nodes indexed, edges indexed, files parsed vs skipped, parallel workers.
For large repos (>50k files): index one directory at a time — /jsat-index src/ then /jsat-index tests/"""
        ),
        "jsat-status": (
            "Show JSAT index statistics and health.",
            """Use jsat__get_index_status and jsat__get_jsat_version to display:
- Node and edge counts with breakdown by type
- JSAT version and graph backend (SQLite / Neo4j)
- Index freshness (when last indexed)

Flag if: node count is 0 (not indexed yet), or version is outdated.
Suggest /jsat-index . if graph is empty."""
        ),
        "jsat-doctor": (
            "Run a full JSAT system health check.",
            """Use jsat__health to run a full system check. Present results in this order:
1. JSAT version and graph backend
2. AI provider: which is active, which are available, free vs paid
3. Graph: node count, edge count, last indexed timestamp
4. MCP connection: which tools are loaded
5. Config: profile (solo/team/ci), any missing settings

Flag as ⚠️ WARN: graph not indexed, no AI configured, stale index (>7 days old)
Flag as ❌ ERROR: graph backend unavailable, AI provider failing test call
For each issue: suggest the fix command (e.g. /jsat-index ., jsat ai use ollama)."""
        ),
        "jsat-find-function": (
            "Find a function or method in the indexed codebase. Supports service scoping.",
            """Parse $ARGUMENTS for optional --service flag, then call jsat__get_function:

  --service <name>  → scope search to one service
  (no flag)         → search entire codebase

Call jsat__get_function with name=<stripped arguments>.
Show: file, line numbers, parameters (with types), return type, complexity, decorators.

If multiple matches: list all matches with file:line so the user can choose.
If no match found: suggest jsat__query(question="find function similar to <name>")"""
        ),
        "jsat-find-class": (
            "Find a class in the indexed codebase. Supports service scoping.",
            """Parse $ARGUMENTS for optional --service flag, then call jsat__get_class:

  --service <name>  → scope search to one service
  (no flag)         → search entire codebase

Call jsat__get_class with name=<stripped arguments>.
Show: file, line numbers, base classes, method count, docstring.

If multiple matches: list all with file:line so the user can choose.
If no match found: suggest jsat__query(question="find class similar to <name>")"""
        ),
        "jsat-list-services": (
            "List all services found in the indexed codebase. Supports language filtering.",
            """Parse $ARGUMENTS for optional --language flag, then call jsat__list_services:

  --language <lang>  → filter by language (python, go, javascript, java, ruby, rust)
  (no flag)          → list all services

Show each service with: name, language, entry point file, endpoint count.
Show total count at the end. If no services found, suggest /jsat-index ."""
        ),
        "jsat-list-endpoints": (
            "List all API endpoints found in the indexed codebase. Supports filtering.",
            """Parse $ARGUMENTS for optional flags, then call jsat__list_endpoints:

  --service <name>    → filter to one service's endpoints
  --method <METHOD>   → filter by HTTP method (GET, POST, PUT, PATCH, DELETE)
  (no flag)           → list all endpoints

Show each endpoint: HTTP method, route, handler function, auth required (yes/no).
Group by service. Show total count. Highlight unauthenticated endpoints with ⚠️."""
        ),
        "jsat-trace": (
            "Trace a call chain from a symbol through the codebase. Supports depth and direction.",
            """Parse $ARGUMENTS for optional flags, then call jsat__trace_call_chain:

Supported flags:
  --depth N       → limit trace depth to N levels (default: no limit)
  --upstream      → show callers of this symbol (who calls it), not what it calls
  (no flag)       → trace downstream: what this symbol calls

Examples:
  /jsat-trace PaymentService.process
    → jsat__trace_call_chain(symbol="PaymentService.process")

  /jsat-trace --depth 3 PaymentService.process
    → jsat__trace_call_chain(symbol="PaymentService.process", max_depth=3)

Display as a numbered chain from entrypoint to leaf. Show file:line for each node. Flag cycles."""
        ),
        # ── Impact & safety ───────────────────────────────────────────────────
        "jsat-blast-radius": (
            "Trace downstream impact of a change. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call the right blast-radius tool:

Supported flags:
  --file           → call jsat__blast_radius_file with path=<rest>
  --diff           → call jsat__blast_radius_diff with diff=<rest>
  --symbol         → call jsat__blast_radius_symbol with symbol=<rest>
  --severity <lvl> → filter output to breaking|degraded|warning|safe only
  (no flag)        → call jsat__blast_radius with target=<rest>

Examples:
  /jsat-blast-radius src/payment/service.py
    → jsat__blast_radius(target="src/payment/service.py")

  /jsat-blast-radius --file src/payment/service.py
    → jsat__blast_radius_file(path="src/payment/service.py")

  /jsat-blast-radius --symbol PaymentService.process
    → jsat__blast_radius_symbol(symbol="PaymentService.process")

  /jsat-blast-radius --severity breaking src/payment/service.py
    → jsat__blast_radius(target="src/payment/service.py", severity_filter=["breaking"])

Group results by severity: breaking / degraded / warning / safe.
Show summary counts first. Show Mermaid diagram if impacts > 5."""
        ),
        "jsat-security": (
            "Run a security scan. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call the right security tool:

Supported flags:
  --file <path>          → call jsat__security_scan_file with file=<path>
  --secrets              → call jsat__list_secrets to find hardcoded credentials
  --auth                 → call jsat__get_auth_coverage to show auth gaps
  --cves                 → call jsat__get_dependency_cves for CVE check
  --severity critical    → filter to critical only (pass severity_threshold="critical")
  --severity high        → filter to high+ (default: medium)
  (no flag / path only)  → call jsat__security_review with path=<rest or ".">

Examples:
  /jsat-security
    → jsat__security_review(path=".")
  /jsat-security src/payment/
    → jsat__security_review(path="src/payment/")
  /jsat-security --file src/auth/login.py
    → jsat__security_scan_file(file="src/auth/login.py")
  /jsat-security --secrets
    → jsat__list_secrets()
  /jsat-security --cves
    → jsat__get_dependency_cves()

Group findings by severity: Critical → High → Medium → Low.
For each finding: file, line, rule ID, description, remediation.

LARGE REPO STRATEGY: For repos >10k files, scan one directory at a time:
  /jsat-security src/auth/    then   /jsat-security src/payment/"""
        ),
        "jsat-migration": (
            "Validate a database migration file for safety. Supports row count hints.",
            """Parse $ARGUMENTS for optional flags, then call jsat__validate_migration:

Supported flags:
  --rows <table:N>   → hint table row count for lock duration estimation
                       (e.g. --rows orders:5000000)
  (no flag)          → validate migration file at path=<rest>

Examples:
  /jsat-migration db/migrations/0042_add_index.sql
    → jsat__validate_migration(path="db/migrations/0042_add_index.sql")

  /jsat-migration --rows orders:5000000 db/migrations/0042.sql
    → jsat__validate_migration(path="db/migrations/0042.sql", table_rows={"orders": 5000000})

Show for each SQL operation: lock type, estimated duration, danger level.
Show zero-downtime alternative for any dangerous operation.
Flag: missing rollback (DOWN section), multiple locking ops in single file, FK without index."""
        ),
        "jsat-contract": (
            "Check API contract compatibility between branches.",
            """Parse $ARGUMENTS, then call jsat__get_api_diff:

Usage:
  (no args)            → jsat__get_api_diff(base="main", head="HEAD")
  <base> <head>        → jsat__get_api_diff(base=<base>, head=<head>)
  --score              → show only the numeric compatibility score (0-100)
  --breaking           → show breaking changes only

Examples:
  /jsat-contract
    → diff main...HEAD for all OpenAPI/AsyncAPI specs in the repo

  /jsat-contract main feature/new-payments
    → jsat__get_api_diff(base="main", head="feature/new-payments")

Show:
  - Compatibility score (100 = no breaking changes; score decays logarithmically)
  - Breaking changes: endpoint removed, required field removed, type changed
  - Non-breaking: new endpoints, optional fields added
  - Migration guide for each breaking change"""
        ),
        # ── Code quality ──────────────────────────────────────────────────────
        "jsat-review": (
            "Multi-model code review. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call the right review tool:

Supported flags:
  --findings        → call jsat__get_review_findings to show results of last review
  --bugs            → call jsat__get_high_confidence_bugs to list confirmed bugs only
  --min high        → filter to high-confidence findings only
  --min medium      → filter to medium+ (default)
  (no flag)         → call jsat__submit_for_review with diff=<rest>

Examples:
  /jsat-review <paste diff here>
    → jsat__submit_for_review(diff="<diff>")

  /jsat-review --findings
    → jsat__get_review_findings()

  /jsat-review --bugs
    → jsat__get_high_confidence_bugs()

Show findings grouped by confidence: high → medium → low.
Highlight bugs confirmed by 2+ models.

LARGE DIFF STRATEGY: For diffs >500 lines, split by file and review in chunks:
  /jsat-review <first file's diff>   then   /jsat-review <next file's diff>
Then run /jsat-review --bugs to see cross-chunk high-confidence findings."""
        ),
        "jsat-test-gaps": (
            "Find untested code paths and optionally generate tests. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call the right test tool:

Supported flags:
  --generate         → after finding gaps, call jsat__generate_unit_test for each gap
  --integration      → call jsat__generate_integration_test instead of unit tests
  --contract <A> <B> → call jsat__generate_contract_test between two services
  --untested         → call jsat__list_untested_paths for a flat list
  --service <name>   → scope to one service (avoids timeout on large codebases)
  (no flag)          → call jsat__get_test_gaps with path=<rest or ".">

Examples:
  /jsat-test-gaps src/payment/
    → jsat__get_test_gaps(path="src/payment/")

  /jsat-test-gaps --generate src/payment/
    → jsat__get_test_gaps then jsat__generate_unit_test for each gap

  /jsat-test-gaps --untested
    → jsat__list_untested_paths()

  /jsat-test-gaps --contract PaymentService RefundService
    → jsat__generate_contract_test(producer="PaymentService", consumer="RefundService")

LARGE CODEBASE STRATEGY: Run per-service to avoid timeout:
  /jsat-test-gaps --service PaymentService   then   /jsat-test-gaps --service RefundService"""
        ),
        "jsat-coverage": (
            "Show behavioral test coverage estimate. Supports generating tests for gaps.",
            """Parse $ARGUMENTS for optional flags, then call jsat__get_behavioral_coverage:

Supported flags:
  --generate       → after showing gaps, call jsat__generate_unit_test for top uncovered paths
  --service <name> → scope to one service (avoids timeout on large codebases)
  --limit N        → show only top N uncovered paths (default: all)
  (no flag)        → full coverage report for path=<rest or ".">

Examples:
  /jsat-coverage src/payment/
    → jsat__get_behavioral_coverage(path="src/payment/")

  /jsat-coverage --generate --limit 5 src/payment/
    → coverage report + generate tests for 5 most critical uncovered paths

  /jsat-coverage --service PaymentService
    → scope to one service to avoid timeout

Show: overall % covered, uncovered functions, over-mocked tests, endpoint gaps."""
        ),
        # ── Knowledge base ────────────────────────────────────────────────────
        "jsat-knowledge": (
            "Query or manage the JSAT knowledge base. Supports subcommands in $ARGUMENTS.",
            """Parse $ARGUMENTS for an optional subcommand, then call the right tool:

Subcommands:
  add <text>                  → call jsat__knowledge_add with text=<text>
  add --category <cat> <text> → store with category (adr, runbook, pattern, decision)
  list                        → call jsat__knowledge_list to show all entries
  list <category>             → call jsat__knowledge_list with category=<category>
  stale <id>                  → call jsat__knowledge_flag_stale with entry_id=<id>
  search <text>               → call jsat__knowledge_search with query=<text>
  (no subcommand)             → call jsat__knowledge_query with query=<rest>  (semantic search)

Examples:
  /jsat-knowledge what are the payment service ADRs?
    → jsat__knowledge_query(query="what are the payment service ADRs?")

  /jsat-knowledge add Use tenacity for all retry logic per ADR-007
    → jsat__knowledge_add(text="Use tenacity for all retry logic per ADR-007")

  /jsat-knowledge add --category adr Payments use idempotency keys for all mutations
    → jsat__knowledge_add(text="...", category="adr")

  /jsat-knowledge list adr
    → jsat__knowledge_list(category="adr")

  /jsat-knowledge search retry patterns
    → jsat__knowledge_search(query="retry patterns")"""
        ),
        "jsat-knowledge-add": (
            "Add an entry to the JSAT knowledge base with optional category.",
            """Parse $ARGUMENTS for optional --category flag, then call jsat__knowledge_add:

  --category <cat>  → tag the entry (adr, runbook, pattern, decision, context)
  (no flag)         → store with no category

Examples:
  /jsat-knowledge-add Use tenacity for retry logic per ADR-007
    → jsat__knowledge_add(text="Use tenacity for retry logic per ADR-007")

  /jsat-knowledge-add --category adr All payment mutations require idempotency keys
    → jsat__knowledge_add(text="All payment mutations require idempotency keys", category="adr")

Confirm the entry was stored: show its ID and a one-line preview."""
        ),
        "jsat-runbook": (
            "Generate an incident runbook for a service or component.",
            """Parse $ARGUMENTS for optional subcommands, then call jsat__generate_runbook:

  sections <target>   → show section outline only (no full content)
  (no subcommand)     → full runbook for target=<rest>

Examples:
  /jsat-runbook PaymentService
    → jsat__generate_runbook(target="PaymentService")

  /jsat-runbook sections PaymentService
    → outline only: symptoms, diagnosis, rollback, escalation, monitoring

Full runbook includes:
  1. Symptoms and alert signatures
  2. Diagnosis steps (with graph-derived call chain)
  3. Rollback procedure
  4. Escalation path and contacts
  5. Prevention and monitoring checklist"""
        ),
        # ── Investigation ─────────────────────────────────────────────────────
        "jsat-incident": (
            "Investigate a production incident. Supports subcommands in $ARGUMENTS.",
            """Parse $ARGUMENTS for an optional subcommand, then call the right tool:

Subcommands:
  hypotheses          → call jsat__get_hypotheses to list ranked root-cause hypotheses
  recent [path]       → call jsat__get_recent_changes to show recent commits in area
  runbook <svc>       → call jsat__generate_runbook to produce an incident runbook
  (no subcommand)     → call jsat__investigate_incident with description=<rest>

Supported flags:
  --since <time>      → limit commit search to window (24h, 7d)
  --service <name>    → scope graph correlation to one service

Examples:
  /jsat-incident 500 errors spiking on checkout since 14:00
    → jsat__investigate_incident(description="500 errors spiking on checkout since 14:00")

  /jsat-incident hypotheses
    → jsat__get_hypotheses()  (after a previous investigation)

  /jsat-incident recent src/payment/
    → jsat__get_recent_changes(target="src/payment/")

  /jsat-incident runbook PaymentService
    → jsat__generate_runbook(target="PaymentService")

Show top hypotheses ranked by score. For each: commit hash, author, changed files, keyword evidence.
TIMEOUT STRATEGY: Use --since 24h to narrow the commit range on large repos."""
        ),
        "jsat-recent": (
            "Show recent changes in the codebase. Supports time range and author filters.",
            """Parse $ARGUMENTS for optional flags, then call jsat__get_recent_changes:

Supported flags:
  --since <time>    → limit to changes since (24h, 7d, 30d)
  --author <name>   → filter by commit author name (substring match)
  --service <name>  → scope to one service's files
  (no flag)         → recent changes for target=<rest or ".">

Examples:
  /jsat-recent
    → jsat__get_recent_changes(target=".")

  /jsat-recent --since 24h src/payment/
    → recent changes in src/payment/ in the last 24 hours

  /jsat-recent --author jay
    → commits by any author whose name contains "jay"

Show: short hash, author, timestamp, files changed, summary.
Highlight: large commits (>10 files), changes touching auth/payment/migrations."""
        ),
        # ── Prompt & token tools ──────────────────────────────────────────────
        "jsat-prompt": (
            "Discuss → Plan → Execute → Verify → Synthesize — uses the right tool per query type and checks its own answers.",
            """Parse $ARGUMENTS for optional flags:

  --rewrite or --agent  → Phase 1 optimizer: jsat__prompt_rewrite  (1 LLM agent)
  --agents              → Phase 1 optimizer: jsat__prompt_multi_agent (3 parallel agents)
  (no optimizer flag)   → Phase 1 optimizer: jsat__prompt_optimize (offline, fastest)
  --diff                → ALSO show raw vs optimized diff after Phase 1
  --optimize-only       → Stop after Phase 1; show optimized prompt only
  --phases N            → Run N phases (2-6, default: 6)
  --service <name>      → Scope all query phases to this one service
  --single              → Original one-shot flow (optimize → one jsat__query call)
  --continue            → Resume most recent in_progress prompt session

## --continue Flag

When --continue is given:
  1. List ~/.jsat/sessions/prompt-*.md; find most recent with status: in_progress
  2. Read it; extract optimized_prompt from ## Findings if Phase 1 completed
  3. Find first "- [ ]" phase — resume from there with saved context
  4. Print: "▶ Resuming prompt session: <filename>"

The query is every word that is NOT a flag. Strip all flags; join the rest.
Priority when multiple optimizer flags: --agents beats --rewrite.

## Phased Mode (default, --phases 6)

Run in 6 sequential phases. Show output after each.

### Session File (before Phase 1)
Create ~/.jsat/sessions/prompt-<SLUG>-<YYYYMMDD-HHMM>.md with phases 1-6 as unchecked steps.
Print: "📄 Session: <path>"

### Phase 1 — Discuss + Optimize (~6s)

STEP A — Discuss (before optimizing):
Classify the query type from the question text:
  structural → contains "what calls", "who calls", "callers", "trace", "call chain"
  lookup     → contains "where is", "find function", "find class", "locate"
  security   → contains "security", "auth", "vulnerability", "secrets", "CVE"
  incident   → contains "failing", "error", "500", "broken", "bug"
  coverage   → contains "untested", "test gaps", "coverage"
  general    → everything else

Select the primary execution tool for Phase 3:
  structural → jsat__trace_call_chain
  lookup     → jsat__get_function or jsat__get_class
  security   → jsat__security_review
  incident   → jsat__investigate_incident
  coverage   → jsat__get_test_gaps
  general    → jsat__query

Print: "🗣 Query type: <type> — primary tool: <tool>"

STEP B — Optimize:
Call the optimizer selected by flags with query=<stripped text>.
Read `optimized_prompt`. Save for all subsequent phases.
Show: optimized prompt, tokens before→after.
If --diff: also call jsat__prompt_diff and show diff.
If --optimize-only: STOP here.
Label: "🔧 Phase 1/6 — Discuss + Optimize"

### Phase 2 — Plan + Scope (~3s)
Call: jsat__get_index_status()
Call: jsat__list_services()
Show: node/edge counts, service list.
State the query plan: "Plan: use <primary_tool> on <service>, then <secondary>."
Identify 1-2 most relevant services for Phase 3-4.
Label: "📊 Phase 2/6 — Plan + Scope"

### Phase 3 — Execute (Primary) (~15s)
Use the primary tool identified in Phase 1:
  structural: jsat__trace_call_chain(symbol=<key_symbol_from_question>)
  lookup:     jsat__get_function(name=<name>) or jsat__get_class(name=<name>)
  security:   jsat__security_review(path=<service_path or ".">)
  incident:   jsat__investigate_incident(description=<optimized_prompt>)
  coverage:   jsat__get_test_gaps(path=<service_path or ".">)
  general:    jsat__query(question=<optimized_prompt>, service=<primary_service>)

If --service was given, use it for all service-scoped calls.
If tool returns "[AI unavailable]": fall back to jsat__query.
Label: "💬 Phase 3/6 — Execute (<tool>)"

### Phase 4 — Execute (Secondary) (~15s)
If a second relevant service was identified in Phase 2:
  Call same primary tool on second service, or jsat__query(service=<second>)
  Label: "💬 Phase 4/6 — Secondary (<service>)"
Else:
  Call: jsat__query(question=<optimized_prompt>) with no service scope
  Label: "💬 Phase 4/6 — Broader Context"

### Phase 5 — Verify (~5s)
Scan Phase 3-4 answers for 2-3 concrete claims to spot-check against the graph:
  function/method name → jsat__get_function(name=<fn>)
  class name           → jsat__get_class(name=<cls>)
  service name         → already known from Phase 2 (no extra call needed)

Mark each claim:
  Found in graph   → ✅ verified
  Not found        → ⚠️ unverified (may be inferred or not yet indexed)

If Phase 3-4 produced no checkable claims (or both timed out):
  Fall back: jsat__short(question=<optimized_prompt>)
Label: "🔍 Phase 5/6 — Verify"

### Phase 6 — Synthesize (by you, Claude — no tool call)
- Lead with the direct answer to the original question
- Present ✅ verified facts first, clearly attributed
- Flag ⚠️ unverified claims: "Note: <X> was not found in the index — treat as inferred"
- Add supporting detail from Phases 3-4
- Note conflicts or gaps between phases
Label: "✅ Phase 6/6 — Final Answer"

## Phase splits for --phases N
N=2: [discuss+optimize] / [execute + verify + synthesis]
N=3: [discuss+optimize] / [scope + execute] / [verify + synthesis]
N=4: [discuss+optimize] / [scope] / [execute] / [verify + synthesis]
N=6: full pipeline above (default)

After each phase completes, update session file: mark phase [x] with 1-sentence finding.
After Phase 6: set status → completed. Print: "✅ Session complete: <path>"
(If interrupted, run /jsat prompt --continue to resume from the last incomplete phase.)

## Actions File

From Phase 6 synthesis, extract concrete follow-up work:
  - Fixes for ⚠️ unverified claims (look them up and correct the answer)
  - Decisions to log (run /jsat decide log)
  - Knowledge to store (run /jsat knowledge-add)
  - Tests or verification steps recommended

Write ~/.jsat/sessions/prompt-actions-<SLUG>-<YYYYMMDD-HHMM>.md.
Print: "📋 Actions: <path>"

Execute each "- [ ]" action in sequence. Mark [x] as done.
When all done: status → completed. Print: "✅ All actions complete: <path>"

## --single Flag
If --single: classify → optimize → jsat__query(question=<optimized_prompt>) once.
No verification in single mode."""
        ),
        "jsat-prompt-diff": (
            "Show what you typed vs what JSAT sent to the AI after optimization.",
            'Use jsat__prompt_diff with query="$ARGUMENTS" to show the before/after '
            "comparison: raw input vs fully optimized prompt with injected context, "
            "constraints, few-shot examples, and model formatting. "
            "Label one panel 'You sent' and the other 'AI received'."
        ),
        "jsat-tokens": (
            "Count, compress, or check token budget. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call the right token tool:

Supported flags:
  --compress           → call jsat__token_compress with text=<rest>  (apply compression)
  --model <name>       → call jsat__token_budget with text=<rest>, model=<name>
  --budget <model>     → same as --model  (alias)
  (no flag)            → call jsat__token_count with text=<rest>

Examples:
  /jsat-tokens explain the payment service
    → jsat__token_count(text="explain the payment service")

  /jsat-tokens --compress <paste large context here>
    → jsat__token_compress(text="<text>")  → show savings and compressed output

  /jsat-tokens --model gpt-4o <paste context here>
    → jsat__token_budget(text="<text>", model="gpt-4o")  → show % used, headroom, status

  /jsat-tokens --model claude-sonnet-4-6 <paste context>
    → jsat__token_budget(text="<text>", model="claude-sonnet-4-6")

Show: token count, savings (if compressed), budget % used and status (ok/warn/critical)."""
        ),
        "jsat-token-budget": (
            "Check how much of a model's context window a text uses. Supports --model flag.",
            """Parse $ARGUMENTS for optional --model flag:

  --model <name>   → use specified model for limit calculation
  (no flag)        → use current session model (claude-sonnet-4-6[1m] or as configured)

Known model context limits:
  claude-sonnet-4-6[1m]  → 1,048,576 tokens
  claude-sonnet-4-6       → 200,000 tokens
  claude-haiku-4-5        → 200,000 tokens
  gpt-4o                  → 128,000 tokens
  gpt-4o-mini             → 128,000 tokens

Use jsat__token_budget with text=<stripped text> and model=<name>.
Show: tokens used, limit, percentage, headroom, status (ok / warn / critical).
Warn at ≥80%. Flag critical at ≥95%."""
        ),
        "jsat-prompt-rewrite": (
            "Rewrite a prompt using offline pipeline + parallel LLM agents for maximum clarity.",
            'Use jsat__prompt_multi_agent with query="$ARGUMENTS" to run 3 specialist LLM agents '
            "(rewrite for clarity, context-expand to fill gaps, constraint-harden for measurable "
            "success criteria) in parallel. Show the winning rewrite with agent name and score. "
            "If the user wants just one agent, use jsat__prompt_rewrite instead."
        ),
        # ── IThinking ─────────────────────────────────────────────────────────
        "jsat-ithinking": (
            "IThinking meta-cognitive reasoning. Supports subcommands in $ARGUMENTS.",
            """Parse $ARGUMENTS for an optional subcommand, then call the right IThinking tool:

Subcommands:
  plan <task>      → call jsat__ithinking_plan with task=<task>  (phases 0-4, default)
  reflect <done>   → call jsat__ithinking_reflect with subtask=<done>  (phase 6 log)
  audit <task>     → call jsat__ithinking_audit_assumptions with task=<task>
  execute <plan>   → call jsat__ithinking_execute with subtask=<plan>
  estimate <task>  → call jsat__ithinking_token_estimate with task=<task>
  (no subcommand)  → call jsat__ithinking_plan with task=<rest>  (same as plan)

Examples:
  /jsat-ithinking refactor the payment retry logic
    → jsat__ithinking_plan(task="refactor the payment retry logic")

  /jsat-ithinking plan add rate limiting to the checkout API
    → jsat__ithinking_plan(task="add rate limiting to the checkout API")

  /jsat-ithinking reflect completed refactor of PaymentService.process()
    → jsat__ithinking_reflect(subtask="completed refactor of PaymentService.process()")

  /jsat-ithinking audit migrate users table to add nullable column
    → jsat__ithinking_audit_assumptions(task="migrate users table to add nullable column")

  /jsat-ithinking estimate write comprehensive tests for the checkout flow
    → jsat__ithinking_token_estimate(task="write comprehensive tests for the checkout flow")

Display plan clearly. After the user approves, proceed. Then reflect on what was done."""
        ),
        "jsat-think": (
            "Think carefully before acting — IThinking shortcut.",
            'Before doing anything, use jsat__ithinking_plan with task="$ARGUMENTS" '
            "to clarify intent, check assumptions, and decompose the work. "
            "Show the plan and ask for confirmation before proceeding."
        ),
        "jsat-reflect": (
            "Record what was done after completing a task (IThinking phase 6).",
            "Use jsat__ithinking_reflect with subtask=\"$ARGUMENTS\" to log the outcome, "
            "what worked, what didn't, and any follow-up actions."
        ),
        # ── New features ──────────────────────────────────────────────────────
        "jsat-crack": (
            "Multi-agent war room with artifact carry-forward — each agent builds on prior findings.",
            """Parse $ARGUMENTS for optional flags:

  --phases N   → run in N phases (2-6, default: 6)
  --single     → run all agents at once (original one-shot behavior, may timeout)
  --continue   → resume the most recent in_progress crack session
  (no flag)    → 6-phase mode with artifact carry-forward (recommended)

## --continue Flag

When --continue is given:
  1. List ~/.jsat/sessions/crack-*.md; find the most recent with status: in_progress
  2. Read it; extract task and findings from ## Findings as accumulated HANDOFF context
  3. Find first "- [ ]" phase — resume execution from that phase
  4. Print: "▶ Resuming crack session: <filename>"

## Phased Mode (default)

Runs 6 agents sequentially. Each agent receives the original task PLUS a running
brief of all prior agents' key findings — agents build on each other's work
rather than operating in isolation. The skeptic specifically challenges the
architect's and implementer's proposals.

Phase splits (strip --phases flag; task = everything else):
  N=2: [architect,security,implementer] / [tester,skeptic,moderator]
  N=3: [architect,security] / [implementer,tester] / [skeptic,moderator]
  N=4: [architect] / [security,implementer] / [tester,skeptic] / [moderator]
  N=5: [architect] / [security] / [implementer] / [tester,skeptic] / [moderator]
  N=6 (default): one agent per phase — maximum granularity

## Phase 0 — Codebase Context (run before Phase 1)

Call: jsat__get_index_status()
Call: jsat__list_services()
Build CONTEXT_BRIEF from the results: node count, edge count, top service names.
Prepend CONTEXT_BRIEF to every agent's task for grounding.

Create session file: ~/.jsat/sessions/crack-<SLUG>-<YYYYMMDD-HHMM>.md
Content: all 6 phases as unchecked steps in ## Steps, ## Findings empty.
Print: "📄 Session: <path>"

## War Room Phases

### Phase 1 — Architect
Call: jsat__crack(task="<task>\n\nCODEBASE: <CONTEXT_BRIEF>\n\nStructure your response:\n**Findings**: what exists in the codebase relevant to this task\n**Concerns**: top design risk\n**Recommendation**: your proposed approach", roles=["architect"], rounds=1)
Show output under "🏛 Phase 1/6 — Architect".
Extract HANDOFF_1: one sentence — "🏛 Architect: <Recommendation>"
Update session file: "- [ ] Phase 1" → "- [x] Phase 1 (HANDOFF_1)"; append to ## Findings.

### Phase 2 — Security
Call: jsat__crack(task="<task>\n\nCODEBASE: <CONTEXT_BRIEF>\n\nPRIOR FINDINGS:\n<HANDOFF_1>\n\nStructure your response:\n**Findings**: threat surfaces or auth gaps\n**Concerns**: highest-risk issue\n**Recommendation**: required security measure", roles=["security"], rounds=1)
Show output under "🔒 Phase 2/6 — Security".
Extract HANDOFF_2: one sentence — "🔒 Security: <Concerns>"

### Phase 3 — Implementer
Call: jsat__crack(task="<task>\n\nCODEBASE: <CONTEXT_BRIEF>\n\nPRIOR FINDINGS:\n<HANDOFF_1>\n<HANDOFF_2>\n\nStructure your response:\n**Findings**: specific files or functions that need changing\n**Concerns**: implementation difficulty or hidden cost\n**Recommendation**: concrete implementation path", roles=["implementer"], rounds=1)
Show output under "⚙️ Phase 3/6 — Implementer".
Extract HANDOFF_3: one sentence — "⚙️ Implementer: <Recommendation>"

### Mid-Sprint Brief (print after Phase 3, before Phase 4)
  "── Mid-sprint brief ──"
  <HANDOFF_1>
  <HANDOFF_2>
  <HANDOFF_3>
  "── Continuing to tester, skeptic, moderator ──"

### Phase 4 — Tester
Call: jsat__crack(task="<task>\n\nCODEBASE: <CONTEXT_BRIEF>\n\nPRIOR FINDINGS:\n<HANDOFF_1>\n<HANDOFF_2>\n<HANDOFF_3>\n\nStructure your response:\n**Findings**: edge cases and failure modes for the proposed implementation\n**Concerns**: hardest thing to test or verify\n**Recommendation**: test strategy and critical test cases", roles=["tester"], rounds=1)
Show output under "🧪 Phase 4/6 — Tester".
Extract HANDOFF_4: one sentence — "🧪 Tester: <Concerns>"

### Phase 5 — Skeptic (targeted challenger)
Call: jsat__crack(task="<task>\n\nCODEBASE: <CONTEXT_BRIEF>\n\nPRIOR FINDINGS:\n<HANDOFF_1>\n<HANDOFF_2>\n<HANDOFF_3>\n<HANDOFF_4>\n\nYour job: challenge the architect's approach (<HANDOFF_1>) and the implementer's plan (<HANDOFF_3>) specifically. Find the weakest assumption in each. Do NOT give generic concerns — cite the specific proposals above.\n\nStructure your response:\n**Findings**: the weakest assumption in the architect's or implementer's proposal\n**Concerns**: most likely failure mode if this proceeds as planned\n**Recommendation**: what must change or be proven before starting", roles=["skeptic"], rounds=1)
Show output under "😈 Phase 5/6 — Skeptic".
Extract HANDOFF_5: one sentence — "😈 Skeptic: <Concerns>"

### Phase 6 — Moderator
Call: jsat__crack(task="<task>\n\nCODEBASE: <CONTEXT_BRIEF>\n\nFULL WAR ROOM BRIEF:\n<HANDOFF_1>\n<HANDOFF_2>\n<HANDOFF_3>\n<HANDOFF_4>\n<HANDOFF_5>\n\nSynthesize these findings. Make a clear recommendation.", roles=["moderator"], rounds=1)
Show output under "🎯 Phase 6/6 — Moderator".

### Final Synthesis (by you, Claude — no tool call)
Using all 6 phase outputs now in context:
  ✅ Agreed:        items all phases converged on
  ⚠️  Disputed:     live tensions (especially skeptic vs architect/implementer)
  ❓ Open questions: must-answer before starting
  🎯 Action plan:   3-5 concrete next steps

Update session file: status → completed.
Print: "✅ Session complete: <path>"
(If interrupted, run /jsat crack --continue to resume from the last incomplete phase.)

## Actions File

Extract the "🎯 Action plan: 3-5 concrete next steps" from the Final Synthesis.
Write ~/.jsat/sessions/crack-actions-<SLUG>-<YYYYMMDD-HHMM>.md with each step
as a "- [ ]" item (include exact file edits, commands, tests to run, decisions to log).

Print: "📋 Actions: <path>"

Execute each action item in sequence:
  1. Run the action
  2. Mark "- [ ]" → "- [x] (done: <result>)" in the file
  3. Continue to next
When all done: status → completed. Print: "✅ All actions complete: <path>"

## --single Flag
If --single: call jsat__crack(task=<task>) with all defaults (6 agents, 3 rounds).
Note: agents do not receive prior findings in single mode.""",
        ),
        "jsat-short": (
            "Ask any question — get the briefest possible correct answer (≤3 sentences).",
            """Parse $ARGUMENTS for optional --one-line flag:

  --one-line  → request exactly one sentence
  (no flag)   → ≤3 sentences

Use jsat__short with question=<stripped arguments> (or jsat__query if jsat__short unavailable),
prepending the brevity constraint: "Answer in ≤3 sentences, plain language. No preamble."

Show only the AI response — no framing, no metadata.
Use as a fast fallback when /jsat-query times out.""",
        ),
        "jsat-smart": (
            "Terse compression mode — answers in fragments, no filler, code intact. Supports --lite / --full / --ultra.",
            """Terse mode: answer questions about this codebase with maximum compression.
Strip all filler words. Preserve code, function names, file paths, and data byte-for-byte.
Use fragment-based responses — no "In order to", no "It's worth noting", no hedging.

Parse $ARGUMENTS for an optional level flag (strip before processing):
  --lite    → remove filler phrases only (~30% reduction)
  --full    → fragments + no explanatory preamble (~55% reduction, default)
  --ultra   → one bullet per fact, ≤8 words each (~70% reduction)
  (no flag) → full mode

Steps:
1. Strip the level flag; query = all remaining text.
2. Call jsat__query(question=<query>) to get the answer.
3. Compress the answer based on level:
   - lite:  remove phrases like "In order to", "It is worth noting", "As mentioned",
            "Additionally", "It should be noted", "In summary". Keep sentences intact.
   - full:  convert to fragments. "The function does X by calling Y" → "Calls Y → X."
            Remove all preamble ("Here is...", "Let me explain...").
   - ultra: one bullet per fact. ≤8 words each. No connectives.
4. Output only the compressed answer. No preamble. No "Here is the compressed answer:".

Examples:
  /jsat-smart what does the payment service do?
    → full mode: fragment bullets, no filler

  /jsat-smart --ultra what does process_refund return?
    → single bullets, ≤8 words each

  /jsat-smart --lite explain the checkout flow
    → filler phrases stripped, sentence structure preserved""",
        ),
        "jsat-lazy": (
            "Reuse-first code planning — runs a 5-rung ladder against the graph before suggesting new code.",
            """Before writing any new code, run the reuse ladder to find what already exists.
Rule: the best code is code you don't write. The graph index is the source of truth.

Parse $ARGUMENTS for optional flags:
  --audit   → scan a diff/file for over-engineering (code that reimplements existing)
  --review  → check a proposed implementation against the graph for duplication
  (no flag) → run the full reuse ladder for the given task description

## Reuse Ladder (run rungs in order — stop as soon as one finds a match)

RUNG 1 — Exact function/class match
  Extract the key function or class name implied by the task.
  Call: jsat__get_function(name=<key_term>)
  If found: show file:line, signature, and say "✅ Already exists — reuse this."

RUNG 2 — Similar pattern in the codebase
  Call: jsat__query(question="find existing implementation for: <task>")
  If the answer names specific functions/files: show them.
  Say "✅ Reuse this pattern from <file>:<line>."

RUNG 3 — Existing service already handles this domain
  Call: jsat__list_services()
  Check if any service name matches the task domain.
  If found: say "✅ Delegate to <ServiceName> instead of building new."

RUNG 4 — Existing endpoint already exposes this
  Call: jsat__list_endpoints()
  Check if a route or method matches the needed operation.
  If found: say "✅ Call existing endpoint <METHOD> <route> instead."

RUNG 5 — Nothing found: minimum viable implementation
  Only reach this rung if rungs 1-4 all return empty.
  Suggest the minimum code:
  - One function, not a class
  - No abstraction layers
  - No config flags for hypothetical future use
  Say: "⚠️ Nothing found in codebase. Minimum implementation:" then show it.

## --audit flag
Given a diff or file path: scan for code that reimplements something already in the graph.
Call jsat__blast_radius(target=<path>) to find what already handles this area.
Call jsat__get_function for each new function name found in the diff.
Flag any that duplicate existing indexed functions.

## --review flag
Given a proposed implementation description: check each function/class name against the graph.
For each named entity: call jsat__get_function(name=<fn>) or jsat__get_class(name=<cls>).
Report: exists / not found / similar match (with location).""",
        ),
        "jsat-plan": (
            "Pre-implementation planning — six forcing questions + scope/architecture/security review before writing code.",
            """Pre-implementation planning gate. Before writing any code, surface assumptions, scope risks, and architectural concerns.

Parse $ARGUMENTS for optional flags:
  --scope          → scope review only: what to build and why
  --architecture   → architecture review: how to build it
  --security       → security review: what can go wrong
  --full           → run all three perspectives (default)
  (no flag)        → full three-perspective review

## Six Forcing Questions (always run first)

Before any perspective review, answer these six questions from the task description and graph context:
  1. What is the exact problem being solved?
  2. Who experiences this problem and how often?
  3. What is the cost of NOT solving it?
  4. What already exists in the codebase that partially handles this?
  5. What is the minimum change that would solve it?
  6. What is the hardest part — and what assumption am I making about it?

Call: jsat__ithinking_audit_assumptions(task=<task>)
Call: jsat__query(question="what exists in the codebase related to: <task>") to answer question 4.
Label: "🔍 Forcing Questions"

## Scope Perspective (--scope or --full)
Classify the task: full scope / reduced scope (cut what loses no core value) / expanded scope (what adjacent improvement would compound value?).
Call: jsat__blast_radius(target=<most relevant file or symbol from Q4>)
Show: recommended scope with reason. Label: "📐 Scope"

## Architecture Perspective (--architecture or --full)
Evaluate the implementation approach:
  - What existing patterns should this follow? (from graph context)
  - What data flows are affected? (from blast-radius above)
  - What are the 2 most likely failure modes?
  - One-line flow: input → transformation → output
Label: "🏗 Architecture"

## Security Perspective (--security or --full)
Flag risks before implementation:
  - What user inputs reach this code path?
  - What external calls or side effects are involved?
  - What is the blast radius if this function behaves unexpectedly?
Call: jsat__get_auth_coverage() if auth is relevant.
Label: "🔒 Security"

## Output
Print a one-page planning brief:
  Decision: build as described / reduce scope / defer / delegate
  Architecture: <one-line approach>
  Top risk: <one-line>
  First step: <specific file or function to change first>""",
        ),
        "jsat-decide": (
            "Decision journal — log architectural decisions and surface them by file, topic, or blast-radius context.",
            """Architectural decision journal. Log decisions with context; retrieve them when analyzing impact or planning changes.

Parse $ARGUMENTS for optional subcommand:
  log <text>               → store a decision
  log --impact h|m|l <text> → store with impact rating (high/medium/low)
  list                     → show all decisions (recent first)
  list <category>          → filter by category
  search <query>           → semantic search across decisions
  context <file_or_symbol> → show decisions relevant to this file or function
  (no subcommand)          → same as search <rest>

## log subcommand
Store the decision in the knowledge base with structured context:
Call: jsat__knowledge_add(
  text="DECISION: <text> | Impact: <impact> | Date: today",
  category="decision"
)
Confirm with ID and 1-line preview.

## context subcommand
Find decisions relevant to a file or function:
  Call: jsat__blast_radius(target=<file_or_symbol>) to find connected nodes
  Call: jsat__knowledge_search(query="decision related to <file_or_symbol>")
  Show decisions whose scope overlaps with the blast-radius output.

## search subcommand
  Call: jsat__knowledge_search(query=<query>)
  Show matching decisions with date, impact, and text.

## list subcommand
  Call: jsat__knowledge_list(category="decision")
  Show all decisions sorted by recency.

Examples:
  /jsat decide log Switched caching from Redis to in-memory — cost $500/month, latency acceptable
  /jsat decide log --impact h Chose PostgreSQL over MongoDB for ACID compliance on payment records
  /jsat decide context src/payments/service.py
  /jsat decide search caching strategy""",
        ),
        "jsat-sprint": (
            "Seven-stage delivery workflow — Think → Plan → Build → Review → Test → Ship → Reflect, each stage fast and focused.",
            """Seven-stage sprint workflow for structured project delivery. Each stage runs focused JSAT tools and passes findings forward.

Parse $ARGUMENTS:
  --stage <1-7>    → resume from a specific stage (skip earlier stages)
  --dry            → show the sprint plan without running any tools
  --continue       → resume most recent in_progress sprint session
  (no flag)        → run all 7 stages sequentially

## --continue Flag

When --continue is given:
  1. List ~/.jsat/sessions/sprint-*.md; find most recent with status: in_progress
  2. Read it; find first "- [ ]" stage; carry ## Findings as context
  3. Print: "▶ Resuming sprint: <filename>"
  4. Resume from that stage

Stage map:
  1. Think   — clarify intent and surface assumptions
  2. Plan    — forcing questions + scope/architecture/security review
  3. Build   — find what exists, map impact scope
  4. Review  — multi-model code review of affected areas
  5. Test    — find test gaps, generate missing cases
  6. Ship    — breaking blast-radius check before release
  7. Reflect — log decisions and outcomes

## Stage execution

### Session File (before Stage 1)
Create ~/.jsat/sessions/sprint-<SLUG>-<YYYYMMDD-HHMM>.md with all 7 stages as unchecked steps.
Print: "📄 Session: <path>"

### Stage 1 — Think (~10s)
Call: jsat__ithinking_plan(task=<task>)
Extract clarified intent in 1 sentence. Label: "🧠 Stage 1/7 — Think"
Update session file: mark Stage 1 [x] with 1-sentence outcome.

### Stage 2 — Plan (~20s)
Call: jsat__ithinking_audit_assumptions(task=<task>)
Call: jsat__query(question="what already handles: <task>")
Summarize: what exists, what's new, top assumption. Label: "📋 Stage 2/7 — Plan"

### Stage 3 — Build (~15s)
Call: jsat__get_function(name=<key function implied by task>)
Call: jsat__blast_radius(target=<most relevant file or function>)
Show: what to change and what it affects. Label: "🔨 Stage 3/7 — Build"

### Stage 4 — Review (~20s)
Call: jsat__get_review_findings() if a recent review exists
Otherwise: jsat__query(question="code quality or design issues in <relevant area>")
Label: "👁 Stage 4/7 — Review"

### Stage 5 — Test (~20s)
Call: jsat__get_test_gaps(path=<relevant path>)
Show top 3 uncovered paths. Label: "🧪 Stage 5/7 — Test"

### Stage 6 — Ship (~10s)
Call: jsat__blast_radius(target=<changed file or function>)
Filter to breaking impacts only. Flag any before proceeding.
Label: "🚢 Stage 6/7 — Ship"

### Stage 7 — Reflect (~5s)
Call: jsat__ithinking_reflect(subtask="<task> — sprint completed")
Prompt: "Log key decision? Run: /jsat decide log <decision>"
Label: "🔮 Stage 7/7 — Reflect"

### Final Summary
  ✅ Stages completed: N/7
  🚢 Ship readiness: yes/no (Stage 6 broke nothing → yes)
  📝 Decisions to log: <architectural choices made during sprint>

Update session file: status → completed.
Print: "✅ Session complete: <path>"
(If interrupted, run /jsat sprint --continue to resume from the last incomplete stage.)

## Actions File

From sprint outcomes, extract concrete remaining work:
  - Decisions to log (from Stage 7 Reflect)
  - Test gaps to fill (from Stage 5 Test)
  - Breaking changes to fix before shipping (from Stage 6 Ship)
  - Any code changes identified but not yet implemented

Write ~/.jsat/sessions/sprint-actions-<SLUG>-<YYYYMMDD-HHMM>.md.
Print: "📋 Actions: <path>"

Execute each "- [ ]" action in sequence. Mark [x] as done.
When all done: status → completed. Print: "✅ All actions complete: <path>"
"""
        ),
        "jsat-cohesion": (
            "File and function cohesion analysis — flags oversized files, high complexity, and mixed responsibilities.",
            """Analyze the codebase for cohesion problems: oversized files, high-complexity functions, and mixed responsibilities.

Parse $ARGUMENTS for optional flags:
  --service <name>    → scope to one service
  --threshold <N>     → flag files with more than N lines (default: 800)
  --functions         → show function-level analysis only (no file-level)
  (no flag)           → full cohesion report for path=<rest or ".">

## What it checks

Files:
  - Lines > 800 (default threshold) → likely need extraction
  - Multiple unrelated responsibilities → split into focused modules

Functions:
  - Cyclomatic complexity > 10 → likely needs simplification
  - Lines > 150 → likely doing too much
  - High outgoing edges in blast-radius (calls many unrelated things)

## How it works

Call: jsat__get_index_status() for graph overview
Call: jsat__query(question="which files are largest and most complex in the codebase?")
Call: jsat__get_test_gaps(path=<path>) to correlate complexity with test coverage gaps

For the top findings, cross-reference with blast-radius to identify which large files
have the highest downstream impact (most urgent to refactor).

## Output format

📊 **Cohesion Report**

  🔴 HIGH priority (extract or split):
    <file> — <N> lines, complexity <X> — suggest extracting: <function names>

  🟡 MEDIUM priority (schedule refactor):
    <file> — <N> lines, complexity <X>

  ✅ Healthy: <N> files within thresholds

  Top recommendation: <one specific first action — most impactful>

TIMEOUT STRATEGY: For large repos, scope with --service <name> to avoid timeout.""",
        ),
        "jsat-magic": (
            "AI-orchestrated skill composer — analyzes any task and dynamically selects, orders, and runs the optimal JSAT skills to complete it.",
            """Analyze the task, compose the optimal JSAT skill sequence from the full catalog,
run each skill adaptively, and converge when the task is complete.

Parse $ARGUMENTS for optional flags:
  --depth quick     → cap at 4 skills (fast pass, breadth-first)
  --depth standard  → cap at 8 skills (default, balanced)
  --depth deep      → cap at 15 skills (comprehensive)
  --budget N        → explicit cap on skill invocations
  --service <name>  → scope all skills to one service (avoids timeout)
  --preview         → compose plan only, do NOT run any skills
  --continue        → resume the most recent in_progress magic session
  (no flag)         → standard depth, auto-scoped

## --continue Flag

When --continue is given:
  1. List files in ~/.jsat/sessions/ matching magic-*.md
  2. Find the most recent file with "status: in_progress" in its frontmatter
  3. Read it and print: "▶ Resuming: <filename>"
  4. Extract task from frontmatter; extract findings from ## Findings as accumulated context
  5. Find first "- [ ]" step — resume execution from there
  6. Skip all "- [x]" steps (already done)
  7. Continue with Step 3 execution, carrying findings as prior context

## Step 1 — Analyze the task

Read the task description and extract:
  - WHAT: what is being asked? (question / change / investigation / decision)
  - WHERE: specific files, functions, services, or broad scope?
  - RISK: does this involve security, data, production, or breaking changes?
  - DEPTH: how complete an answer is needed?

## Step 2 — Compose the skill sequence

Select skills from this layered catalog, ordered by information dependency.
Select only what the task genuinely needs — minimum sufficient set.
Prefer narrow fast skills before heavy ones (crack, sprint only if genuinely complex).

  LAYER 0 — Context (always run):
    status, list-services

  LAYER 1 — Discover (when task names symbols or asks where/what/how):
    find-function, find-class, trace, query, smart, short, recent, list-endpoints

  LAYER 2 — Analyze (when task involves risk, impact, quality, or incidents):
    blast-radius, security, test-gaps, coverage, contract, cohesion, migration, incident

  LAYER 3 — Plan (when task involves building, deciding, or designing):
    lazy, plan, think, crack, decide, knowledge

  LAYER 4 — Execute (when task involves implementing or reviewing):
    review, prompt, sprint

  LAYER 5 — Verify (after execution, before shipping):
    test-gaps --generate, blast-radius --severity breaking

  LAYER 6 — Record (at end, for operational or architectural work):
    decide log, reflect, knowledge-add, runbook

If --service was given, scope all Layer 1-5 skills to that service.

Announce the composed plan before running:
  "✨ Magic Plan (<N> skills, <depth> depth):"
  "  Layer 0: status → list-services"
  "  Layer 1: <selected discover skills with params>"
  "  Layer 2: <selected analyze skills>"
  (only list layers that have selected skills)

If --preview: STOP here, do not run any tools.

## Session File

Before running any skills, create the session directory and file:

  mkdir -p ~/.jsat/sessions/
  SLUG = first 4 words of task, lowercased, spaces→hyphens
  FILE = ~/.jsat/sessions/magic-<SLUG>-<YYYYMMDD-HHMM>.md

Write the file:
  ---
  skill: magic
  task: <original task>
  created: <current datetime>
  status: in_progress
  ---

  ## Steps
  - [ ] <each selected skill, one line each>

  ## Findings
  (populated as steps complete)

Print: "📄 Session: ~/.jsat/sessions/<filename>"

## Step 3 — Execute adaptively

For each selected skill in layer order:
  1. Print: "▶ [Layer N] <skill> — <what it checks for this specific task>"
  2. Call the corresponding JSAT MCP tool with task-specific parameters
  3. Show result under: "✅ <skill>: <1-sentence finding>"
  4. ADAPT: if the finding reveals new information needs, add skills from later layers
     (example: blast-radius shows breaking changes → add test-gaps --generate to Layer 5)
  5. CONVERGE: if the task is now answerable with high confidence, skip remaining skills
     and jump to synthesis. Print: "⚡ Converged at step N/M — sufficient to answer."
  6. Update session file: change "- [ ] <skill>" → "- [x] <skill> (finding: <1-sentence>)"
     and append to ## Findings: "**<skill>:** <1-sentence finding>"

Timeout handling: if any skill returns "[AI unavailable]" or times out:
  - Retry with --service <most relevant service> to narrow scope
  - Or skip and note: "(timed out — answer based on available data)"

## Step 4 — Synthesize

  ✨ **Magic Summary**
  - Task: <original task>
  - Skills used: <N of planned>
  - Key findings: <one bullet per skill with useful data>
  - Answer: <direct, complete answer to the task>
  - Actions: <1-3 concrete next steps>
  - Log a decision? <yes/no — if yes: /jsat decide log <decision>>
  - Record outcome? <yes/no — if yes: /jsat reflect <outcome>>

Update session file frontmatter: status → completed.
Print: "✅ Session complete: ~/.jsat/sessions/<filename>"
(If interrupted before this step, run /jsat magic --continue to resume.)

## Actions File

Extract every concrete action from the summary above (commands to run, files
to edit with line:column, tests to verify, commits to make). Write:
  ~/.jsat/sessions/magic-actions-<SLUG>-<YYYYMMDD-HHMM>.md

File format:
  ---
  skill: magic
  task: <original task>
  generated: <datetime>
  status: pending
  ---
  ## Action Items
  - [ ] <exact command or file edit>  — <why>
  ...
  ## Completed Actions
  (empty)

Print: "📋 Actions: <path>"

Now read that file and execute each "- [ ]" action in sequence:
  1. Execute the action (run command, edit file, install package, etc.)
  2. Update the file: "- [ ]" → "- [x] (done: <result>)"
  3. Append to ## Completed Actions: "<action>: <result>"
  4. Continue to next action

When all actions are done: set status → completed in the actions file.
Print: "✅ All actions complete: <path>"
""",
        ),
        "jsat-aw": (
            "Workflow advisor — classifies your task and runs the optimal JSAT tool sequence end-to-end.",
            """Given a task in $ARGUMENTS, act as a JSAT workflow advisor.
Classify the task, announce the recommended tool sequence, then run each step.

## Step 1 — Classify task type

Read the task description and identify the type:

  feature    → adding new functionality to the codebase
  bugfix     → fixing broken or incorrect behavior
  security   → security audit, hardening, or vulnerability check
  understand → exploring or learning how existing code works
  incident   → investigating a production issue or alert
  refactor   → improving existing code without changing behavior
  review     → reviewing a diff or PR before merge

If the type is unclear, default to "understand".

## Step 2 — Announce the workflow

Show the recommended sequence before running anything:

  feature:   jsat-lazy → jsat-find-function → jsat-blast-radius → jsat-crack → jsat-test-gaps
  bugfix:    jsat-recent → jsat-incident → jsat-find-function → jsat-blast-radius
  security:  jsat-security → jsat-blast-radius --severity breaking → jsat-crack --phases 3 → jsat-knowledge-add
  understand:jsat-smart → jsat-trace → jsat-find-function → jsat-query
  incident:  jsat-incident → jsat-recent → jsat-blast-radius → jsat-runbook
  refactor:  jsat-lazy → jsat-blast-radius → jsat-test-gaps → jsat-crack → jsat-review
  review:    jsat-review → jsat-blast-radius --severity breaking → jsat-test-gaps --untested

Print before running:
  "📋 Task type: <type>"
  "🔄 Workflow (<N> steps): step1 → step2 → ..."

## Step 3 — Execute each step in sequence

For each step:
  1. Invoke the JSAT MCP tool that corresponds to the skill, passing the task description
     (or the most relevant part) as the argument. Apply any flags shown in the workflow.
  2. Show the result under the header "✅ Step N/M — <skill-name>".
  3. Extract the key finding in 1 sentence.
  4. Carry that finding forward as additional context to the next step where useful.
  5. Before each step, print: "▶ Step N/M — <skill-name>: <what it checks>"

## Step 4 — Final summary

After all steps complete, produce:

  📊 **Workflow Summary**
  - Task: <original task>
  - Type: <classified type>
  - Steps run: <N>
  - Key findings: <one bullet per step>
  - Recommended action: <1-2 concrete next steps>
  - Save to knowledge base: <yes/no — if yes, use jsat-knowledge-add>

## Flags

  --type <type>   → skip classification, force a specific workflow type
  --dry           → show the workflow plan only, do NOT run any tools
  (no flag)       → classify + run full workflow

Examples:
  /jsat-aw add idempotency keys to the payment mutation endpoint
    → classifies as "feature": lazy → find-function → blast-radius → crack → test-gaps

  /jsat-aw --type security src/auth/
    → skips classification, runs security workflow on src/auth/

  /jsat-aw --dry investigate the checkout 500 errors from this morning
    → prints the "incident" workflow plan without executing anything""",
        ),
        "jsat-help": (
            "Show flags, params, and examples for any /jsat command. No args = full command list.",
            """/jsat-help <command>

No args → print a one-liner table of all 39 commands and stop.
With a command name → print that command's full description, all flags, and examples.

Examples:
  /jsat-help              → list all available commands with one-liner descriptions
  /jsat-help magic        → full explanation of magic: flags, depth levels, examples
  /jsat-help crack        → phases, --single, --continue, phase-split table
  /jsat-help blast-radius → --file/--diff/--symbol/--severity flags and examples""",
        ),
}

# Appended to every generated command so the assistant delivers a real answer
# instead of stopping at raw tool output. Without this, some tools (especially
# ones that return an intermediate artifact like an optimized prompt or a JSON
# blob) get echoed verbatim, which reads as "just showing what the tool does".
_JSAT_CMD_DIRECTIVE = (
    "\n\nHOW TO RESPOND: Actually invoke the tool(s) described above, then reply "
    "with a direct, useful answer built from the result — interpret it for the "
    "user in plain language. Do not merely describe what the tool does, and do "
    "not echo raw JSON. If a tool returns an intermediate artifact (e.g. an "
    "optimized prompt), use it to finish the task rather than presenting it as "
    "the final answer."
)


def _write_jsat_skills(scope: str, commands_dir: Path | None = None) -> Path:
    """Write /jsat-* skill files so Claude Code can call JSAT tools via slash commands."""
    if commands_dir is None:
        if scope == "global":
            commands_dir = Path.home() / ".claude" / "commands"
        else:
            commands_dir = Path.cwd() / ".claude" / "commands"

    commands_dir.mkdir(parents=True, exist_ok=True)

    for name, (description, instruction) in _JSAT_SKILLS.items():
        skill_file = commands_dir / f"{name}.md"
        content = f"---\ndescription: {description}\n---\n\n{instruction}{_JSAT_CMD_DIRECTIVE}\n"
        skill_file.write_text(content, encoding="utf-8")

    return commands_dir


def _write_jsat_dispatcher(scope: str, commands_dir: Path | None = None) -> Path:
    """Write a single /jsat dispatcher sourced from the bundled jsat/commands/*.md files.

    Reads the actual skill files from jsat/commands/ so updates to those files are
    automatically reflected when 'jsat connect claude' is re-run.
    """
    if commands_dir is None:
        if scope == "global":
            commands_dir = Path.home() / ".claude" / "commands"
        else:
            commands_dir = Path.cwd() / ".claude" / "commands"

    commands_dir.mkdir(parents=True, exist_ok=True)

    # Remove any existing individual jsat-*.md files
    for old in commands_dir.glob("jsat-*.md"):
        old.unlink()

    # Locate the bundled skill files: jsat/commands/jsat-*.md
    pkg_commands_dir = Path(__file__).parent / "commands"
    skill_files = sorted(pkg_commands_dir.glob("jsat-*.md"))

    def _frontmatter_desc(text: str) -> str:
        """Extract description: value from YAML frontmatter."""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("description:"):
                return line.removeprefix("description:").strip().strip('"')
        return ""

    def _strip_frontmatter(text: str) -> str:
        """Remove the leading ---...--- frontmatter block."""
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return text
        try:
            end = lines.index("---", 1)
            return "\n".join(lines[end + 1:]).lstrip("\n")
        except ValueError:
            return text

    # Build help table
    lines: list[str] = [
        "---",
        "description: \"JSAT — /jsat <command> [flags] [args]. Type '/jsat help' for all commands.\"",
        "---",
        "",
        "Parse the first word of $ARGUMENTS as COMMAND; everything after is ARGS.",
        "Find the matching section below and execute its instructions, treating ARGS as $ARGUMENTS.",
        "If COMMAND is \"help\" or $ARGUMENTS is empty: print the command list and stop.",
        "",
        "---",
        "## help",
        "",
        "| Command | Description |",
        "|---------|-------------|",
    ]
    for fpath in skill_files:
        short = fpath.stem.removeprefix("jsat-")
        desc = _frontmatter_desc(fpath.read_text(encoding="utf-8"))
        lines.append(f"| `/jsat {short}` | {desc} |")

    lines += ["", "---", ""]

    # Embed each skill file's body as a named section
    for fpath in skill_files:
        short = fpath.stem.removeprefix("jsat-")
        content = fpath.read_text(encoding="utf-8")
        desc = _frontmatter_desc(content)
        body = _strip_frontmatter(content)
        lines += [
            f"## {short}",
            "",
            f"*{desc}*" if desc else "",
            "",
            body.rstrip(),
            "",
            "---",
            "",
        ]

    (commands_dir / "jsat.md").write_text("\n".join(lines), encoding="utf-8")
    return commands_dir


def _write_bob_commands(scope: str, commands_dir: Path | None = None) -> Path:
    """Write /jsat-* slash commands so Bob Shell can call JSAT tools.

    Bob reads markdown commands from .bob/commands/ (project) or ~/.bob/commands/
    (global); the filename becomes the command name. Bob uses shell-style
    argument placeholders, so the $ARGUMENTS used by the Claude skills is
    rewritten to $@ ("all arguments"), and an argument-hint is added when the
    command takes input.
    """
    if commands_dir is None:
        if scope == "global":
            commands_dir = Path.home() / ".bob" / "commands"
        else:
            commands_dir = Path.cwd() / ".bob" / "commands"

    commands_dir.mkdir(parents=True, exist_ok=True)

    def _yaml_dq(s: str) -> str:
        """Double-quote a value for YAML frontmatter. Bob parses frontmatter as
        strict YAML, so descriptions containing ':' etc. must be quoted."""
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    for name, (description, instruction) in _JSAT_SKILLS.items():
        body = instruction.replace("$ARGUMENTS", "$@") + _JSAT_CMD_DIRECTIVE
        # Menu descriptions read better with a plain word than the raw token.
        desc = description.replace("$ARGUMENTS", "arguments")
        hint = f"\nargument-hint: {_yaml_dq('<arguments>')}" if "$@" in body else ""
        content = f"---\ndescription: {_yaml_dq(desc)}{hint}\n---\n\n{body}\n"
        (commands_dir / f"{name}.md").write_text(content, encoding="utf-8")

    return commands_dir
