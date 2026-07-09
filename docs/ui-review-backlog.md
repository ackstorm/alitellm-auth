# UI Review Backlog

External GenAI-agent feedback on the `/ui` console screenshots, triaged against
the real code + backend data model. One section per screen. Only **worth-implementing**
items are kept here (with feasibility + where to go); rejected items get a one-line
reason so we don't re-litigate them.

**Framing that killed half the raw feedback:** the reviewer graded the console as an
*admin multi-tenant key vault* (manage other people's keys). It's a *per-user
self-service console* — every key belongs to the signed-in user. So "Created by",
per-key permissions, environments (dev/staging/prod), IP/region all assume the wrong
product.

---

## KEYS screen (`routes/Dashboard.tsx`, `components/keys/KeysTable.tsx`)

Backend key fields (`KeyRow`, projected by `litellm_client.py::_project_session_key`):
`id, key_alias, spend, tpm_limit, rpm_limit, models, team_id, created_at, expires,
last_used, is_default, blocked`. No permissions / IP / rotation / budget-reset-date.

### Worth implementing

1. **Relative "Last used" + stale warning** — *frontend only, best ROI*
   - Now: `KeysTable.tsx` "Last used" column prints absolute `formatDate(row.last_used)`.
   - Want: `2h ago` / `3 days ago` / `Never used`; warning tone (amber) on stale keys
     (e.g. >30d or never-used-but-old).
   - Feasibility: `last_used` present. **No relative-time helper exists in `lib/format.ts`** —
     add a small `relativeTime(iso)` there and reuse.
   - Where: `lib/format.ts` (new helper), `KeysTable.tsx` lastused cell.

2. **Rate-limit column (TPM / RPM)** — *JC wants it*
   - Now: not shown. `tpm_limit`/`rpm_limit` already on `KeyRow` (from LiteLLM
     `k.get("tpm_limit")`, `litellm_client.py:498-499`).
   - Feasibility: frontend only. Populated when a per-key limit is set; **null (→ em-dash)
     when inherited from user/team**, which is the common case — expect many em-dashes.
   - Where: add column(s) to `KeysTable.tsx`. Consider one compact `TPM/RPM` cell.

3. **Budget card: "% used"** — *trivial*
   - Now: `BudgetBar` shows `$current of $max / duration`.
   - Want: append `· N% used` (we already compute `ratio`).
   - Where: `Dashboard.tsx::BudgetBar` figure line (~1 line).

4. **Budget card: projected spend** — *"si no es difícil, mola"; it isn't*
   - Want: naive linear run-rate — `current / daysElapsed * daysInPeriod`, labelled
     "projected".
   - Feasibility: pure frontend from `me.spend.current` + current date. ~5 lines.
   - Caveat: naive linear only; label clearly as *projected*. Skip if `budget_duration`
     isn't monthly-ish (projection is meaningless for a 24h window).
   - Where: `Dashboard.tsx::BudgetBar`.

5. **Team card caption** — *trivial, low value*
   - Now: `TeamTile` renders team-alias pills (`default`, `run`, `dream`) under a "Team"
     label; ambiguous whether selected/available/tags.
   - Want: small sub-label/tooltip like "Your teams".
   - Where: `Dashboard.tsx::TeamTile`.

### Rejected (reason)

- **Model access per key** — permission == team membership; we don't define more (JC).
- **View usage per key** — already covered by the STATS screen (JC).
- **Filters above table (team/status/last-used/expiring)** — YAGNI; users have few keys (JC).
- **Disable action** — already exists in the kebab menu (`Disable key`); reviewer missed it.
- **Copy key ID / Rotate / Edit permissions** — deliberate no-secret table; no rotation
  concept; no permission model.
- **Scope/permissions, Created by, Last IP/region, Rotation status** — not in data model /
  self-service console (Created by is always the signed-in user).
- **Environment dev/staging/prod** — no environment concept.
- **Budget: days remaining** — needs budget-reset date; backend doesn't expose it.
- **Budget: alert threshold** — no threshold config exists.

---

## MODELS screen (`routes/Models.tsx`)

Backend fields (`ModelRow`, projected by `litellm_client.py::_project_model_group` from
LiteLLM `/model_group/info` — the **safe public** group view):
`name, providers[], mode, max_input_tokens, max_output_tokens, input_cost_per_token,
output_cost_per_token, supports_vision, supports_function_calling, supports_reasoning,
supports_web_search`. Deliberately **no** upstream model id / api_base / api_key, and no
description / rate-limits / allowed-teams / latency fields.

This screen is already ahead of the reviewer: capability icons **already have tooltips**
(`CapBadge`/`ThinkingCell` `title=`), and pricing is **already labelled** (`$ / 1M (in / out)`
header + "per 1M tokens" subtitle).

### Worth implementing

1. **Capability filter toolbar** — *frontend only, JC scoped it to capabilities*
   - Quick-filter toggles by `mode` (chat / image / audio / …) + the four `supports_*`
     booleans (vision / thinking / tools / web).
   - "Cheaper" is continuous, not boolean — the price column already sorts, so treat
     cheapest as sort (or an optional `≤ $X` toggle), not a filter chip.
   - Feasibility: all fields on `ModelRow`; filter rows client-side before the DataTable.
     Needs a little filter-state + a toggle row above the table.
   - Where: `Models.tsx` (new toolbar), filter `models` before passing to `DataTable`.

2. **Router `$0.00 / $0.00` → "Dynamic"** — *frontend only*
   - Now: `PriceCell` renders literal `$0.00` for a 0-cost row (0 is a number), so the
     auto-router alias shows `$0.00 / $0.00`, which reads as unfinished.
   - Want: detect a router row via `providers` ⊇ `auto_router` → show `Dynamic` for both
     price and context.
   - Where: `Models.tsx::PriceCell` + `ContextCell` (add a `isRouter(row)` guard).

3. **Example API call snippet** — *frontend only, the one real win from the "detail panel" idea*
   - Per-model curl / python snippet built from `me.endpoint` + the alias (copy button or
     small expand). Genuine dev value; nothing else in a detail panel adds data we don't
     already show in the row.
   - Where: `Models.tsx` — per-row expand or a copy-snippet action.

### Open (JC to decide)

- **Alias taglines** (`ackstorm.fast` = low-latency, etc.) — real value, but **needs a
  backend `description` field** surfaced from LiteLLM `model_info` (can't hardcode:
  aliases are deployment-configured, not always `ackstorm.*`). Biggest value / biggest cost.
- **Computed badges** (Cheapest / Largest context) — derivable frontend, but **redundant**
  with the already-sortable price/context columns. Skip unless wanted.

### Rejected (reason)

- **Capability icon tooltips** — already implemented (`title=` on every badge).
- **"Price per 1M" clarity** — header + subtitle already state it; `In$/Out$` relabel is taste.
- **Editorial badges** (Recommended / Fastest / Best quality) — no data; = the alias-tagline
  backend work above.
- **Full detail side-panel** — full model id **deliberately hidden** (security); rate limits /
  allowed teams / latency / supported-params **not in data**; panel would just repeat the row.
- **Multi-state placeholders** (Coming soon / Inherited / Custom for `—`) — backend only
  emits null; we can't distinguish those states. Router "Dynamic" (worth #2) is the one
  detectable case.

---

## STATS screen (`routes/Stats.tsx`)

Contract (`stats.py::build_stats_contract`, sourced from LiteLLM `/user/daily/activity`):
`totals{requests, tokens, spend, failed_requests, input_tokens, output_tokens,
cache_read_tokens, cache_hit_pct, avg_cost_per_1m_tokens, deltas}`, per-day
`series[]{date, spend, requests, tokens, failed}`, per-model + per-key breakdowns,
`budget`, `capabilities`. **No latency, no error codes, no per-model/per-key failure
split, no logs** in the daily aggregate.

### Worth implementing

1. **Projected spend** — *frontend only; same item JC liked on KEYS #6c, better home here*
   - Naive month-end run-rate on the budget panel: `budget.current / daysElapsed *
     daysInPeriod`, labelled "projected".
   - Implement once (shared helper) and reuse on the KEYS dashboard budget bar.
   - Where: `components/stats/BudgetPanel.tsx` (+ `Dashboard.tsx::BudgetBar`).

2. **Failed-requests trend** — *frontend only*
   - `series[].failed` already exists and `RequestsChart` already has a metric toggle
     (requests / tokens) — add `failed` as a third metric to get the failure-rate trend.
   - Where: `components/stats/RequestsChart.tsx` (`RequestsMetric` union + toggle).

3. **Split the Total-Tokens KPI card** — *taste, JC approved*
   - One-line `209M in · 1.05M out · 99% cached` → three lines (or a small stacked bar).
     Data present (`input_tokens`, `output_tokens`, `cache_hit_pct`).
   - Where: `components/stats/KpiRow.tsx`.

4. **Spend tooltip** — *frontend only, cheap*
   - LiteLLM spend already accounts for cache/provider pricing → add a tooltip on the
     spend KPI: "gateway-computed spend; includes cache & provider pricing".
   - Where: `components/stats/KpiRow.tsx`.

### Wanted — blocked on upstream LiteLLM

7. **Latency (p50/p95/p99, TTFT, tokens/sec)** — *JC wants it; investigated*
   - Data EXISTS per request: LiteLLM `/spend/logs` rows carry `request_duration_ms`
     (total latency) and `completionStartTime` (→ TTFT). Percentiles + tok/s are derivable.
   - BLOCKER: `/spend/logs` was removed from this repo (`session.py:790`) because its
     `user_id`/`date` filters are silently ignored (**cross-user leak**) and it returns the
     entire table (~83 MB/user/7d → **OOM-killed the pod**). The daily aggregate we use has
     no latency. This service can't measure latency itself (it doesn't proxy LLM traffic).
   - NEXT ACTION: recheck `/spend/logs` filtering + pagination on the current LiteLLM
     version. If honored now → a bounded per-request fetch + server-side percentile
     aggregation becomes feasible (heavier query, no leak/OOM). Else: upstream PR to add
     latency to the daily aggregate, or a Prometheus/otel metrics path (new infra).
   - **RECHECK 2026-07-09 (live probe, `api.ackstorm.ai`, a real user `sk-`) → GO (bounded).**
     - **No cross-user leak on the user-key path.** `GET /spend/logs?summarize=false` called
       with a plain user `sk-` **auto-scopes to the caller**: all 138 rows had
       `user=<key owner>`, and the daily-aggregate `users` block listed only that user. The
       original leak was the *master-key* path (`user_id` param ignored); server-side we must
       call it via the `sso_key_swapper` impersonation (master + `x-user-id`, same as
       models/mcp) so it auto-scopes, NEVER master alone with a `user_id` filter.
     - **Latency fields ARE present per request:** `request_duration_ms` (138/138 rows),
       `startTime`, `endTime`, `completionStartTime`, `status`, tokens. Probe percentiles for
       one day: p50 3251 ms, p95 7226 ms, p99 9231 ms. TTFT = `completionStartTime − startTime`.
     - **Date filters honored; pagination IGNORED.** `start_date`/`end_date` bound the window;
       `page`/`page_size` are silently ignored (10-page-size request still returned all 138
       rows). So the fetch is bounded ONLY by the date range, not by pages.
     - **Size:** 1 day ≈ 138 rows ≈ **3.7 MB** raw — bloated by `proxy_server_request` (16 KB),
       `metadata` (6 KB), `response` (3 KB) per row. The **lean latency subset is 375 B/row**
       (72× smaller). A wide window on a heavy user still risks the old OOM (30 d ≈ 100 MB+).
     - **Follow-up plan (build):** alitellm-auth backend fetches `/spend/logs?summarize=false`
       server-side via `sso_key_swapper` impersonation (auto-scoped), **capped by a short date
       window (≤7 d) + a hard row cap** (stop after N rows, label "sampled" — since pagination
       is a no-op), computes p50/p95/p99 + TTFT + tok/s server-side, and returns ONLY the
       computed metrics (or the 375 B lean subset) — **never** forwarding
       `messages`/`response`/`proxy_server_request`/`metadata` to the browser (kills both the
       info-disclosure and payload-size problems). New route e.g. `GET /api/session/latency`.

