// api-types.ts — TypeScript models of the CURRENT backend JSON shapes.
//
// Every type below mirrors what the FastAPI service actually emits today (field
// names + nullability), NOT a speculative or normalized shape. Each type points
// at its backend source so the contract stays verifiable. Do NOT add fields that
// the backend does not return (YAGNI) — if the backend gains a field, model it
// here in the same PR that ships it.

// ---------------------------------------------------------------------------
// GET /api/session/me  — src/api/app/session.py::session_me
// ---------------------------------------------------------------------------

/**
 * Per-user limit block. Built by session.py::_build_limits from the LiteLLM
 * user object; every field is independently nullable, and the WHOLE block is
 * `null` when the LiteLLM enrichment is unavailable OR all fields are null.
 */
export interface SessionLimits {
  max_budget: number | null;
  budget_duration: string | null;
  tpm_limit: number | null;
  rpm_limit: number | null;
}

/** Source of the spend figure. session.py::_derive_spend / _SPEND_SOURCE_UNKNOWN. */
export type SpendSource = 'team_member' | 'team' | 'user' | 'unknown';

/** Spend block on /me. session.py::_derive_spend. `current` is always a number. */
export interface SessionSpend {
  current: number;
  source: SpendSource;
}

/** GET /api/session/me response. session.py::session_me JSONResponse. */
export interface SessionMe {
  email: string;
  name: string;
  team_id: string;
  endpoint: string;
  limits: SessionLimits | null;
  spend: SessionSpend;
}

// ---------------------------------------------------------------------------
// GET /api/session/keys  — src/api/app/session.py::session_list_keys
// (rows projected by litellm_client.py::_project_session_key, then the handler
//  strips `key`/`token` before returning — D-17)
// ---------------------------------------------------------------------------

/**
 * One row of GET /api/session/keys (after the backend strips `key`/`token`).
 *
 * Fields emitted by _project_session_key (minus the stripped pair):
 *   id, key_alias, spend, budget, tpm_limit, rpm_limit, models, created_at, expires
 * `budget` is ALWAYS null today (D-17 — inherited from user/team, reported by /me).
 *
 * `revoked`/`blocked` are NOT emitted by the current backend, but keys-table.js
 * (isRevoked) reads them defensively (absence === active). Modeled optional so a
 * future backend that adds them type-checks without a churn.
 */
export interface KeyRow {
  id: string | null;
  key_alias: string | null;
  spend: number;
  budget: null;
  tpm_limit: number | null;
  rpm_limit: number | null;
  models: string[] | null;
  created_at: string | null;
  expires: string | null;
  /** LiteLLM per-key last-used timestamp (its `last_active`); null until used. */
  last_used: string | null;
  /** Explicit default-key flag (metadata-backed; session API derives it). */
  is_default: boolean;
  // Not emitted by the current backend; isRevoked() reads them defensively.
  revoked?: boolean;
  blocked?: boolean;
}

/** GET /api/session/keys response. session.py::session_list_keys. */
export interface KeysResponse {
  keys: KeyRow[];
}

// ---------------------------------------------------------------------------
// POST /api/session/keys  — src/api/app/session.py (CreateKeyBody + create handler)
// ---------------------------------------------------------------------------

/** POST /api/session/keys request body. session.py::CreateKeyBody (both optional). */
export interface CreateKeyBody {
  alias?: string;
  duration?: string;
}

/**
 * POST /api/session/keys response — the only place the sk- (`key`) is returned,
 * once, and never stored server-side. session.py::session_create_key.
 * `team_id` comes from key_data.get("team_id") so it may be null.
 */
export interface CreateKeyResponse {
  key: string;
  id: string;
  team_id: string | null;
}

/**
 * The one-time freshly-minted key. Same payload as CreateKeyResponse; named
 * separately because list rows (KeyRow) deliberately OMIT the sk- `key`.
 */
export type CreatedKey = CreateKeyResponse;

