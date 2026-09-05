# JSAT — Feature Inventory

Every user-facing feature of JSAT, where it lives, what it takes, and which AI
tools it works with. Compiled from the **0.4.20** worktree (`main`, unreleased)
from the live CLI help, the MCP registry, and the skills registry.

JSAT exposes one core (index → graph → queries) through **three surfaces**:

| Surface | Count | Registry |
|---|---|---|
| CLI commands (top-level) | 42 | `jsat/_cli_*.py` |
| MCP tools (any connected AI) | 69 | `jsat/mcp/server.py:_build_registry()` |
| Slash commands / skills | 47 (46 + help) | `jsat/commands/jsat-*.md` |
| AI tool integrations | 11 | `jsat/_cli_connect.py`, `jsat/_cli_launchers.py` |

A feature usually appears on more than one surface. The four tables below are
the same feature set from four angles:

- **§1 AI integration matrix** — how JSAT plugs into each AI tool (launcher,
  connector, skills, review, etc.). This is the per-AI presence table.
- **§2 CLI commands** — everything `jsat …` accepts, with its source file.
- **§3 MCP tools** — every `jsat__*` tool plus the arguments/graph it resolves.
- **§4 Slash commands & skills** — the `/jsat-*` skills that get installed into
  AI tools on connect.

> **Rendering note.** Long cells use `<br>` for wrapped multi-line text. Some
> rows are still wide in raw source — that is inherent to markdown tables.

Legend for presence cells: **✓** supported · **→** as that tool itself
· **✗** not present · **·** no MCP surface (JSAT-shell / API provider only).

---

## §1 AI integration matrix

How each AI tool is wired into JSAT. Each row is one integration affordance;
the columns say whether that affordance exists for that AI. `GPT`/`Ollama` are
JSAT-shell sessions (JSAT is the provider), not external MCP clients, so several
affordances don't apply.

