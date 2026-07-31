---
description: Workflow advisor — classifies your task and runs the optimal JSAT tool sequence end-to-end.
---

Given a task in $ARGUMENTS, act as a JSAT workflow advisor.
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
    → prints the "incident" workflow plan without executing anything

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
