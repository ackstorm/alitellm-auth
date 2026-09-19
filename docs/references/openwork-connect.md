<!-- Research report, 2026-09-19, from the OpenWork source (apps/server, apps/app, ee/apps/den-api)
     and test/openwork-den/den.mjs. Read before implementing Connect / Cloud MCP in app/openwork.py. -->

# OpenWork Connect / Cloud MCP — Den contract research

Sources: `/home/jcm/Projects/openwork` (server + app + `ee/apps/den-api`), reference Den `/home/jcm/Projects/alitellm-auth/test/openwork-den/den.mjs`, current Den `/home/jcm/Projects/alitellm-auth/src/api/app/openwork.py`.

---

## 1. CONNECT SWITCH (`connectEnabled`)

### Where it comes from
| Source | File:line | Note |
|---|---|---|
| Den `GET /v1/me/desktop-config` | `packages/types/src/den/desktop-policies.ts:342`, normalized `:733-748` | optional boolean; absent = "no org policy" |
| Den `POST /v1/auth/desktop-handoff/exchange` `connectEnabled` | `apps/app/src/app/lib/den.ts:1856-1861`, `den-handoff.ts:332-335`, `den.ts:1516-1530` | seeds the cached desktop-config before the first config fetch |

### What the app does with it
- `desktop-config-provider.tsx:95-97` `resolveConnectStateToPush` → `null` if not boolean → `reconciler.setDesired(null)` (`:484-490`), i.e. **nothing is pushed**.
- Otherwise `connect-policy-reconciler.ts` issues `PUT /experimental/connect/state {connectEnabled}` on the local OpenWork server (`desktop-config-provider.tsx:106-123`, `openwork-server.ts:1666`), re-applied per runtime generation.
- UI: `agent-access-card.tsx:141-142` → `openwork-connect-status.ts:14-52` shows "Disabled" summary in Settings → Connect when `false`. Diagnostics report shows it (`agent-context-diagnostics-report.tsx:598`). `useConnectEnabled()` (`desktop-config-provider.tsx:558`) has **no other consumer**.
- **It does not gate the Cloud MCP loop.** `useSessionMcpMaintenance` (`use-session-mcp-maintenance.ts:413-580`) and `syncCloudControlMcpInBackground` (`:217-311`) run whenever signed in + org + workspace; the only skips are signed_out / missing_org / an existing `openwork-cloud` entry with `enabled:false` / a recorded user "disabled" intent (`:265-277`, `cloud-mcp-reconciler.ts:259-274`). So the desktop calls `POST /v1/mcp/token` regardless of `connectEnabled:false`.

### What the local server does with it
- `routes/core.ts:298-306` → `writeConnectState` → `<runtime>/connect-state.json` (`connect-state.ts:22, 87-89, 170-177`). File also holds `cloudMcp` (host-level copy of the `openwork-cloud` MCP config, `:31-37`).
- `getConnectSnapshot` (`connect-state.ts:286-299`): `connectEnabled`, **`connectCatalogEnabled: state.connectEnabled`** (`:294`, same at `:322`) — "connect catalog enabled" is literally the same switch; `cloudMcpPresent = cloudHealth.usable === true`.
- Consumers of the snapshot:
  - `GET /experimental/connect/state` (`core.ts:268-274`) → steering plugin `openwork-extensions-preview-steering.ts:275-302`; `composeOpenWorkExtensionDiscoveryInstruction` (`:332-344`): `connectCatalogEnabled` is consulted **only when there is no cloudHealth**: `false` → plain `OPENWORK_EXTENSION_DISCOVERY_INSTRUCTION`, `true` → `OPENWORK_CONNECT_SIGN_IN_INSTRUCTION` ("direct the user to sign in… Settings → Connect"). If the engine reports an `openwork-cloud` MCP status, that wins outright (`:372-383`, `:346-351`).
  - Diagnostics `expectedConnectBranch` (`agent-context-diagnostics.ts:261-268`): `"extensions-only"` when catalog disabled and no health.
  - `POST /experimental/extensions/call` (`core.ts:322` → `extensions/index.ts:52-53`) uses `cloudHealth` only.