| # | Feature | Args | Path | Claude | Codex | OpenCode | Bob | GPT | Ollama | Gemini | Cursor | Windsurf | Zed | Continue |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Launcher** — `jsat <tool>` | `--repo/-r`, `--verbose/-v`<br>`claude`: `--resume <id>`, `--continue/-c`<br>`bob`: `--mode/-m plan\|code\|advanced\|ask`<br>`ollama`: see #5 | `jsat/_cli_launchers.py` | ✓ | ✓ | ✓ | ✓ | ✓ | → | ✓ | ✓ | ✓ | ✓ | · |
| 2 | **MCP wiring** — `jsat connect` | claude: `--scope project\|global`, `--global/-g`, `--repo/-r`<br>· `--install-skills/--no-skills`, `--claude-md/--no-claude-md`, `--show`<br>codex: `--no-instructions` (always global)<br>opencode: `--scope/--global`, `--install-commands/--no-commands`, `--agents-md/--no-agents-md`, `--show`<br>bob: `--scope/--global`, `--no-instructions`, `--install-commands/--no-commands`<br>cursor: `--scope project\|global`, `--no-instructions`<br>windsurf/gemini: `--no-instructions` | `jsat/_cli_connect.py` | ✓ | ✓ | ✓ | ✓ | ✗ | ✓* | ✓ | ✓ | ✓ | ✓ | ✓ |
| 3 | **Undo** — `jsat disconnect <tool>` | tool, `--scope/-s project\|global\|all` (claude/codex)<br>`--keep-guidance/--keep-skills` | `jsat/_cli_setup.py:19` | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 4 | **Shell `switch`** — inside `jsat shell` | `switch <provider> [model]`<br>→ claude-cli, codex, opencode, gemini, cursor, windsurf, zed, claude, gpt, ollama, bob, anthropic, lmstudio | `jsat/tools/shell.py:322` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · |
| 5 | **Ollama-launched** — `jsat ollama --tool` | `--tool/-t claude\|opencode\|codex`<br>· `--model/-m`, `--config`, `--restore` (codex), `--yes/-y`<br>· `--repo/-r`, positional `[TOOL\|MODEL]` | `jsat/_cli_launchers.py:140` | ✓ | ✓ | ✓ | ✗ | ✗ | → | ✗ | ✗ | ✗ | ✗ | ✗ |
| 6 | **Managed lifecycle** — `jsat start/stop/restart/resume/ps` | tool `claude\|codex\|opencode\|all`<br>· `--via auto\|native\|ollama`, `--model/-m`, `--repo/-r`<br>· `stop --force`, `resume --session/-s` | `jsat/_lifecycle.py`, `jsat/_cli_lifecycle.py` | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 7 | **GitHub MCP pairing** — `jsat connect github <tool>` | `--scope project\|global`, `--global/-g`<br>· `--remote`, `--token-env NAME`, `--repo/-r` | `jsat/_cli_connect.py:736` | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| 8 | **Reviewer model** — `jsat review` / `jsat__submit_for_review` | model provider chosen in config | `jsat/tools/review.py:44` | ✓ | ✓ | ✓ | ✗ | · | ✓ | · | · | · | · | · |
| 9 | **AI provider adapter** — `jsat ai use` | provider `ollama\|anthropic\|openai\|lmstudio\|claude_cli\|codex_cli\|opencode_cli\|bob_cli`<br>· `--model/-m`, `--config/-c`, `--global/-g`<br>· `gemini`/`deepseek` via `openai_compat` aliases | `jsat/_cli_ai.py:167`<br>`jsat/_ai/aliases.py`, `jsat/_ai/` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | · | · | · |
| 10 | **Auto-detect** — `jsat doctor`/`index` provider probe | none | `jsat/_config.py:265` probe, `:442` priority | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | · | · | · |
| 11 | **Skills / slash commands written on connect** | claude `--install-skills`, opencode `--install-commands`, bob `--install-commands`<br>registry: `jsat/commands/`, `_JSAT_SKILLS` | `jsat/_cli_skills_data.py`<br>`jsat/commands/` | ✓ `/jsat` dispatcher | ✓ `$jsat` SKILL.md | ✓ `/jsat` dispatcher | ✓ `/jsat-*` | ✗ | ✗ | ✗ guidance only | ✗ rules only | ✗ rules only | ✗ guidance only | ✓ `customCommands` |
| 12 | **Guidance / rules file written** | claude → `CLAUDE.md` · opencode → `AGENTS.md`<br>bob → `BOB.md` · cursor → `.cursorrules`<br>windsurf → `.windsurfrules` · gemini → `GEMINI.md`<br>zed → project instructions · codex → `SKILL.md` | `jsat/_cli_connect.py` per-tool | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | · |
| 13 | **Provider adapter module** | — | `jsat/_ai/{claude_cli,bob_cli,codex_cli,opencode_cli,anthropic,openai,openai_compat,ollama,none}.py` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (compat) | · | · | · | · |

\* `jsat connect ollama` wires MCP into every tool Ollama launches, not into
Ollama itself. Provider **detection priority**: `claude_cli` 0 → `bob_cli` 1 →
`codex_cli` 2 → `opencode_cli` 3 → `anthropic` 4 → `openai` 5 →
`openai_compat` 6 → `ollama` 7.

---

## §2 CLI commands

Every `<cmd>` under `jsat …`. **Surface** column cross-references the other two
tables: `CLI` (own command), `MCP` (exposed as `jsat__*` tool, §3), `/skill`
(upper `/jsat-*` command, §4). Args are abbreviated; run `jsat <cmd> --help`
for full text. `PATH` is the Typer command registration; heavy logic lives in
`jsat/tools/`.

### ⚡ Tools (`jsat/_cli_tools.py`, `jsat/_cli_analysis.py`, …)