// ---------------------------------------------------------------------------
// DELETE /api/session/keys/{id}  — src/api/app/session.py::session_delete_key
// ---------------------------------------------------------------------------

/** DELETE /api/session/keys/{id} response. session.py::session_delete_key. */
export interface DeleteKeyResponse {
  status: string;
  id: string;
}

/** POST /api/session/keys/{id}/default response. session.py::session_make_default. */
export interface MakeDefaultResponse {
  status: string;
  id: string;
}

/** POST /api/session/keys/{id}/block response. session.py::session_block_key. */
export interface BlockKeyResponse {
  status: 'blocked' | 'active';
  id: string;
}

// ---------------------------------------------------------------------------
// GET /api/session/stats  — src/api/app/session.py::session_stats
// (contract assembled by src/api/app/stats.py::build_stats_contract)
// ---------------------------------------------------------------------------

/** stats.py::build_stats_contract range_meta.compare sub-block. */
export interface StatsRangeCompare {
  start: string;
  end: string;
}

/** stats.py range_meta. {start, end, days, compare}. */
export interface StatsRange {
  start: string;
  end: string;
  days: number;
  compare: StatsRangeCompare;
}

/**
 * Period-over-period deltas. stats.py::compute_deltas. Each *_pct is null when
 * the prior-window denominator is 0/None (D-08 null-vs-0), else a ratio.
 */
export interface StatsDeltas {
  requests_pct: number | null;
  tokens_pct: number | null;
  spend_pct: number | null;
  avg_cost_per_1m_tokens_pct: number | null;
}

/** stats.py totals block. avg_cost_per_1m_tokens is null when tokens===0 (D-08). */
export interface StatsTotals {
  requests: number;
  tokens: number;
  spend: number;
  avg_cost_per_1m_tokens: number | null;
  deltas: StatsDeltas;
}

/** One series point (one per in-window day). stats.py::aggregate_window. */
export interface StatsSeriesPoint {
  date: string | null;
  spend: number;
  requests: number;
  /** Per-day total tokens (prompt + completion). */
  tokens: number;
}

/**
 * Per-model breakdown row. stats.py::build_stats_contract.
 * spend_pct is null when total model spend is 0 (D-08); last_used is null when
 * no source data was available for that model.
 */
export interface StatsModelRow {
  model: string | null;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  spend: number;
  spend_pct: number | null;
  last_used: string | null;
}

/**
 * Per-key (top-keys) breakdown row, ranked by spend desc. stats.py.
 * `id` is the LiteLLM key hash; key_alias may be null; spend_pct null when total
 * key spend is 0 (D-08).
 */
export interface StatsKeyRow {
  id: string | null;
  key_alias: string | null;
  requests: number;
  spend: number;
  spend_pct: number | null;
}

/**
 * Budget block. stats.py::build_stats_contract. max_budget null when none is
 * configured; pct null when max_budget is null/0 (D-08); has_budget mirrors that.
 */
export interface StatsBudget {
  current: number;
  max_budget: number | null;
  budget_duration: string | null;
  source: SpendSource;
  pct: number | null;
  has_budget: boolean;
}

/**
 * Backend capability flags. stats.py / session.py::_CAPABILITY_DEFAULTS.
 * per_model_last_used flips to false when no last-used data is available.
 */
export interface StatsCapabilities {
  token_split: boolean;
  per_model_last_used: boolean;
  deltas: boolean;
  per_key_spend: boolean;
}

/** GET /api/session/stats response. stats.py::build_stats_contract. */
export interface StatsResponse {
  range: StatsRange;
  totals: StatsTotals;
  series: StatsSeriesPoint[];
  models: StatsModelRow[];
  keys: StatsKeyRow[];
  budget: StatsBudget;
  capabilities: StatsCapabilities;
}