- **Not consulted at all** by `connect-automation-catalog.ts`, `connect-skill-catalog.ts`, `cloud-native-skills.ts`, `engine-v2-preview.ts` (reads global runtime `openwork-cloud`, `:341`), or `mcp.ts` (only deny-diagnostics tool ids `:26-28, :76`). They read whichever `openwork-cloud` config exists (global runtime row → connect-state `cloudMcp` → per-workspace rows; `connect-skill-catalog.ts:75-83`, `connect-automation-catalog.ts:82-90`).
- Separate `connectCatalogEnabled` inside Cloud MCP health (`cloud-mcp-health.ts:662, 2301`) comes from the **reconcile body**, defaulting `true` (`cloud-mcp-reconciler.ts:210`); nothing wires desktop-config into it. Shown as "Safe capabilities: schema v1; connect catalog enabled" (`advanced-view-sections.tsx:461`) — "schema v1" is just `CloudMcpHealth.schemaVersion: 1` (`cloud-mcp-health.ts:2297`); there is no separate "safe capabilities schema" document.

**Net:** `connectEnabled` is a prompt-steering + Settings-label switch. Setting it `false` makes the agent stop telling users to sign in to Connect, nothing more.

---

## 2. CLOUD MCP CONTRACT (Den side)

### 2.1 Token mint — `POST /v1/mcp/token`
Client: `den.ts:3164-3176`, `mintCloudControlMcpToken:3661-3673`.

| Item | Value |
|---|---|
| Headers | `Authorization: Bearer <session token>`, `x-openwork-org-id`, `x-openwork-legacy-org-id` (`den.ts:84-85`, `:2884-2900`), `credentials: include` |
| Body | `{"scopes":["mcp:read","mcp:write"]}` |
| Response (required, `parseDenMcpToken` `den.ts:2039-2061`) | `token` string, `expiresAt` ISO string, `organizationId` string, `resource` string; optional `scopes[]`, `appHostToken`+`appHostExpiresAt` (both strings, else ignored) |
| Failure | missing field → `DenApiError 500 invalid_mcp_token_payload`; HTTP 404 → maintenance `failed`, non-retryable (`use-session-mcp-maintenance.ts:110-123`) → badge "Needs attention" |
| Hosted reference | `ee/apps/den-api/src/routes/mcp/index.ts:38-50, 88-133`; TTL 7 days (`mcp/token-lifetime.ts:24`); `resource` = `<origin>/mcp` or `<origin>/api/den/mcp` behind the web proxy (`mcp/resource.ts:34-45, 102-112`) |

Token metadata (`organizationId`, `expiresAt`, `resource`, `scopes`) is echoed into the local reconcile payload (`cloud-mcp-reconciler.ts:155-162`); `organizationId` must equal the active org id or health fails `cloud_token_org_mismatch` (`cloud-mcp-health.ts:828-839`). Refresh margin 24 h before `expiresAt` (`use-session-mcp-maintenance.ts:35`); maintenance ticks every 5 min / on focus / online (`:33, 552-558`).

### 2.2 Endpoint URL derivation
`resolveMcpUrl` (`cloud-mcp-reconciler.ts:179-184`): `url = resolveCloudMcpResourceUrl(token.resource) + "/agent"` (`den.ts:916-931` only heals hosted web-app origins). Server-side `normalizeCloudEndpointUrl` requires http(s), no query/hash, path ending `/mcp/agent` (`cloud-mcp-health.ts:681-698`, error `cloud_endpoint_invalid` `:791-802`). So `resource` **must** end in `/mcp` (e.g. `https://den/api/den/mcp` → `https://den/api/den/mcp/agent`).

The registered OpenCode entry (`cloud-mcp-reconciler.ts:194-203`): `{type:"remote", enabled:true, url, headers:{Authorization:"Bearer <token>"}, oauth:false}` — `oauth` must be `false` (`cloud-mcp-health.ts:816-826`). Persisted as **global** runtime MCP `openwork-cloud` (`:2362-2366`) and fanned out to every workspace when changed (`:2519-2534`). Global persistence by non-owner requires a trusted origin: built-in, loopback, or the **activated enterprise Den origin** (`:727-745`, `enterprise-den-origin.ts`).

### 2.3 Transport requirements (what the endpoint must speak)
Two independent clients hit it: the OpenCode engine (MCP SDK; authoritative for "connected") and the OpenWork server's own probes.