| S.No | Command | Args | Path | Surface |
|---|---|---|---|---|
| 1 | `blast-radius <target>` | `--diff/-d <range\|file>`, `--max-depth <n>` (5)<br>· `--output/-o <file>`, `--fail-on-breaking`, `--json`, `--repo/-r` | `jsat/_cli_analysis.py:129`<br>→ `tools/blast_radius.py` | CLI<br>MCP: blast_radius, blast_radius_diff/symbol/file/topic<br>/jsat-blast-radius |
| 2 | `contract-check` | `--base/-b origin/main`, `--head HEAD`<br>· `--fail-on-breaking/--no-fail-on-breaking`, `--json`, `--repo/-r` | `jsat/_cli_analysis.py:232`<br>→ `tools/contract.py` | CLI<br>MCP: get_api_diff, check_breaking_changes, get_compat_score<br>/jsat-contract |
| 3 | `security-review [path]` | `--severity/-s medium`, `--sarif <file>`<br>· `--no-deps`, `--fail-on-critical`, `--json`, `--repo/-r` | `jsat/_cli_analysis.py:295`<br>→ `tools/security.py` | CLI<br>MCP: security_review, security_scan_file, list_secrets, get_dependency_cves<br>/jsat-security |
| 4 | `improve` | `--list/-l`, `--id <id>`, `--report`, `--dry-run`, `--submit <bundle>`, `--repo/-r` | `jsat/_cli_improve.py:9`<br>→ `jsat/_improve/` | CLI<br>MCP: improve_status (read-only) |
| 5 | `crack <task>` | `--roles/-r`, `--rounds/-n` (3), `--file/-f <out>`, `--repo` | `jsat/_cli_tools.py:22`<br>→ `tools/crack.py` | CLI · MCP: crack<br>/jsat-crack |
| 6 | `short <query>` | `--words/-w` (50), `--one-line/-1`, `--repo/-r` | `jsat/_cli_tools.py:87` | CLI · MCP: short<br>/jsat-short |
| 7 | `prompt <text>` | `--send/-s`, `--ai claude\|gpt\|ollama`, `--format/-f code\|plan\|json\|prose`<br>· `--cot`, `--compress/--no-compress`, `--no-context`, `--no-examples`<br>· `--self-critique`, `--rewrite`, `--agents <n>`, `--diff`, `--dry-run`<br>· `--verbose/-v`, `--max-tokens` (4096), `--repo/-r` | `jsat/_cli_tools.py:120`<br>→ `tools/prompt_optimizer.py` | CLI<br>MCP: prompt_optimize, prompt_rewrite, prompt_multi_agent, prompt_diff<br>/jsat-prompt, /jsat-prompt-rewrite, /jsat-prompt-diff |
| 8 | `tokens [text]` | `--file/-f`, `--model/-m`, `--compress/-c`, `--strip-comments`<br>· `--no-dedup`, `--target/-t <n>`, `--verbose/-v`, `--repo/-r` | `jsat/_cli_tools.py:293`<br>→ `tools/token_optimizer.py` | CLI<br>MCP: token_count, token_compress, token_budget<br>/jsat-tokens |
| 9 | `knowledge-ingest [path]` | `--pattern/-p *.md`, `--category/-c general`, `--dry-run`, `--repo/-r` | `jsat/_cli_tools.py:411`<br>→ `tools/knowledge.py` | CLI · MCP: knowledge_add |
| 10 | `session` | sub: `list` (`--skill/-s`, `--status in_progress\|completed\|abandoned`, `--limit/-n` 20)<br>· `show <name>`, `resume <name>` (newest by default), `rm <name>`, `prune` | `jsat/_cli_session.py:30,70,91,115,125`<br>→ `jsat/_sessions.py` | CLI (resumable skill sessions) |
| 11 | `note` | sub: `add <text>` (`--category/-c note\|adr\|runbook\|pattern\|decision`)<br>· `list` (`--category`, `--limit/-n` 20), `search <q>` (`--limit/-n` 10)<br>· all `--repo/-r` | `jsat/_cli_session.py:166,188,201`<br>→ `tools/knowledge.py` | CLI<br>MCP: knowledge_add/list/search |

### 🔍 Graph & Index (`jsat/_cli_index.py`)

| S.No | Command | Args | Path | Surface |
|---|---|---|---|---|
| 12 | `index [path]` | `--branch/-b`, `--force/-f`, `--languages/-l`<br>· `--incremental/--full`, `--watch/-w` | `jsat/_cli_index.py:34`<br>→ `tools/indexer.py`, `jsat/_parsers/` | CLI · MCP: index_repo, get_index_status<br>/jsat-index |
| 13 | `doctor` | `--refresh`, `--json` | `jsat/_cli_index.py:103` | CLI · MCP: health, get_jsat_version |
| 14 | `export <output>` | `--compress/-z 0-9` (6) | `jsat/_cli_index.py:219` | CLI · MCP: export_index |
| 15 | `import <archive>` | `--migrate` | `jsat/_cli_index.py:244` | CLI · MCP: import_index |
| 16 | `clean` | `--cache`, `--graph`, `--vectors`, `--history`, `--all/-a`, `--repo/-r` | `jsat/_cli_index.py:267` | CLI |
| 17 | `remove` | `--yes/-y`, `--keep-config` | `jsat/_cli_index.py:324` | CLI |

