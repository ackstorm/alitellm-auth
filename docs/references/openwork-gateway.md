<!-- Research report, 2026-09-29, from the OpenWork source @a3b7799 (dev). Den "AI Gateway"
     (inference providers, ipr_*) vs Den llmProviders (lpr_*), and what reaches engine v2.
     Companion to openwork-provisioning.md and openwork-engine-v2.md (which is @8c18c952a). -->

# OpenWork Gateway / Den model delivery — research report

Repo `different-ai/openwork` dev @ `a3b7799`. `S` = `apps/server/src`, `A` = `apps/app/src`,
`D` = `ee/apps/den-api/src`, `W` = `ee/apps/den-web`, `G` = `packages/docs/self-host/gateway.mdx`.
`CPS` = `S/cloud-provider-sync.ts`.

---

## 0. Who calls what

| Caller | Den endpoints | Cite |
|---|---|---|
| Local OpenWork server (`CloudProviderSync`) | `GET /v1/llm-providers` → `GET /v1/llm-providers/:id/connect` each; `GET /v1/inference-providers?scope=usable` → `GET /v1/inference-providers/:id/connect` each (skipped when that row has 0 models); `GET /v1/inference-providers/:id/oauth/start[?credentialSetId=]` | `CPS:539-592, 1029-1042` |
| Desktop app → local server | `PUT /den-session {baseUrl,token,orgId}`, `POST /cloud-provider-sync/run` ("Sync now"), `POST /cloud-provider-sync/providers/:id/oauth/start {orgId,credentialSetId?}` | `S/server.ts:3218-3256`; `A/app/lib/openwork-server.ts:1682-1686`; `A/react-app/domains/settings/pages/cloud-providers-view.tsx:172` |
| Den web (`/dashboard/model-connections`, `/gateway/connect`) | `GET /v1/inference-providers/member-connections`, `…/:id/oauth/start`, `…/oauth/browser-status`, `…/oauth/browser-start`, `…/oauth/callback` | `W/app/(den)/dashboard/_components/gateway-member-connections-data.ts:32-61`; `W/app/gateway/connect/gateway-connect.tsx:50,135` |

All server→Den calls: `Authorization: Bearer <den session token>`, `x-openwork-org-id`, `x-openwork-legacy-org-id`, 8 s timeout, `redirect:"error"` (`CPS:499-517`). `baseUrl` includes any `/api/den` prefix (`CPS:52-54`).
Desktop never reads `/v1/org` `deploymentCapabilities` (grep `A`,`S` → none); that gate is admin-management only (`G:270`).

---

## 1. Inference-provider (`ipr_*`) wire contract — strict

List `GET /v1/inference-providers?scope=usable` → `{"inferenceProviders":[…]}`. 404/405/501 = "no Gateway", sync continues legacy-only (`CPS:522, 562-563`). Any bad row fails the whole list (`CPS:445-455`).

Row (`parseInferenceProvider` `CPS:401-443`, on top of `parseProvider` `:317-340`):
- `id` `/^ipr_/i` (oauth start requires `/^ipr_[a-z0-9]+$/`, `CPS:1030`), `providerId`, `name`, `models[]` required; `source` forced to `"openwork_gateway"` (`:442`, `:165`).
- `credentialStatus` ∈ `ready|member_auth_required|org_credential_missing` — required (`:393-405`).
- each model: `id` = `gwm_<ulid26>_<ulid26>_<ulid26>` (Crockford lowercase), `config.id === id`, `upstreamModelId`, `modelGroupId`, `modelGroupName`, `credentialSetId`, `credentialSetName` all required (`:406-410`).
- `authorizationRequests[]` optional: `{credentialSetId:/^gcs_<ulid26>$/, name, authUrl, models?}`; model id segments must match group/set ids (`:411-438`).
- `authUrl` optional/tolerated (`:440-441`).

Connect `GET /v1/inference-providers/:id/connect` → `{"inferenceProvider":{…row…, "apiKey":"ow_gw_…", "apiKeys":{ENV:apiKey}}}` (`CPS:458-482`). Rejected (`den_inference_provider_unscoped_credentials_*`) unless: `providerConfig.env` non-empty, every env name starts with `<ID uppercased, non-alnum→_>_` (e.g. `IPR_XXX_`), `apiKey` starts `ow_gw_`, every env maps to exactly `apiKey`, no extra `apiKeys` names (`:466-474`). Den-side key format: 49 chars `^ow_gw_[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$` (`ee/packages/utils/src/gateway-bearer-key.ts:4,20`) — client only checks the prefix.
409 `{error:"gateway_selection_required"|"credential_set_required"}` → surfaced to UI (`CPS:523-528`).

`providerConfig` Den builds: `api` = `<GATEWAY_PUBLIC_BASE_URL>/api/v1/providers/<ipr_id>`, `env` = runtime-scoped names (`D/llm/inference-provider-config.ts:202-227`). The v2 gateway-quota plugin only attaches when baseURL ends `/api/v1/providers/<ipr_id>` (`S/gateway-quota.ts:14-25`).

OAuth start → `{authUrl}`; server accepts only `https://<any host>/gateway/connect…` (or `http://loopback` when Den is loopback) or `https://accounts.google.com/o/oauth2/v2/auth`; no userinfo/hash; must not contain the Den token (`CPS:30-48`).

## 2. "Each member signs in" — end to end

