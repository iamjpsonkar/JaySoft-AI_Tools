---
description: Multi-model code review. Supports flags in $ARGUMENTS.
---

Parse $ARGUMENTS for optional flags, then call the right review tool:

Supported flags:
  --findings        → call jsat__get_review_findings to show results of last review
  --bugs            → call jsat__get_high_confidence_bugs to list confirmed bugs only
  --min high        → filter to high-confidence findings only (applies to whichever
                      of the above ran; strip BOTH "--min" and its value token
                      before treating anything left over in $ARGUMENTS as a diff —
                      a naive strip of just "--min" would leak the literal word
                      "high"/"medium" into the diff text passed to submit_for_review)
  --min medium      → filter to medium+ (default)
  (no flag)         → call jsat__submit_for_review with diff=<rest>

If no flag matched and $ARGUMENTS is empty after stripping BUDGET flags: stop and
ask the user to paste a diff — do not call jsat__submit_for_review(diff="") and
silently review nothing.

Examples:
  /jsat-review <paste diff here>
    → jsat__submit_for_review(diff="<diff>")

  /jsat-review --findings
    → jsat__get_review_findings()

  /jsat-review --bugs
    → jsat__get_high_confidence_bugs()

  /jsat-review --bugs --min high
    → jsat__get_high_confidence_bugs() filtered to high-confidence only

Show findings grouped by confidence: high → medium → low.
Highlight bugs confirmed by 2+ models.

SINGLE-PROVIDER CAVEAT: "confirmed by 2+ models" assumes jsat__submit_for_review
actually dispatched to multiple distinct LLM providers/models. A median setup
may have only ONE provider configured (e.g. just Ollama, or just one API key) —
in that case every finding comes from a single model appearing once, the "2+"
threshold can never be met, and nothing will ever be labeled "confirmed" even
when the review ran cleanly and found real bugs. This is a configuration
ceiling, not a sign the review failed or that the code is clean. Before
reporting "0 confirmed bugs" as if it means "nothing serious found", check how
many distinct models actually responded (jsat__get_review_findings /
jsat__submit_for_review's response should list reviewer identities) — if only
one responded, say so explicitly ("only 1 model configured — 'confirmed by 2+'
cannot trigger; treat single-model high-confidence findings as the strongest
signal available instead") rather than silently presenting an empty confirmed
list as a clean bill of health.

jsat__submit_for_review runs multiple LLM reviewers, so it needs a working AI
backend — same failure mode as jsat__query ("[AI unavailable: ..." when the
provider is down, which is common, not rare). If submit_for_review reports AI
unavailable: do not retry it silently or report "no findings". Fall back to
jsat__blast_radius_diff(diff=<diff>) plus jsat__security_review(path=<changed
paths>) — both are pure graph/static analysis with no LLM dependency — and
present their output explicitly labeled as "structural + security signal only,
not a full multi-model review" so the user knows the review is degraded, not clean.

LARGE DIFF STRATEGY: For diffs >500 lines, split by file and review in chunks:
  /jsat-review <first file's diff>   then   /jsat-review <next file's diff>
Then run /jsat-review --bugs to see cross-chunk high-confidence findings.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