### 🤖 AI Launchers (`jsat/_cli_launchers.py`)

| S.No | Command | Args | Path | Surface |
|---|---|---|---|---|
| 18 | `shell` | `--repo/-r`, `--verbose/-v` | `jsat/_cli_launchers.py:33`<br>→ `tools/shell.py` | CLI<br>`switch` → all §1 #4 targets |
| 19 | `claude` | `--repo/-r`, `--verbose/-v`, `--resume <id>`, `--continue/-c` | `jsat/_cli_launchers.py:82` | CLI ≡ `connect claude` |
| 20 | `bob` | `--repo/-r`, `--verbose/-v`, `--resume`, `--continue/-c`<br>· `--mode/-m plan\|code\|advanced\|ask` | `jsat/_cli_launchers.py:106` | CLI ≡ `connect bob` |
| 21 | `gpt` | `--repo/-r`, `--verbose/-v` | `jsat/_cli_launchers.py:131` | CLI (JSAT-shell, needs `OPENAI_API_KEY`) |
| 22 | `ollama [TOOL\|MODEL]` | `--model/-m`, `--tool/-t`<br>· `--config`, `--restore`, `--yes/-y`, `--verbose/-v`, `--repo/-r` | `jsat/_cli_launchers.py:140`<br>→ `jsat/_ai/ollama.py` | CLI (§1 #5) |
| 23 | `codex` | `--repo/-r`, `--verbose/-v` | `jsat/_cli_launchers.py:512` | CLI ≡ `connect codex` |
| 24 | `opencode` | `--repo/-r`, `--verbose/-v` | `jsat/_cli_launchers.py:537` | CLI ≡ `connect opencode` |
| 25 | `cursor` | `--repo/-r` | `jsat/_cli_launchers.py:562` | CLI ≡ `connect cursor` |
| 26 | `windsurf` | `--repo/-r` | `jsat/_cli_launchers.py:576` | CLI ≡ `connect windsurf` |
| 27 | `gemini` | `--repo/-r`, `--verbose/-v` | `jsat/_cli_launchers.py:590` | CLI ≡ `connect gemini` |
| 28 | `zed` | `--repo/-r` | `jsat/_cli_launchers.py:607` | CLI ≡ `connect zed` |
| 29 | `start <tool>` | tool `claude\|codex\|opencode\|all`<br>· `--via auto\|native\|ollama`, `--model/-m`, `--repo/-r` | `jsat/_cli_lifecycle.py:191`<br>→ `jsat/_lifecycle.py` | CLI (managed) |
| 30 | `stop [tool]` | tool or `all`, `--force` | `jsat/_cli_lifecycle.py:234` | CLI (managed) |
| 31 | `restart [tool]` | `--via`, `--model/-m`, `--repo/-r`, `--force` | `jsat/_cli_lifecycle.py:276` | CLI (managed) |
| 32 | `resume [tool]` | `--session/-s`, `--via`, `--model/-m`, `--repo/-r` | `jsat/_cli_lifecycle.py:338` | CLI (managed) |
| 33 | `ps` | — | `jsat/_cli_lifecycle.py:385` | CLI (managed) |

### 🔧 Setup & Config

| S.No | Command | Args | Path | Surface |
|---|---|---|---|---|
| 34 | `disconnect <tool>` | tool, `--scope/-s project`<br>· `--keep-guidance/--keep-skills` | `jsat/_cli_setup.py:19` | CLI (§1 #3) |
| 35 | `init` | `--profile/-p solo\|team\|ci\|raspberry-pi`, `--output/-o`, `--global/-g` | `jsat/_cli_setup.py:301` | CLI · config `jsat/_models.py` |
| 36 | `ci-setup` | `--provider/-p github\|gitlab`, `--repo/-r` | `jsat/_cli_setup.py:386` | CLI (CI workflow install) |
| 37 | `mcp-server` | `--repo/-r`, `--verbose/-v` | `jsat/_cli_setup.py:504`<br>→ `jsat/mcp/server.py` | MCP stdio server (69 tools) |
| 38 | `skills` | sub: `list`, `run <name>` | `jsat/_cli_setup.py:340,363`<br>→ `jsat/skills/` | CLI |
| 39 | `connect <tool>` | sub: `claude` `opencode` `ollama` `cursor` `github`<br>· `codex` `windsurf` `continue` `zed` `gemini` `bob` `list` `remove`<br>· flags per §1 #2/#7 | `jsat/_cli_connect.py` (:70,320,465,683,736,<br>:1055,1150,1177,1237,1287,1312,1400,1466) | CLI |
| 40 | `ai <sub>` | sub: `status`, `use <provider>`, `test`, `models`<br>· flags per §1 #9 | `jsat/_cli_ai.py:81,167,356,379` | CLI → provider config |

### 📦 Package (`jsat/_cli_setup.py`)

| S.No | Command | Args | Path | Surface |
|---|---|---|---|---|
| 41 | `version` | — | `jsat/_cli_setup.py:287` | CLI |
| 42 | `update` | `--pre` | `jsat/_cli_setup.py:744` | CLI (`pip install -U jsat`) |

---

## §3 MCP tools (69)

Every tool in `_build_registry()`. `Args` = JSON-schema properties (the four
injected `_dashboard`/`_budget`/`_dashboard_session` args are stripped before
handlers run). `Path` = registry + the features module that owns the logic; tools
whose logic is inline are marked `mcp/server.py`. Every connected AI — Claude,
Codex, OpenCode, Bob, Gemini, Cursor, Windsurf, Zed, Ollama-launched tools —
gets the identical 69-tool surface via MCP.

### Graph & index

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 1 | `index_repo` | path, branch, force, incremental | Build/refresh the graph | `mcp/server.py` → `tools/indexer.py` |
| 2 | `get_index_status` | — | Node/edge counts, freshness | `mcp/server.py` |
| 3 | `create_index_md` | path, max_files | Generate/refresh `INDEX.md` | `mcp/server.py:1926` |
| 4 | `lookup_index_md` | path, pattern | Fast `INDEX.md` pattern search | `mcp/server.py:2033` |
| 5 | `get_jsat_version` | — | Version, provider, backend | `mcp/server.py` |
| 6 | `health` | — | Graph + AI reachability | `mcp/server.py` |
| 7 | `export_index` | output, compress | Portable `.jsat.zip` | `mcp/server.py` |
| 8 | `import_index` | archive | Restore from archive | `mcp/server.py:2482` |
| 9 | `get_metrics` | — | In-memory call counters | `mcp/server.py` |

### Graph lookup & navigation

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 10 | `list_services` | language | Service nodes | `mcp/server.py:1771` |
| 11 | `list_endpoints` | service, method, auth | API endpoints | `mcp/server.py:1796` |
| 12 | `list_tables` | — | Table nodes | `mcp/server.py:1907` |
| 13 | `get_function` | name, file, line | Function details | `mcp/server.py:1832` |
| 14 | `get_class` | name, file | Class details | `mcp/server.py:1861` |
| 15 | `trace_call_chain` | from, to | Shortest path BFS | `mcp/server.py:2070` → `tools/blast_radius.py` |
| 16 | `get_data_flow` | service | Reads/writes/produces/consumes | `mcp/server.py:2130` |
| 17 | `get_consumers` | target, max_consumers | Callers/consumers of a node | `mcp/server.py:2221` |
| 18 | `get_consumers_of_endpoint` | endpoint | Callers of a route | `mcp/server.py` |

### Impact & blast radius

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 19 | `blast_radius` | target, max_depth, service_filter | Downstream impact | `mcp/server.py` → `tools/blast_radius.py` |
| 20 | `blast_radius_diff` | diff, max_depth | Export a git diff | `mcp/server.py:2150` |
| 21 | `blast_radius_symbol` | symbol | Export a symbol | `mcp/server.py` |
| 22 | `blast_radius_file` | path, file, max_depth | Export a file | `mcp/server.py` |
| 23 | `blast_radius_topic` | topic | Kafka schema change | `mcp/server.py` |

### Security & secrets

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 24 | `security_review` | path, severity_threshold | OWASP scan | `mcp/server.py` → `tools/security.py` |
| 25 | `security_scan_file` | file, severity | Single-file scan | `mcp/server.py` |
| 26 | `list_secrets` | path | Entropy-based secret detection | `mcp/server.py` → `tools/_secrets.py` |
| 27 | `get_dependency_cves` | path, cvss_min | osv.dev CVE lookup | `mcp/server.py:2525` |
| 28 | `get_auth_coverage` | service | Unauthenticated endpoints | `mcp/server.py:2805` |
| 29 | `trace_data_flow` | entry_point | Injection-risk paths | `mcp/server.py` |

### Incident & investigation

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 30 | `investigate_incident` | description, since | Root-cause hypotheses | `mcp/server.py` → `tools/incident.py` |
| 31 | `get_hypotheses` | limit | Last investigation results | `mcp/server.py` |
| 32 | `get_recent_changes` | services, since | Recent commit/deploy signal | `mcp/server.py` |
| 33 | `generate_runbook` | hypothesis | Step-by-step runbook | `mcp/server.py` |

### Contract & migrations

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 34 | `get_api_diff` | base, head | OpenAPI/AsyncAPI diff | `mcp/server.py` → `tools/contract.py` |
| 35 | `check_breaking_changes` | base, head | Breaking-only diff | `mcp/server.py:2314` |
| 36 | `get_compat_score` | base, head | 0–100 score | `mcp/server.py:2333` |
| 37 | `validate_migration` | file | Lock risk, rollback, estimate | `mcp/server.py` → `tools/migration.py` |
| 38 | `suggest_zero_downtime` | operation | Zero-downtime plan | `mcp/server.py:2352` |
| 39 | `estimate_lock_duration` | operation, table, row_count | Lock time estimate | `mcp/server.py:3030` |

### Code review & tests

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 40 | `submit_for_review` | diff, base, head | Multi-model review | `mcp/server.py:2395` → `tools/review.py` |
| 41 | `get_review_findings` | min_confidence | Filtered findings | `mcp/server.py:2438` |
| 42 | `get_high_confidence_bugs` | — | High-confidence only | `mcp/server.py` |
| 43 | `get_test_gaps` | path, service | Uncovered paths | `mcp/server.py` → `tools/test_helper.py` |
| 44 | `get_behavioral_coverage` | service | Behavior→test coverage map | `mcp/server.py:2259` |
| 45 | `list_untested_paths` | limit | Highest-risk gaps | `mcp/server.py:2283` |
| 46 | `generate_unit_test` | function | Test suggestion + graph context | `mcp/server.py:3011` |
| 47 | `generate_integration_test` | endpoint | Endpoint test suggestion | `mcp/server.py` |
| 48 | `generate_contract_test` | producer, consumer | Contract test suggestion | `mcp/server.py` |

### Knowledge

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 49 | `knowledge_query` | question, service | Ask the KB | `mcp/server.py` → `tools/knowledge.py` |
| 50 | `knowledge_search` | query, limit | Semantic search (keyword now) | `mcp/server.py` |
| 51 | `knowledge_add` | text, category | Add entry | `mcp/server.py` |
| 52 | `knowledge_list` | category | List by category | `mcp/server.py` |
| 53 | `knowledge_flag_stale` | entry_id | Flag outdated | `mcp/server.py` |

### Reasoning & planning

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 54 | `crack` | task, roles, rounds | 6-agent war room | `mcp/server.py:2946` → `tools/crack.py` |
| 55 | `ithinking_plan` | task | Phases 0–4 plan | `mcp/server.py` |
| 56 | `ithinking_execute` | task | Full 7-phase pipeline | `mcp/server.py` |
| 57 | `ithinking_audit_assumptions` | subtask | Assumption audit | `mcp/server.py` |
| 58 | `ithinking_reflect` | task, result | Post-task reflection | `mcp/server.py` |
| 59 | `ithinking_token_estimate` | task | Local vs LLM cost | `mcp/server.py` |
| 60 | `short` | query, max_words, one_line | ≤50-word answer | `mcp/server.py:2985` |

### Prompts & tokens

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 61 | `prompt_optimize` | query, ai_provider, format, cot, no_context, send | 7-stage pipeline | `mcp/server.py:2650` → `tools/prompt_optimizer.py` |
| 62 | `prompt_rewrite` | query, ai_provider | 1 rewrite agent | `mcp/server.py:2710` |
| 63 | `prompt_multi_agent` | query, ai_provider, n_agents | 3 parallel agents | `mcp/server.py` |
| 64 | `prompt_diff` | query, ai_provider | Raw vs optimized | `mcp/server.py:2612` |
| 65 | `token_count` | text, model | Offline estimate | `mcp/server.py:2836` → `tools/token_optimizer.py` |
| 66 | `token_compress` | text, model, target_tokens, dedup, strip_comments | Offline compression | `mcp/server.py:2863` |
| 67 | `token_budget` | text, model | Context-window headroom | `mcp/server.py:2896` |

### Self-improvement

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 68 | `improve_status` | — | Friction JSAT recorded in itself | `mcp/server.py:2915` → `jsat/_improve/` |

### Graph query (natural language)

| S.No | Tool | Args | Purpose | Path |
|---|---|---|---|---|
| 69 | `query` | question, service | Answer from the graph | `mcp/server.py:2689` → `tools/query.py` |

---

## §4 Slash commands & skills (47)

Installed on `jsat connect`: Claude gets all `/jsat-*` in `.claude/commands/`,
Bob all `/jsat-*` in `.bob/commands/`, OpenCode gets the `/jsat` + `/jsat-help`
dispatcher in `.opencode/commands/`, Continue gets `customCommands` in
`~/.continue/config.json`, Codex gets one `$jsat` skill at
`~/.codex/skills/jsat/SKILL.md`. Gemini/Cursor/Windsurf/Zed get guidance files,
not commands. Args are parsed from `$ARGUMENTS` inside each `.md` body.

| S.No | Skill | Purpose | Args | Runs |
|---|---|---|---|---|
| 1 | `jsat` (help) | Dispatcher / help router | `help` or bare | routes to all skills |
| 2 | `jsat-aw` | Workflow advisor — classify the task, run the right tool sequence | task | query, crack, ithinking, … |
| 3 | `jsat-blast-radius` | Downstream impact of a change | `$ARGUMENTS` flags | blast_radius(_diff/_symbol) |
| 4 | `jsat-changelog` | Changelog between refs, by service/impact | `<base>..<head>` | get_recent_changes, api_diff |
| 5 | `jsat-cherry-pick` | Graph-aware cherry-pick + conflict resolution | commit/branch | blast_radius, git |
| 6 | `jsat-cohesion` | File/function cohesion analysis | path | query, get_function |
| 7 | `jsat-contract` | API contract delta between branches | `--base/--head` | check_breaking_changes, compat_score |
| 8 | `jsat-coverage` | Behavioral coverage + gap generation | path | get_behavioral_coverage, gen tests |
| 9 | `jsat-crack` | Multi-agent war room, artifacts carried forward | task | crack |
| 10 | `jsat-dead-code` | No-caller functions/classes (graph inversion) | — | blast_radius / get_consumers |
| 11 | `jsat-decide` | Decision journal, surfaced by context | `log/search <topic>` | knowledge, blast_radius |
| 12 | `jsat-doctor` | Full system health check | — | health, get_jsat_version, index_status |
| 13 | `jsat-find-class` | Find a class, service-scoped | name (`--service`) | get_class, list_services |
| 14 | `jsat-find-function` | Find a function/method, service-scoped | name (`--service`) | get_function, list_services |
| 15 | `jsat-improve` | Diagnose JSAT friction, draft patch | — | improve_status |
| 16 | `jsat-incident` | Incident investigation | `$ARGUMENTS` subcommands | investigate_incident, hypotheses, runbook |
| 17 | `jsat-index` | Build/refresh the graph | `$ARGUMENTS` flags | index_repo, get_index_status |
| 18 | `jsat-internet` | Live-web facts grounded in this repo | query | jsat__* + web search (only net-enabled skill) |
| 19 | `jsat-ithinking` | Meta-cognitive reasoning | `$ARGUMENTS` subcommands | ithinking_plan/audit/execute/reflect |
| 20 | `jsat-knowledge` | Query/manage the KB | `$ARGUMENTS` subcommands | knowledge_query/add/search/list |
| 21 | `jsat-lazy` | Reuse-first planning — 5-rung ladder | query | query, trace_call_chain |
| 22 | `jsat-list-endpoints` | All endpoints, filterable | `--method/--auth/--service` | list_endpoints |
| 23 | `jsat-list-services` | All services, language filter | `--language` | list_services |
| 24 | `jsat-magic` | Orchestrator — picks/orders the right skills | task | dynamic skill sequence |
| 25 | `jsat-merge` | Graph-aware merge + conflict resolution | source→target branches | blast_radius, get_test_gaps |
| 26 | `jsat-migration` | Validate a migration file | file (`--rows`) | validate_migration |
| 27 | `jsat-plan` | Pre-implementation planning gate | task | ithinking_plan, query, security |
| 28 | `jsat-pr-describe` | PR description from review+contract+coverage | — | get_review_findings, api_diff |
| 29 | `jsat-prompt` | Discuss→Plan→Execute→Verify→Synthesize | query | prompt_optimize |
| 30 | `jsat-prompt-diff` | Raw vs optimized side by side | query | prompt_diff |
| 31 | `jsat-prompt-rewrite` | Pipeline + parallel LLM agents | query | prompt_multi_agent |
| 32 | `jsat-query` | Answer any codebase question | question (`--service`) | query |
| 33 | `jsat-rebase` | Graph-aware rebase of current branch | target | blast_radius, git rebase |
| 34 | `jsat-recent` | Recent changes, time/author filters | `--hours/--author` | get_recent_changes |
| 35 | `jsat-review` | Multi-model code review | `$ARGUMENTS` flags | submit_for_review, review_findings |
| 36 | `jsat-runbook` | Incident runbook for a service | service | generate_runbook |
| 37 | `jsat-security` | OWASP/secret scan | `$ARGUMENTS` flags | security_review, list_secrets |
| 38 | `jsat-service-health-check` | One service's readiness verdict | `<ServiceName>` (required) | list_services, auth_coverage, test_gaps, security, blast_radius |
| 39 | `jsat-short` | Briefest correct answer (≤3 sentences) | `--one-line` | short |
| 40 | `jsat-smart` | Terse compression mode | `--lite/--full/--ultra` | query + compress |
| 41 | `jsat-sprint` | Seven-stage delivery workflow | `--stage <1-7>`, `--dry`, `--continue` | ithinking, query, blast_radius, test_gaps, review |
| 42 | `jsat-status` | Index stats + health (+ AI-reachability) | — | get_index_status, health, version |
| 43 | `jsat-test-gaps` | Uncovered paths + optional generation | `--generate/--integration/--contract/--untested/--service` | get_test_gaps, generate_*_test, list_untested_paths |
| 44 | `jsat-tokens` | Count/compress/budget | `--compress/--model/--budget` | token_count/compress/budget |
| 45 | `jsat-trace` | Point-to-point call chain | `<source> [<target>]`, `--upstream` | trace_call_chain, get_consumers, blast_radius |
| 46 | `jsat-upgrade-impact` | What breaks if a dependency bumps | `<package>`, `--service/--to` | query, security_review, blast_radius |
| 47 | `jsat-verify` | Live-verify the diff's affected behaviors | `<target>`, `--service/--claim` | blast_radius_diff, get_test_gaps, git/test-run |

The definition lives in one place per skill: `jsat/commands/jsat-<name>.md`
(frontmatter `description:` + body). The registry that drives install +
completion is `_JSAT_SKILLS` in `jsat/_cli_skills_data.py:80`; `jsat-help.md`
and `_JSAT_SKILLS` are hand-maintained together — a new `.md` needs all three.

---

## Keeping this file honest

Counts drift with every release. Re-derive before relying on them:

```bash
jsat --help | rg -c '^│'                                        # approx
python - <<'EOF'
from jsat.mcp.server import MCPServer; from jsat._core import JSAT
print(len(MCPServer(JSAT())._registry))          # MCP tools
from jsat._cli_skills_data import _load_jsat_skills
print(len(_load_jsat_skills()))                   # skills (excl. help)
EOF
```

Feature files referenced above: `jsat/_cli_*` = argument parsing +
presentation, `jsat/tools/*` = feature logic, `jsat/mcp/server.py` = MCP
registry + per-call budget/auth/RBAC wrapper, `jsat/commands/` = slash
commands/skills. The CLI→MCP→skills triple is what a single new feature must
touch; `AGENTS.md` §4 documents that contract.