| Requirement | Where enforced |
|---|---|
| `POST` JSON-RPC, `Accept: application/json, text/event-stream`; reply JSON **or** SSE (`data:` frames, first frame matching request id) | `connect-mcp-transport.ts:21-69, 77-86`; `cloud-mcp-health.ts:1221` |
| `initialize` result `protocolVersion` ∈ {`2025-06-18`, `2025-03-26`} (discovery client hard-fails otherwise); health probe reads `mcp-protocol-version` response header or result field | `connect-mcp-transport.ts:118-120`; `cloud-mcp-health.ts:1462-1465` |
| optional `mcp-session-id` response header is echoed back | `connect-mcp-transport.ts:121-127`; `cloud-mcp-health.ts:1466-1470` |
| `notifications/initialized` → **HTTP 202 with empty body** (status !== 202 or any body → reader returns null) | `connect-mcp-transport.ts:128-129` |
| `tools/list` must contain `search_capabilities` and `execute_capability` (engine projects them as `openwork-cloud_search_capabilities` / `openwork-cloud_execute_capability`) | `cloud-mcp-health.ts:24-31, 1042-1052, 1482-1510` |
| 401 → `invalid_mcp_token` (triggers silent re-mint); 403 → `wrong_mcp_resource` | `cloud-mcp-health.ts:1264-1288`; remint logic `cloud-mcp-reconciler.ts:219-257, 386-392` |
| `resources/read` result `contents[]` entry with `uri` **identical** to the request and string `text` | `connect-mcp-transport.ts:139-144` |
| `GET` (standalone SSE): hosted Den returns **405 `Allow: POST`** (`ee/.../mcp/standalone-sse.ts`; 204 is explicitly unsafe with the SDK). An open keep-alive SSE stream (den.mjs) also works. | `ee/apps/den-api/src/mcp/agent.ts:407-409` |
| Probe timeout 5 s per request | `connect-mcp-transport.ts:82`; `cloud-mcp-health.ts:38-40` |
| `initialize` result `instructions` — OpenCode injects it into the system prompt; the steering text relies on it for the "Connect contract" | `openwork-extensions-preview-steering.ts:145-154`; hosted text `agent.ts:174-192, 302-314` |

### 2.4 App wiring into every workspace
- `useSessionMcpMaintenance` (`use-session-mcp-maintenance.ts:413-580`) per active workspace → `syncCloudControlMcpInBackground` → `runOpenworkCloudMcpReconciler(mode:"repair", probe:true)` (`cloud-mcp-reconciler.ts:339-426`): health first; if not usable/expired → mint → `POST /workspace/:id/mcp/openwork-cloud/reconcile` (`routes/cloud-mcp.ts:151`) with payload from `buildOpenworkCloudMcpReconcilePayload` (`:186-217`).
- Server `reconcileOpenworkCloudMcp` (`cloud-mcp-health.ts:2480-2611`): validate → persist global desired → fan-out → private App-host catalog (`reconcileConnectMcpCatalog`) → register MCP in engine → poll `connected` → health.
- Retries `[1s,3s,10s,30s,60s]` only if `issue.retryable` (`:38, 346-386`).

### 2.5 Health / "usable" criteria
`usable = firstFailure === null` (`cloud-mcp-health.ts:2299`). Failures accumulate from: desired config present + strictly valid (`:2216-2228, 767-855`), workspace directory + engine base URL (`:2229-2246`), no tool denies (`:2247-2248`, `mcp.ts:76`), engine MCP status `connected` (`:1929-1943`), engine tool ids include both prefixed tools (`:1962`), direct probe ok (only when `probe:true`; a transport-level failure is diagnostic only, `:1977-1982, 1511-1524`), provider projection (`:1987-1996`), **plugin canaries**.

**Plugin canaries** `openwork_docs_search`, `openwork_query` (`:32-35, 1963, 1998-2007`) are tools provided by the **local** OpenWork OpenCode plugins (`opencode-plugins/openwork-capabilities-knowledge.ts:218`, `openwork-extensions-preview.ts:1354`), not by the Den. Missing → `extensions_plugin_missing` (retryable: reload engine). Nothing for a Den to serve.