### Rejected (reason)

- **Interactive charts** — already done: both charts have Recharts hover tooltips.
- **Error drilldowns** (top error codes / failed-by-model / failed-by-key / error logs) —
  only a total + per-day `failed` count exists; no error codes, no per-entity split, no logs.
- **Model/key row drilldowns** — no per-entity time series, no detail pages; scope creep.
- **"Top model/key per day" in chart hover** — series is a daily aggregate; no per-day split.

---

## STATS part 2 — the Model Breakdown table (`components/stats/ModelTable.tsx`)

`StatsModelRow` today: `model, requests, input_tokens, output_tokens, total_tokens,
spend, spend_pct, last_used`. LiteLLM feeds `MCP: …` tool rows through the **models**
breakdown itself (consistent `MCP: ` prefix), so they land in this same table.

**Data-availability correction:** the raw LiteLLM per-model metrics block carries MORE
than we project — verified in `daily_activity_current.json`:
`cache_read_input_tokens, cache_creation_input_tokens, failed_requests,
successful_requests` are all present per model. We just don't aggregate them in
`stats.py::_accumulate_day_models` or expose them on `StatsModelRow`. So per-model
**cached-input** and **errors** are feasible with a small backend change (NOT no-data as
first triaged). Latency remains the only genuinely-absent metric.