- Mode is Google-only today (Vertex / Vertex-Anthropic) (`G:179-192`; `D/routes/org/inference-providers.ts:464` "member set with a Google OAuth client").
- Flow: desktop → local server `oauth/start` → Den `/v1/inference-providers/:id/oauth/start` mints a 10-min entry handle → Den-web `/gateway/connect` (needs a signed-in Den **browser cookie** for the same user) → `browser-start` → Google → Den `oauth/callback` stores the member's Google access/refresh token **server-side, encrypted** (`D/routes/org/inference-providers.ts:595-685`; `G:208-216`).
- What the desktop holds: only the member's `ow_gw_` Gateway bearer from `/connect`. `ensureMemberGatewayKey` returns the existing active key or creates one; **one long-lived key per org member, rotated only when revoked/corrupt** (`D/gateway-keys.ts:8-38`; also minted on org join `D/orgs.ts:558,569`). Upstream refresh is the Gateway's job, not the client's.
- Re-fetch cadence: every 5 min (`CPS:243`, `OPENWORK_CLOUD_PROVIDER_SYNC_INTERVAL_MS` `:840-843`), on `den_session_updated` (`:906,932`), and on "Sync now" (`POST /cloud-provider-sync/run`).
- On 401 from the provider baseURL: **no refetch/refresh anywhere** (grep `401` in CPS / gateway-quota / engine-v2-preview → only the no-session error `CPS:1034`). The v2 gateway-quota plugin only marks Gateway quota responses `x-should-retry:false` (`S/opencode-plugins/openwork-gateway-quota-v2.ts:21-37`).
- `/dashboard/model-connections` is **optional**: it's the Den-web view of the caller's Google member connections (`W/…/gateway-member-connections-data.ts:32`); desktop can start the same flow from its own Login action (`G:210`).

## 3. Engine v2 in current dev — delta vs @8c18c952a

- Still a preview, **off by default**: `OPENWORK_ENGINE_V2_PREVIEW=1|chat|sidecar` or persisted `engine-v2-preview.json` (missing/invalid → `{enabled:false}`) (`S/engine-v2-preview.ts:118-159`); Settings → "Experimental engine" (`A/react-app/domains/settings/advanced-sections.ts:6`). Pin still `opencode2 0.0.0-beta-19086` (`constants.json:3`).
- **Changed**: generated config now has a `plugins` key — but only OpenWork's own (context, gateway-quota, provider-filters) as `file://` dirs under the private root (`S/managed-opencode-v2.ts:157-172, 184-186`). User plugins still never loaded; `OPENCODE_CONFIG_DIR` still private (`:242`). The §5 "no plugin key" line in openwork-engine-v2.md is outdated; its conclusion (our plugin can't run) stands.
- Provider mirror unchanged in substance: reads the ENGINE_GLOBAL runtime row (where both `lpr_` and `ipr_` rows land) + env.json credentials (`S/engine-v2-preview.ts:567-578`); adapters `@ai-sdk/openai|anthropic|openai-compatible` + `@openrouter/ai-sdk-provider` mapped to `@opencode-ai/ai/providers/*` (`:215-220`); custom endpoints need `options.baseURL` (a non-native `api` alone → skipped) (`:221-247`); key = literal `options.apiKey` (not `{env:`) → env.json by declared `env[]` → local `auth.json` api key (`:249-260`). New: local v1 `auth.json` API keys are also mirrored (`S/opencode-v2-local-auth.ts:11-20`).
- Side note (out of scope): our plugin hardcodes `@opencode/ai/providers/openai-compatible`; OpenWork's pinned v2 uses `@opencode-ai/ai/...`. Different engine builds; unverified whether either name resolves in the other.

## 4. `llmProviders` (`lpr_*`) — unchanged contract, confirmed

List/connect shapes as in openwork-provisioning.md §1 (`CPS:342-385`). `memberCredential.state` ∈ `missing|active|blocked|stale|error`; anything else fails; non-`active` → provider skipped `needs_key` (`:364-375, 720-728`). Ownership restore needs `^lpr_[a-z0-9]{26}$` (`:1556`). Declared `env[]` with no resolvable key → skipped `missing_credentials` (`:746-757`). v1 engine: reload deferred while sessions are busy (`:1142-1180`); v2: env.json change → re-mirror, no reload.

## 5. Feasibility for alitellm-auth

**Gateway (`ipr_`) "each member signs in" with our AS: not worth it.** Member OAuth is Google-hardwired on Den's side; the client-visible result is still a static per-member `ow_gw_` bearer (long-lived by design) plus strict ULID/`gcs_`/`gwm_` parity rules — i.e. D-3's "static per-member key" with far more surface. Only upside: the quota plugin. Minimum surface would be list + connect (+ oauth/start if `member_auth_required`) with ULID-shaped ids.

**Recommended: Den `llmProviders` + `/connect` returning a per-member, short-TTL LiteLLM key.** Minimum:
1. `GET /api/den/v1/llm-providers` → one row, fixed `id` `lpr_<26 [a-z0-9]>`, `providerConfig {npm:"@ai-sdk/openai-compatible", env:["<NAME>"], options:{baseURL}}`, models with per-model `config`.
2. `GET /api/den/v1/llm-providers/:id/connect` → same row + `apiKey` (member's current key; reuse until ~half TTL left, then mint) + `memberCredential.state:"active"` (or `"missing"` when the member has none yet).
3. (optional) `/v1/resources.llmProviders {id: updatedAt}` for change detection.

Risks: (a) reverses D-3/D-4 — a bearer on disk (env.json / 0600 config), mitigated only by TTL; (b) no 401-driven refresh: TTL must exceed the 5-min poll plus the longest v1 busy-deferred reload, else 401 until next sync; (c) models surface as `lpr_…/<model>` (not `ai-platform/`), v2 drops `cost/attachment/temperature`, and only the openai-compatible+baseURL shape mirrors.