`usableByCurrentModel` (`:2127-2132`) = provider projection of the two tool ids for the selected model.

---

## 3. CAPABILITIES MODEL

### 3.1 Tools (hosted reference, `ee/apps/den-api/src/mcp/agent.ts`)
| Tool | Input (`:552-557`, `:583-589`) | Output |
|---|---|---|
| `search_capabilities` (readOnly annotations `:118-123`) | `query` (req), `limit` 1–20 (def 5), `type` ∈ all/api/admin/mcp/marketplace/skills/connectors, `intent` ∈ discover/connect | `{ matches: CapabilityMatch[], hint?, connectionAction?, connectorCatalog? }` as text JSON + `structuredContent` (`:240-256`, schema `:144-172`) |
| `execute_capability` (destructive annotations `:124-129`) | `name` (exact match name), `schemaDigest?` (`sha256:<64hex>`), `path?`, `query?`, `body?` | tool result; skill capabilities return the SKILL.md text (`:578`); errors `unknown_capability`, `invalid_capability_arguments`, `needs_connection`/`connection_not_connected`, `capability_timeout` (180 s `:116, 258-267`) |

### 3.2 CapabilityMatch schema (`mcp/search.ts:23-49`, `agent.ts:144-165`)
`name, method, path, score, summary, pathParams[], queryParams[], hasBody, bodySchema?, querySchema?, outputSchema?, argumentsSchema?, schemaDigest?, invocation?:{argumentsField:"body"}, kind?, mcpApp?:{resourceUri}, status?, hint?, connectionStatus?, scriptPath?`.

`kind` values in the hosted registry: `native`, `admin`, `catalog`, `marketplace` (Workflows appear as marketplace with kind `workflow` per description `:545`), `skill`, `mcp_app`, `connection_status`, `remote_session` (grep across `capability-registry.ts`, `marketplace-capabilities.ts`, `external-capabilities.ts`, `native-capabilities.ts`, `builtin-skills.ts`, `remote-session-capabilities.ts`). Name namespaces: native `<connector>:…`, external MCP `mcp:<connectionId>:<tool>` (`:190`), skills `skill:<name>` (`builtin-skills.ts:10`), marketplace `plugin:<pluginId>:<configObjectId>` (`marketplace-capabilities.ts:272-275`; regex in `connect-skill-catalog.ts:29`).

### 3.3 Resources the desktop reads
| URI | Reader | Schema |
|---|---|---|
| `skill://index.json` | v1 prompt catalog `connect-skill-catalog.ts:15-31, 42-51` (**strict**: `$schema` = `https://schemas.agentskills.io/discovery/0.2.0/schema.json`, `skills[].name` kebab-case ≤64, `type:"skill-md"`, `description` ≤1024 req, `url` `skill://…`, `capability` `skill:x` or `plugin:a:b`, optional `title/marketplaceName/pluginName`); v2 native sync `cloud-native-skills.ts:82-88` (**lenient**: `name`, `type`, `url` only) | hosted builder `agent.ts:210-227` |
| `skill://<name>/SKILL.md` | `cloud-native-skills.ts:130-143` (≤256 KiB, ≤200 skills) | markdown with `name:`/`description:` frontmatter (`agent.ts:229-232`) |
| `automation://index.json` | `connect-automation-catalog.ts:11, 28-44` (`fetchedAt, total, omitted, automations[{id,name,state,schedule{kind:once/daily/weekly,…},nextDueAt,latestRun}]`) | hosted `mcp/automation-index.ts` |
| `openwork://connect/mcp-servers/index.json` | `connect-mcp-server-catalog.ts:16-50` (`schemaVersion:"openwork.connect/mcp-servers/1"`, `servers[{connectionId,name,description,url,exposeDirectly}]`), requires `appHostToken` + header `x-openwork-mcp-client-capabilities: mcp-app-host-v1` (`:26-27, 331-338`) and a **trusted origin** (built-in, loopback in dev mode, or activated enterprise Den `:171-184`) | hosted `mcp/connect-mcp-server-index.ts` |