### Worth implementing

1. **Option A — "Usage Breakdown" + `TYPE` column + blank cost cells for MCP rows** —
   *frontend only; the reviewer's own simplest fix; subsumes 3 of their bullets*
   - Rename the section `MODEL BREAKDOWN` → `USAGE BREAKDOWN`.
   - Add a `TYPE` column: `MCP Tool` when `model.startsWith("MCP:")`, else `Model`
     (optionally strip the `MCP: ` prefix from the name cell).
   - On MCP-type rows, render `—` (not `$0.00` / `0`) for the token + cost columns
     (INPUT/OUTPUT/TOTAL/SPEND-per-1M) — kills the "MCP looks free" misread and the
     empty-column visual noise in one move.
   - Rejects Options B (tabs) and C (grouped sections): a column + row-classing gets the
     same result with no tab/section machinery.
   - Where: `ModelTable.tsx` (+ the section label in `Stats.tsx`).
   - Detection caveat: confirm the `MCP: ` prefix against live data before shipping.

2. **Table search (name)** — *frontend only*
   - Filter rows by substring (`gitlab`, `slack`, `gemini`…). Same pattern as MODELS #1.
   - Where: `Stats.tsx` / `ModelTable.tsx`.

3. **Per-model "Cached input" column** — *small backend + frontend; JC asked, data confirmed*
   - Aggregate `cache_read_input_tokens` in `_accumulate_day_models`, add
     `cache_read_tokens` to `StatsModelRow` (backend + `api-types.ts`), render a column.
   - Where: `stats.py::_accumulate_day_models`, `api-types.ts::StatsModelRow`, `ModelTable.tsx`.

