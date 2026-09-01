---
description: Terse compression mode — answers in fragments, no filler, code intact. Supports --lite / --full / --ultra.
---

Terse mode: answer questions about this codebase with maximum compression.
Strip all filler words. Preserve code, function names, file paths, and data byte-for-byte.
Use fragment-based responses — no "In order to", no "It's worth noting", no hedging.

Parse $ARGUMENTS for an optional level flag (strip before processing):
  --lite    → remove filler phrases only (~30% reduction)
  --full    → fragments + no explanatory preamble (~55% reduction, default)
  --ultra   → one bullet per fact, ≤8 words each (~70% reduction)
  (no flag) → full mode

If more than one level flag is present in $ARGUMENTS (e.g. "--lite --ultra
explain X"), this is ambiguous, not additive — the three levels are mutually
exclusive compression strategies (phrase-stripping vs fragments vs bullets),
not stackable passes. Do not silently apply the first one found or chain them.
Use the MOST aggressive one specified (--ultra > --full > --lite) and strip
all level flags from the query text, since that's the safer failure mode for
a "maximum compression" command — under-compressing loses less than a user
discovering their explicit --ultra was silently downgraded to --lite.

Steps:
1. Strip the level flag; query = all remaining text. If nothing remains after
   stripping flags, stop and ask for a question — do not call jsat__query("").
2. Call jsat__query(question=<query>) to get the answer.
   CHECK FIRST: jsat__query needs a working LLM backend and returns
   "[AI unavailable: ..." when the provider is down — a common failure mode,
   not a rare edge case. If the response matches that pattern, STOP before
   step 3: do not compress it. An error string run through the "fragments,
   ≤8 words, no connectives" compressor would come out looking like a normal
   terse answer (e.g. a bullet reading "AI unavailable ollama down") and could
   be mistaken for a real, compressed response to the user's actual question.
   Instead report plainly, uncompressed: "AI backend unavailable — cannot
   answer '<query>' right now. Check the provider (e.g. `jsat doctor`)."
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
    → filler phrases stripped, sentence structure preserved


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