### 3.4 How the prompt uses them
- Base prompt "## Connected work" (`apps/server/src/openwork-agent-prompt.ts:45-47`): discover with `openwork-cloud_search_capabilities`, run with `openwork-cloud_execute_capability` using exact returned name.
- Per-request `experimental.chat.system.transform` (`openwork-extensions-preview.ts:1301-1334`) appends: routing steering (ready / sign-in / disabled / extensions-only, `steering.ts:136-160`), skill-authoring mode (cloud vs local, `:353-361`), `<available_remote_skills>` (`connect-skill-catalog.ts:149-191`: "call openwork-cloud_execute_capability with { name: <capability> }… read the returned SKILL.md"), `<available_automations>` (`connect-automation-catalog.ts:124-158`).
- Engine v2 preview (off by default, `engine-v2-preview.ts:87-95, 114-128`) replaces "remote skills" text with native skills (`opencode-v2-instructions.ts:113-127`) and materializes `skill://` bodies into `<runtime>/cloud-skills/<scope>/openwork-cloud-<hash>/SKILL.md` on every prompt admission (`server.ts:1265-1286`, `cloud-native-skills.ts:174-215`).

---

## 4. RELATED DEN ENDPOINTS

All parsed in `apps/app/src/app/lib/den.ts`; all sent with Bearer + `x-openwork-org-id`.

| Endpoint | Desktop use | Minimal payload (parser) |
|---|---|---|
| `GET /v1/mcp-connections?scope=usable` | Connection cards/OAuth reconnect in chat & dashboard (`session-surface.tsx:3089`, `dashboard-connection-card.tsx:32`, `cloud-inventory-cache.ts:118`, `use-org-mcp-connections.ts:286`) | `{connections:[{id,name,url,authType:oauth\|apikey\|none,credentialMode:shared\|per_member,exposeDirectly?,connected?,connectedAt?,connectedForMe?,…}]}` (`:2131-2175`) |
| `GET /v1/mcp-connections/presets` | Settings → MCP quick-add list (`mcp-view.tsx:507`) | `{presets:[{presetId,displayName,description,url,authType}]}` (`:2177-2207`) |
| `POST /v1/mcp-connections/:id/connect/start`, `…/disconnect-my-account`, `POST /v1/oauth-providers/:id/disconnect` | per-member OAuth (`:3484-3510`) | `{status:"connected"\|"needs_auth", authorizeUrl}` (`:2209-2221`) |
| `GET /v1/me/library` | Connect capability inventory in composer (`connect-capability-inventory.ts:236`), extensions store (`extensions-store.ts:2304`) | `{items:[{type:"plugin",id,name,description?}]}` (`:2703-2715`) |
| `GET /v1/marketplaces?status=active&limit=100` | same inventory + Library "add item" + onboarding (`connect-capability-inventory.ts:254`, `add-library-item-modal.tsx:315`, `org-onboarding-page.tsx:619`) | `{items:[{id,name,description?,status?,pluginCount?,updatedAt?}]}` (`:2625-2656`) |
| `GET /v1/resources/marketplace-capabilities` | which marketplace skills/plugins are assigned to me (`connect-capability-inventory.ts:235`) | `{items:[{configObjectId,marketplaceId\|null,objectType,pluginId}]}` (`:2681-2701`) |
| `GET /v1/marketplaces/:id/resolved`, `GET /v1/plugins/:id/resolved` | plugin/file listing for cloud plugin import | `{item:{marketplace,plugins:[…]}}`, `{items:[memberships]}` (`:2658-2679`) |
| `GET /v1/resources` | `desktop-cloud-sync.ts:112-117` → `POST /workspace/:id/desktop-cloud-sync` diff of installed cloud plugins vs timestamps (`apps/server/src/desktop-cloud-sync.ts`) | `{organizationId,orgMemberId,teamIds[],resources:{llmProviders:{[id]:isoTs},marketplaces:{[id]:{lastUpdatedAt,plugins:[{pluginId,lastUpdatedAt,configItems:[{configItemId,lastUpdatedAt}]}]}}}}` (`:658-675`; `organizationId`, `orgMemberId`, `resources` required) |
| `GET /v1/automations?limit=100` (+CRUD, `/run`, `/runs`, `/v1/automation-runs/:id`) | Automations page + session route (`automations-page.tsx:177`, `session-route.tsx:438`) | `AutomationList` (`packages/types/src/automations.ts:474`): `{items:[{automation,revision,latestRun}],nextCursor}` — empty `{items:[],nextCursor:null}` works |
| `POST /v1/cloud-automations` | web "run in cloud" creation only (`den.ts:3340-3350`) | `AutomationDetail` |
| `GET /v1/workers`, `POST /v1/workers/:id/tokens`, `/v1/cloud/instance*` | hosted OpenWork Web / cloud workspace overlay (`cloud-workspace-overlay.tsx:195`) — not Connect | skip |
| skills sync | **no REST endpoint**; skills travel through the MCP resources (§3.3/§5) | — |