### Feasible but not requested (parked — same backend change as #3)

- **Per-model Errors / Error %** — `failed_requests` is in the same metrics block. If wanted
  later, add it alongside cached-input for near-zero extra cost. (Corrects the earlier
  "no per-model errors" reject.)

### Rejected (reason)

- **Options B / C** (tabs / grouped sections) — Option A subsumes the value with less UI.
- **Latency column** — genuinely not in daily activity; blocked upstream (STATS #7).
- **Clickable row → side panel** (usage-over-time / related keys / recent errors / samples) —
  no per-entity time series, no key↔model mapping, no error detail, no sample requests.
- **Sticky first column** — JC declined (shared `DataTable` change).

---

## HOW-TO screen (`routes/HowTo.tsx`, 801 lines)

The most mature screen. Much of the review is **already built**: `apiBase = me.endpoint`
is injected into every snippet (endpoint personalization done); the Editors & CLIs section
has full tabbed setup (OpenCode Gemini/OpenAI, Claude Code, Gemini CLI, codex, each with
config + notes + guide + caveats); MCP already has `MCP Access` / `MCP Group access` /
`Try with curl` tabs; the No-terminal section has ACKstorm Chat (ready) + openwork (`Soon`).

**Two factual corrections (reviewer wrong):**
- MCP auth `x-litellm-api-key: Bearer sk-...` **is** the gateway's required format (not a
  mistake); don't switch to `Authorization: Bearer`.
- `LITELLM_API_KEY` is read verbatim by the tool configs (`{env:LITELLM_API_KEY}` in
  opencode/codex); renaming to `ACKSTORM_API_KEY` breaks them. `brand_short` already brands display.

### Worth implementing

1. **Quickstart SDK tabs + expected-response block** — *frontend only; reviewer's #1*
   - Quickstart is curl-only today. Add Python / TypeScript / OpenAI-SDK tabs (static
     snippets with `apiBase` injected, `sk-...` placeholder) + a small expected-response JSON.
   - Where: `HowTo.tsx` Quickstart `Section` (reuse `Tabs` + `CodeBlock`).

