---
description: File and function cohesion analysis — flags oversized files, high complexity, and mixed responsibilities.
---

Analyze the codebase for cohesion problems: oversized files, high-complexity functions, and mixed responsibilities.

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

FALLBACK if jsat__query returns "[AI unavailable" (a down/unconfigured AI provider
takes the whole tool with it — this is common, not a rare edge case): jsat__query is
only the primary DISCOVERY step here, so replace it with pure graph/Bash lookups:
  1. File size, AI-free: Bash `find <path> -type f \( -name "*.py" -o -name "*.js"
     -o -name "*.ts" -o -name "*.go" ... \) -exec wc -l {} +`, sorted descending —
     this alone gives the "oversized files" half of the report with zero AI.
  2. Complexity, AI-free: for the top N files from step 1, enumerate their top-level
     functions/classes (`grep -n "^def \|^class \|^function "` or the language
     equivalent), then call jsat__get_function(name=<fn>) per candidate — it returns
     complexity directly and does not need the AI backend. This is slower (one call
     per function) than the single jsat__query call, so cap it to the top ~15-20
     files by size to stay within budget.
  Mark results produced this way as "Bash/graph-enumerated (AI backend unavailable)"
  in the report so the user knows it wasn't a single graph-native semantic lookup.

For the top findings — cap this at the top 10 by file size/complexity, whether from a
single unscoped pass or the globally-sorted pool from the LARGE-SCOPE STRATEGY above
— cross-reference with blast-radius (jsat__blast_radius(target=<file>)) to identify
which large files have the highest downstream impact (most urgent to refactor). Do
not run this cross-reference against every flagged file; it's one call per file and
exists to rank the already-identified top findings, not to re-scan the whole set.

LARGE-SCOPE STRATEGY: this command is read-heavy — get_test_gaps and the per-function
complexity fallback both scale with repo size. For a repo with more than ~150 files
or ~50k lines in scope, do not run an unscoped full-repo pass:
  1. Call jsat__list_services() first and process one service at a time (this is
     exactly what --service is for — use it proactively rather than waiting for a
     timeout).
  2. Within a very large single service, further scope by top-level directory and
     process chunk by chunk.
  3. Aggregating ONLY the HIGH/MEDIUM/healthy counts across chunks is not enough —
     the "top findings" cross-reference below and the final "Top recommendation"
     both need to name a specific file, and a count has no identity. Per chunk, keep
     the actual top ~10 flagged file records (path, lines, complexity, category),
     not just how many fell into each bucket. After all chunks finish, merge those
     per-chunk top-10 lists into one pool and re-sort it globally by severity/size to
     get the true cross-repo top findings — a file that's #3 in a small chunk but
     would be #40 repo-wide must not out-rank a file that's #1 in a large chunk. Use
     this globally-sorted list (not a chunk-local one) for both the blast-radius
     cross-reference step below and the final recommendation.

## Output format

📊 **Cohesion Report**

  🔴 HIGH priority (extract or split):
    <file> — <N> lines, complexity <X> — suggest extracting: <function names>

  🟡 MEDIUM priority (schedule refactor):
    <file> — <N> lines, complexity <X>

  ✅ Healthy: <N> files within thresholds

  Top recommendation: <one specific first action — most impactful>

BUDGET STRATEGY: For large repos, scope with --service <name> to stay within budget.
  Override budget: /jsat cohesion timeout=120 --service payments
  ⏱ progress notification = still running (wait or skip). ⛔ _hard_timeout = retry with --service.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