---

## 5. NATIVE SKILLS PUSH (`cloud-native-skills.ts`)

Path: MCP resources, not a Den REST route.
1. `fetchCloudNativeSkills` (`:95-146`) opens one Streamable-HTTP session (`openMcpResourceReader`, `connect-mcp-transport.ts:99-146`) against the **global** `openwork-cloud` config (`engine-v2-preview.ts:341`), reads `skill://index.json` (≤1 MiB), keeps entries with `type:"skill-md"`, dedupes URLs, then reads each `url` via `resources/read` (4 concurrent, ≤256 KiB each). Any failure throws a `CloudNativeSkillSyncError` code (`:23-31`) and the registry is **cleared** (fail closed, `:274-284`).
2. `materializeCloudNativeSkills` (`:174-215`): `<runtime>/cloud-skills/<sha256(url+Authorization)[:16]>/openwork-cloud-<sha256(uri)[:16]>/SKILL.md`, 0600/0700, atomic renames; scope dir registered in the engine's `skills` config list (`engine-v2-preview.ts:338-347`).
3. Triggered on every prompt admission (`server.ts:1265-1286`); config change invalidates scope (`engine-v2-preview.ts:549-553`).
4. Requires `OPENWORK_ENGINE_V2_PREVIEW=1|chat|sidecar` or persisted preview state (`engine-v2-preview.ts:87-95`). Default desktop = v1 → skills reach the agent only via the `<available_remote_skills>` prompt block + `execute_capability` (strict index schema, §3.3).

Payload shape (lenient): `{"skills":[{"name":"<≤64>","type":"skill-md","url":"skill://<name>/SKILL.md"}]}`; body = markdown text returned under the exact `uri`.

---

## 6. CHEAPEST USEFUL SUBSET PER GOAL

Prerequisite for every goal: `POST /v1/mcp/token` returning `{token, expiresAt, organizationId(=active org), scopes, resource:"<origin>/api/den/mcp"}` and an MCP endpoint at `<resource>/agent` that passes §2.3 (initialize with `protocolVersion:"2025-06-18"` + `instructions`, 202 on `notifications/initialized`, `tools/list` with `search_capabilities` + `execute_capability`, 401 on bad bearer). Den origin must be the activated enterprise origin or loopback for global persistence (`cloud-mcp-health.ts:727-745`).

**(c) Green badge** — exactly the prerequisite. Badge = `resolveOpenWorkConnectStatus` on maintenance state `ready` (`openwork-connect-status.ts:81-87`), which needs `health.usable` (`use-session-mcp-maintenance.ts:312-318`). Stub tools returning empty `matches` are enough. Also set `connectEnabled:true` (or omit) so Settings → Connect doesn't label it "Disabled" and the steering picks the "ready" branch.

**(a) Push corporate skills**
- Serve `resources/read` for `skill://index.json` + one `skill://<name>/SKILL.md` per skill.
- For default (v1) desktops the index must satisfy `connect-skill-catalog.ts:19-31` (`$schema`, `description`, `capability:"skill:<name>"`), **and** `execute_capability {name:"skill:<name>"}` must return the SKILL.md text (`agent.ts:578`, `capability-registry.ts:662-669`). Optionally `search_capabilities` with `type:"skills"` returning `{name:"skill:<name>", kind:"skill", summary, method:"", path:"", pathParams:[], queryParams:[], hasBody:false}`.
- v2-preview desktops need only the lenient index (§5).