// ---------------------------------------------------------------------------
// GET /api/config  — src/api/app/public.py::public_config
// (defaults mirrored in src/ui/app.js DEFAULT_CONFIG)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// GET /api/session/models  — src/api/app/session.py::session_models
// (rows projected by litellm_client.py::_project_model_group from LiteLLM
//  /model_group/info — the safe public group view; no litellm_params/creds)
// ---------------------------------------------------------------------------

/**
 * One public model-group row. EVERY field mirrors _project_model_group's
 * explicit allow-list. `mode` is e.g. "chat" | "embedding" | "rerank" | null.
 * Costs are per-token floats (often scientific notation); token caps are floats
 * or null (LiteLLM emits them as floats, e.g. 128000.0).
 */
export interface ModelRow {
  name: string | null;
  providers: string[];
  mode: string | null;
  max_input_tokens: number | null;
  max_output_tokens: number | null;
  input_cost_per_token: number | null;
  output_cost_per_token: number | null;
  supports_vision: boolean;
  supports_function_calling: boolean;
  supports_reasoning: boolean;
  supports_web_search: boolean;
}

/** GET /api/session/models response. session.py::session_models. */
export interface ModelsResponse {
  models: ModelRow[];
}

// ---------------------------------------------------------------------------
// GET /api/session/mcp  — src/api/app/session.py::session_mcp
// (rows projected by litellm_client.py::_project_mcp_server from LiteLLM
//  /v1/mcp/server — a PUBLIC subset; credentials/env/headers are stripped)
// ---------------------------------------------------------------------------

/**
 * One configured MCP server (public projection). `transport` is "sse" | "http"
 * | "stdio"; `status` is "healthy" | "unhealthy" | "unknown" | null; `auth_type`
 * is the type LABEL only (e.g. "oauth2"), never a secret. `tool_count` mirrors
 * tools.length (LiteLLM has no numeric count field).
 */
export interface McpServerRow {
  id: string | null;
  name: string | null;
  description: string | null;
  url: string | null;
  transport: string | null;
  auth_type: string | null;
  status: string | null;
  tools: string[];
  tool_count: number;
  access_groups: string[];
}

/**
 * GET /api/session/mcp response. session.py::session_mcp. `available` is false
 * when the deployment's LiteLLM has no MCP gateway (a 404 the backend degrades
 * to an empty, available:false 200) — the page shows a calm "not enabled" state.
 */
export interface McpResponse {
  servers: McpServerRow[];
  available: boolean;
}

/**
 * One configured A2A (Agent-to-Agent) agent (public projection). Display fields
 * come from the agent card: `transport` is the preferred transport, `version` the
 * card version, `skills` the agent's skill names (`skill_count` mirrors length),
 * `streaming` the card's streaming capability. No secret/header field is surfaced.
 */
export interface A2aAgentRow {
  id: string | null;
  name: string | null;
  description: string | null;
  url: string | null;
  transport: string | null;
  version: string | null;
  skills: string[];
  skill_count: number;
  streaming: boolean;
}

/**
 * GET /api/session/a2a response. session.py::session_a2a. `available` is false
 * when the deployment's LiteLLM has no A2A gateway (a 404 the backend degrades to
 * an empty, available:false 200) — the page shows a calm "not enabled" state.
 */
export interface A2aResponse {
  agents: A2aAgentRow[];
  available: boolean;
}

/** One BACKED-BY provider chip. public.py::_PROVIDERS. */
export interface ConfigProvider {
  label: string;
}

/**
 * GET /api/config response (public, non-secret presentation config).
 * public.py::public_config. `links` only carries keys whose target is set
 * (real-links-only rule, D-02/D-03), so every link key is optional.
 */
export interface AppConfig {
  brand: string;
  brand_short: string;
  tagline: string;
  accent_segment: string;
  provider_label: string;
  public_host: string;
  // Explicit hosted-chat URL. Empty string => the SPA derives chat.<domain> from
  // the gateway host (deriveSubdomainUrl over me.endpoint).
  chat_public_url: string;
  providers: ConfigProvider[];
  links: Record<string, string>;
}
