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
    → filler phrases stripped, sentence structure preserved

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