**(b) Expose own MCP servers (ach-memory, LiteLLM /mcp)** — two options:
1. *Direct exposure* (native OpenCode MCP entries, tools called directly by the model): `openwork://connect/mcp-servers/index.json` with `servers[{connectionId,name,description,url,exposeDirectly:true}]`; requires `appHostToken` in the mint response, the App-host header, trusted origin, and `url` on the **same origin** as the cloud MCP URL (`connect-mcp-server-catalog.ts:133-162` fails closed cross-origin unless it is the built-in hosted pair) → i.e. reverse-proxy `…/mcp/agent/connections/<id>` on the Den and re-use the member bearer (`directConnectMcpRuntimeEntries` `:219-234`). Also `/v1/mcp-connections` entries with `exposeDirectly:true` for the Settings UI.
2. *Via capabilities* (cheaper): proxy inside `search_capabilities` / `execute_capability`: list downstream tools as matches `{name:"mcp:<connId>:<tool>", kind:"mcp", argumentsSchema, schemaDigest, invocation:{argumentsField:"body"}}` and forward `body` on execute. No extra endpoints, no App-host token, no origin constraints.

---

## Reconciliation of `den.mjs` with the code

| den.mjs | Verified against | Status |
|---|---|---|
| `resource: ${ORIGIN}/api/den/mcp` and endpoint `/api/den/mcp/agent` (`:215, :443`) | `cloud-mcp-reconciler.ts:179-184`, `cloud-mcp-health.ts:681-698` | correct; loopback trusted for global persist |
| Token response fields incl. `scopes`, no `appHostToken` (`:435-441`) | `den.ts:2039-2061` | correct; App-host catalog just stays `missing_app_host_auth` (retried hourly, `cloud-mcp-reconciler.ts:120-123`) |
| Comment: green only when the two tools show up (`:212-214`) | `cloud-mcp-health.ts:24-31, 1482-1510` | correct |
| `initialize` echoes requested `protocolVersion` else `2025-06-18` (`:269`); no `instructions` | `connect-mcp-transport.ts:120` | works; adding `instructions` is what the "ready" steering assumes exists (`steering.ts:145-154`) |
| 202 empty for notifications (`:454-457`) | `connect-mcp-transport.ts:129` | correct (trap: any body breaks discovery) |
| `resources/read` returns `uri` verbatim (`:304`) | `connect-mcp-transport.ts:142` | correct, real trap |
| GET → open SSE stream (`:466-479`) | hosted returns 405 (`standalone-sse.ts`) | both acceptable; 405 is simpler |
| MCP tokens persisted separately from session tokens (`:239-241`) | 401 → `invalid_mcp_token` → remint (`cloud-mcp-reconciler.ts:240-241`) | sound; a restart that forgets tokens would only trigger a remint |
| Skill index `{name,type,url}` only (`:188, :202`) | lenient v2 schema `cloud-native-skills.ts:82-88` ✔; **strict v1 schema** `connect-skill-catalog.ts:19-31` ✘ (missing `$schema`, `description`, `capability`) and `execute_capability` stub never returns SKILL.md | skills only reach v2-preview desktops; default v1 desktops get no `<available_remote_skills>` block |
| `automation://index.json` `{fetchedAt,total:0,omitted:0,automations:[]}` (`:205`) | `connect-automation-catalog.ts:28-44` | correct → "This member owns no Automations" guidance |
| CORS `Access-Control-Allow-Headers` lists `x-organization-id,x-openwork-organization-id` (`:138`) | app sends `x-openwork-org-id`, `x-openwork-legacy-org-id` (`den.ts:84-85`) | mismatch; harmless only if the webview skips CORS preflight — worth adding the real names |
| `connectEnabled:false` in desktop-config and exchange (`:67, :391`) | §1 | only affects steering/labels; the desktop still mints and registers the MCP |
| `/api/den/v1/resources` `{organizationId, orgMemberId, teamIds, resources:{llmProviders:{}, marketplaces:[]}}` (`:97-102`) | `den.ts:658-675` — `marketplaces` should be an object; an array is tolerated (`:642` → `{}`) | fine |
| Brand accent / blockedCommands traps (`:31-32, :50-51`) | `desktop-policies.ts:302`, `managed-policy-rules.ts:77-78` | as commented (not re-verified here) |

Current `openwork.py` (`:197, :335, :411-427`) returns 404 `not_implemented` for `POST /v1/mcp/token`, which is why the badge shows "Needs attention" (non-retryable 404 → `failed`, `use-session-mcp-maintenance.ts:110-123`).