2. **Troubleshooting section (401 / 404 / 429 / MCP errors)** — *frontend only; highest-value add*
   - Genuinely absent. Static content + a new TOC entry. Cuts onboarding support load.
   - Where: `HowTo.tsx` (new `Section` + `TOC` item).

3. **`export OPENAI_API_KEY=$LITELLM_API_KEY` compat hint** — *frontend only, cheap*
   - The correct version of the naming feedback: preempts confusion without breaking the
     tool var references.

4. **openwork `Soon` → `Coming soon`** — *trivial* (relabel + keep muted styling).

5. **Client-specific MCP config tabs** (Cursor / Claude Desktop / VS Code + where to place the
   config) — *frontend, content work* — extends the existing MCP tabs with per-client placement.

6. **Model picker to personalize snippets** — *frontend* — a `useModels`-backed picker that
   swaps the `MODEL_ALIAS` token across the page's snippets (endpoint already personalizes).

### Rejected (reason)

- **Standardize MCP auth header** — current format is the gateway's requirement (correction above).
- **Rename env var to `ACKSTORM_API_KEY`** — breaks tool config references (correction above).
- **Personalize with the real key** — `sk-` shown once, never on this page (hard security
  constraint, already enforced with `KEY_PLACEHOLDER`).
- **Onboarding checklist with completion states** — "first request sent / editor connected /
  usage viewed" are unobservable by this app; a static list only would be low value.
- **Endpoint personalization / editor tabs / MCP 3-case tabs / no-terminal cards** — already built.
- **Video/GIF, collapsible sections, copy-all, downloadable configs** — YAGNI / scope.
- **Cross-links "next steps" + live MCP tools preview** — deferred by JC (not selected).

---

## Consolidated plan (go-deep after this session)

Covers the 6 surfaces reviewed: KEYS, MODELS, MCP, STATS (KPIs/charts), STATS (breakdown),
HOW-TO. Ordered by ROI. Frontend-only unless marked.

### Tier 1 — frontend-only, cheap, high value

- **Projected spend** (shared: STATS `BudgetPanel` + KEYS budget bar) — one helper, two call sites.
- **Relative "Last used" + stale state** (KEYS) — needs a small `relativeTime()` in `lib/format.ts`.
- **Failed-requests trend** — add `failed` to the `RequestsChart` metric toggle (STATS).
- **Budget "% used"** (KEYS budget bar).
- **Router `$0.00/$0.00` → "Dynamic"** (MODELS) — `providers ⊇ auto_router`.
- **Usage Breakdown rename + TYPE column + blank MCP cost cells** (STATS p2, Option A).
- **Spend tooltip** (cache/provider pricing note) (STATS KPI).
- **MCP: `auth` relabel + tooltip** + **summary bar** + **tool-count prominence / collapse tool list**.
- **Team card caption** (KEYS, trivial).
- **HOW-TO: Quickstart SDK tabs + expected response**, **Troubleshooting section**,
  **`OPENAI_API_KEY` compat hint**, **openwork "Coming soon"** relabel.

### Tier 2 — frontend-only, moderate

- **Capability filter toolbar** (MODELS) + **table search** (MODELS, STATS breakdown, **MCP**)
  — one shared filter pattern across the catalogs (MCP search folded in here).
- **TPM/RPM column** (KEYS) — expect many em-dashes (limits usually inherited).
- **Example API call snippet** (MODELS) — curl/python from `endpoint` + alias.
- **Split the Total-Tokens KPI card** (STATS).
- **HOW-TO: client-specific MCP config tabs** (Cursor / Claude Desktop / VS Code + file paths).
- **HOW-TO: model picker** to personalize snippets (`useModels` → swap `MODEL_ALIAS`).

### Tier 3 — small backend

- **Per-model "Cached input" column** — aggregate `cache_read_input_tokens` (STATS p2 #3).
  Optional same-change add: per-model Errors / Error %.

### Tier 4 — large / blocked upstream

- **Latency** (p50/p95/p99, TTFT, tok/s) — blocked: only in `/spend/logs`, which is removed
  for cross-user-leak + OOM. NEXT ACTION: recheck `/spend/logs` filtering/pagination on the
  current LiteLLM version before any build.

### Dropped by JC

- MODELS **alias taglines** (would need a backend `description` field / editorial copy).
- MODELS **Cheapest / Largest-context badges** (redundant with sortable columns).
