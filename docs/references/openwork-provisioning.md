<!-- Research report, 2026-09-19, from the OpenWork source. What a Den can and cannot push
     to replace the manual opencode.json / env setup. Companion to openwork-connect.md. -->

# Den-driven provisioning vs. manual OpenCode setup — research report

Repo: `/home/jcm/Projects/openwork` (all paths below are under this root; `S` = `/home/jcm/Projects/openwork/apps/server/src`, `A` = `/home/jcm/Projects/openwork/apps/app/src`, `E` = `/home/jcm/Projects/openwork/apps/desktop/electron`, `T` = `/home/jcm/Projects/openwork/packages/types/src/den`). Builds on `/home/jcm/Projects/alitellm-auth/docs/references/openwork-connect.md`.

**Headline:** the desktop does NOT read `~/.config/opencode/opencode.json` for Den content and never writes it. Everything Den-driven lands in the OpenWork server's runtime DB (`ENGINE_GLOBAL` row) and is rendered into `<runtime>/runtime-opencode-config.json`, passed to the engine as `OPENCODE_CONFIG` (`S/openwork-runtime-config.ts:4-16, 139-141`; `S/embedded.ts:203-221`). The user's own `~/.config/opencode/opencode.json` is still loaded by OpenCode as its global config alongside it (OpenWork only writes a `{$schema}` stub into the workspace if missing: `E/runtime.mjs:1853-1862`).

---

## 1. Models / providers via Den

### Endpoints and parsers
| Endpoint | Consumer | Parser |
|---|---|---|
| `GET /v1/llm-providers` (no scope) then `GET /v1/llm-providers/:id/connect` per provider | server `CloudProviderSync` every 5 min + on session (`S/cloud-provider-sync.ts:501-514, 222, 1194-1207`) | `parseProviderList`/`parseProviderConnection` `:321-364` |
| `GET /v1/inference-providers?scope=usable` (+ `/:id/connect`, `/:id/oauth/start`) — Gateway `ipr_*` rows; 404/405/501 = "Den has no gateway" | `:516-539`, OAuth `:990-1017` | `parseInferenceProvider` `:380-405` (strict: model ids `gwm_…`, `upstreamModelId`, `credentialSetId`, apiKey must start `ow_gw_`, env names prefixed `IPR_…_` `:428-436`) |
| `GET /v1/llm-providers?scope=usable` + `GET /v1/inference-providers?scope=usable` | policy check when `allowCustomProviders=false` and user picks a model (`S/managed-desktop-policy.ts:219-255`) | inline |
| desktop copies | `A/app/lib/den.ts:2074-2130` (`DenOrgLlmProvider`, type `:316-344`), `/connect` parser `:2223-2238`; desktop-side manual import `A/react-app/domains/connections/provider-auth/store.ts:1258, 1869` (legacy, user-clicked) |

Den session reaches the server via `PUT /den-session {baseUrl, token, orgId}` (`S/server.ts:3040-3046` → `cloudProviderSync.setSession`), sent by the desktop (`A/app/lib/openwork-server.ts:1624-1625`).

### Required list payload shape (server parser, strict — any bad row fails the whole list `:328`)
```json
{"llmProviders":[{
  "id":"lpr_<26 lowercase alnum>",        // /^lpr_/ on list (:296); ownership restore needs /^lpr_[a-z0-9]{26}$/ (:1522)
  "providerId":"openai-compatible",        // becomes inner `id`
  "name":"ACKstorm",
  "source":"custom",                       // "openwork" => runtime key "openwork" (:574-576); else key = lpr_ id
  "updatedAt":"ISO",
  "providerConfig":{"env":["ACKSTORM_API_KEY"],"npm":"@ai-sdk/openai-compatible",
                    "api":"https://api.ackstorm.ai/v1","options":{"baseURL":"https://api.ackstorm.ai/v1"},
                    "whitelist":[],"blacklist":[]},
  "models":[{"id":"gpt-x","name":"GPT X","config":{ ...per-model metadata... }}]
}]}
```
`/connect` payload: `{"llmProvider":{...same..., "apiKey":"<secret>" | "apiKeys":{"ENV_NAME":"<secret>"}, "memberCredential":{"state":"active|missing|blocked|stale|error"}}}` (`:334-364`). Example fixture: `S/cloud-provider-sync.e2e.test.ts:81-99`.

### What gets written into the engine config (`buildProviderConfig` `:642-664`, `buildModelConfig` `:625-640`)
`provider["lpr_xxx"] = { id: providerId, name, env: [...], models: {<id>: {id, name, + passthrough}}, npm, api, options (verbatim), whitelist, blacklist }`.
Per-model passthrough keys (`:223-239`): `family, release_date, attachment, reasoning, temperature, tool_call, interleaved, cost, limit, modalities, status, options, headers, provider, variants` → **yes**, modalities (image/audio/pdf), cost, limit, reasoning, tool_call, attachment all survive. Written to the ENGINE_GLOBAL runtime row (`:1273-1276`) → rendered into `OPENCODE_CONFIG` file (`S/openwork-runtime-config.ts:65, 113`); engine reload deferred while sessions are busy (`:1322-1358`).

Note: the OpenCode provider key is the Den id `lpr_…` (model ids become `lpr_…/model`), not `"ackstorm"` — only `source:"openwork"` maps to a fixed key.

### API key: long-lived secret on disk, twice
1. `providerConfig.env[0]` ← `apiKey` (or every `apiKeys` entry) upserted into `~/.config/openwork/env.json` (0600) via `EnvService` (`:603-623, 1278-1281`; path `packages/paths/index.mjs:123-130`).
2. Delivered to the engine with `PUT <engine>/auth/<lpr_id> {type:"api", key}` (`S/managed-provider-auth.ts:326-331`) → OpenCode's own auth store. Re-seeded on every standby generation ("Engine standby seeded with managed provider credentials." `S/server.ts:5574-5590`).
- No `{env:VAR}` reference mode: if `env` names are declared and no key arrives (and no local env.json value matches), the provider is **skipped** `missing_credentials` (`:707-719`); with `env: []` it is materialized without auth (`managed-provider-auth.ts:302-306` skips `no_env_names`). `options` is passed verbatim, so `options.apiKey:"{env:X}"` would reach OpenCode's substitution — untested path, and the v2 sidecar explicitly ignores `{env:` keys (`S/engine-v2-preview.ts:223`).
- Per-member keys: `memberCredential.state !== "active"` → skipped `needs_key` (`:681-689`); binding happens Den-side (desktop only reads `hasMyCredential`, `A/app/lib/den.ts:337-341`).
- Plugin-minted credentials: not a Den concept (see §3).

### Provider gating
- `allowCustomProviders:false` in `/v1/me/desktop-config` → engine config gets `enabled_providers: [all lpr_/ipr_/openwork keys, + "opencode" unless allowZenModel:false]` (`S/openwork-runtime-config.ts:68-71`); server blocks `POST /runtime-config/providers`, engine `/auth/*`, `/provider/*/oauth` for other ids and model selection not in Den grants (`S/managed-policy-rules.ts:98-100, 117`; `S/managed-desktop-policy.ts:206-212, 219-255`). Also `disabled_providers` union from runtime rows (`S/runtime-opencode-config-store.ts:603-606`).
- Policy schema: `T/desktop-policies.ts:34-126` (`allowCustomProviders`, `allowZenModel`, `allowMultipleWorkspaces`, `allowControlSettings`, `allowManageExtensions`, `allowBuiltInExtensions`, `allowAlphaUpdates`, `showWelcomePage`), `execution` (`:177-189`), `desktopConfigSchema` `:330-346`.

### OPENCODE_MODELS_URL
- Honored: `resolveOpencodeModelsUrl` returns `process.env.OPENCODE_MODELS_URL` if set, else **`https://models.openworklabs.com/`** (not models.dev) (`S/opencode-models-url.ts:3-17`); injected at engine spawn (`S/embedded.ts:209-221`, `S/managed-opencode-v2.ts:146,180`, pool fingerprint `S/engine-pool.ts:410`).
- Source of that env: Electron's `process.env` (whatever the GUI launcher inherited) + env.json, but env.json **strips `OPENCODE_*`/`OPENWORK_*`** (`E/runtime.mjs:729-748`, `S/env-file.ts:22-28`). So only a launcher/systemd/MDM-set env var works; no login-shell import exists.
- **No Den field** for a catalog URL. `T/inference.ts:56` only references models.dev for hosted aliases.

---

## 2. Environment variables

| Item | Finding |
|---|---|
| `~/.config/openwork/env.json` | `{schemaVersion:1, updatedAt, variables:[{key,value,updatedAt}]}` (`S/env-file.ts:36-40, 114-152`), 0600 |
| Writers | user via `PUT /env` (host-token, `S/routes/core.ts:434-470`, Settings → Environment) and **only one Den path**: `CloudProviderSync` upserting provider credential env names (`S/cloud-provider-sync.ts:1278-1281`) — `grep upsertMany` shows no other writer |
| Injection | Electron merges env.json under `process.env` at server start (`E/runtime.mjs:1546-1598, 1918-1920`); managed engine spawns with `...process.env` (`S/managed-opencode.ts:164-173`). Changes need an engine/server restart; managed-provider-auth exists precisely because the running engine never re-reads the store (`S/managed-provider-auth.ts:13-22`) |
| Reserved | keys starting `OPENWORK_`/`OPENCODE_` rejected (`S/env-file.ts:22-28, 211-213`) except `OPENWORK_API_KEY`, `OPENWORK_MODELS_API_KEY`, `OPENWORK_INFERENCE_BASE_URL`, `OPENWORK_MODELS_BASE_URL` |
| `OPENCODE_ENABLE_EXA` | Setting `openwork.opencodeEnableExa` exists in the UI (`A/react-app/domains/settings/state/debug-view-model.ts:54,143-144,741`) and is passed to `engineStart` (`E/runtime.mjs:2212`) but **never turned into an env var** — dead option (no `OPENCODE_ENABLE_EXA` anywhere in `E/*.mjs` or `S/*.ts`). Cannot come from env.json (reserved prefix) |
| Den control of web search | only **deny**: `execution.browserOrigins` set → `permission.websearch/webfetch = "deny"` (`S/managed-policy-rules.ts:32-36, 43-55, 103`) rendered into engine config (`S/openwork-runtime-config.ts:63, 72, 80`). No allow/enable path |

Workaround for a non-reserved var (e.g. `ACH_MEMORY_API_KEY`): declare it in a Den llmProvider `providerConfig.env` + `apiKeys` — the sync writes any valid key name (`:603-614`); ownership tracked by hash so a later user edit is preserved (`:1256-1260`).

---

## 3. Plugins via Den

- "Cloud plugin" = Den `plugin` resource with `memberships[].configObject` of `objectType ∈ {skill, agent, command, tool, mcp, hook, context, custom}` (+ `workflow`/`script` app-side) (`A/app/lib/den.ts:2252-2258`; server `S/cloud-plugins.ts:13, 109-123`). **There is no `plugin` objectType** — OpenCode `plugin: [...]` entries (JS/URL plugins like `https://platform.ackstorm.ai/public/opencode-auth`) cannot be expressed.
- Resolved payload (`GET /v1/plugins/:id/resolved` → `{items:[{id, pluginId, configObjectId, configObject:{id, objectType, title, description, currentFileName, currentFileExtension, currentRelativePath, status:"active", updatedAt, latestVersion:{id, rawSourceText, normalizedPayloadJson, sourceRevisionRef, createdAt}}}]}` (`den.ts:2261-2287, 2637-2648, 2671-2679`). Marketplace: `GET /v1/marketplaces?status=active&limit=100` → `{items:[{id,name,description,status,pluginCount,updatedAt}]}` and `/v1/marketplaces/:id/resolved` → `{item:{marketplace, plugins:[{id,name,description,status,memberCount,updatedAt,componentCounts,extension?,cloudReadiness?}]}}` (`:2603-2669`). `/v1/me/library` → `{items:[{type:"plugin",id,name,description}]}` (`:2703-2715`).
- Install = `POST /workspace/:id/cloud-plugins {marketplaceId, marketplace, resolved}` (`S/server.ts:2610`) → `installCloudPlugin` (`S/cloud-plugins.ts:536-647`): skill → `.opencode/skills/<ns>/<name>/SKILL.md`, agent → `.opencode/agents/<ns>/<name>.md`, command → `.opencode/commands/<ns>/<name>.md`, tool → `.opencode/tools/<ns>/<name>.ts`, hook/context/custom → files (`:226-258`); mcp → `addMcp()` into the **workspace** runtime row (`:559-575`), i.e. workspace-scoped, not global. Record kept in KV store `cloud_plugin_install_configs` (`:479-498`).
- **Manual, not pushed**: `importCloudOrgPlugin` is a user action gated by `allowManageExtensions` (`A/react-app/domains/settings/state/extensions-store.ts:1230-1268, 1218-1223`). Marketplace polling only raises "New extension available" / "update available" notifications (`:1185-1210, 561-604`); no auto-install (`grep orgWide|autoInstall` → none). `GET /v1/resources` + `POST /workspace/:id/desktop-cloud-sync` only diff timestamps (`S/desktop-cloud-sync.ts:1-25, 210-260`).
- OpenCode `plugin` entries are added only via local `POST /workspace/:id/plugins {spec}` (`S/server.ts:3405-3437` → `S/plugins.ts:95-105`, spec only non-empty `S/validators.ts:21-25`), stored ENGINE_GLOBAL and appended after OpenWork's built-in plugins (`S/openwork-runtime-config.ts:94-109`). Blocked when `allowManageExtensions=false` (`S/managed-policy-rules.ts:115, 131-132`).

---

## 4. MCP servers via Den

| Path | Shape accepted | Scope | Secrets |
|---|---|---|---|
| Cloud plugin `objectType:"mcp"` (`latestVersion.normalizedPayloadJson` or `rawSourceText` JSON) | `{mcp:{name:{...}}}` / `{mcpServers:{...}}` / bare config. **Local stdio accepted**: `command` (array or `command`+`args`) + `environment`/`env` string map → `{type:"local", command, environment, enabled}`; remote: `url`, `headers`, `oauth` (`S/cloud-plugins.ts:346-407`; app mirror `extensions-store.ts:812-873`; validator `S/validators.ts:52-66`). Name namespaced `<plugin>-plugin-<name>` (`:338-344`) | per-workspace runtime row; manual install (§3) | `environment` values written verbatim to the runtime DB and config file; `{env:X}` would be substituted by OpenCode from the engine env (env.json vars are in it — §2) |
| `/v1/mcp-connections?scope=usable` + `openwork://connect/mcp-servers/index.json` (`exposeDirectly:true`) | **remote only**, same-origin as cloud MCP URL, bearer = member MCP token (`S/connect-mcp-server-catalog.ts:16-50, 133-162, 219-234`) | global, automatic | per-member OAuth via `POST /v1/mcp-connections/:id/connect/start` (`den.ts:3484-3510`), `credentialMode:"per_member"` (`den.ts:352-357`) |
| Den MCP embedded in cloud plugin via `openworkManaged:"den_external_mcp"` + `externalMcpConnectionId` | pointer to a Den connection, no local config (`extensions-store.ts:881-906, 1000-1016`) | — | Den-side |
| Presets `GET /v1/mcp-connections/presets` | `{presets:[{presetId,displayName,description,url,authType}]}` — remote quick-add only (`A/react-app/domains/settings/pages/mcp-view.tsx:507`, `den.ts:2177-2207`) | manual | — |
| `local-managed-mcp.ts` | OAuth-managed *remote* MCP proxied locally, not stdio (`S/local-managed-mcp.ts:1-60`) | — | — |

So: stdio `ach-memory` is pushable only as a cloud-plugin MCP component (user clicks Install, per workspace). Per-member secrets for a stdio server have no provisioning path except (a) `{env:ACH_MEMORY_API_KEY}` + the env.json hack in §2, or (b) a shared value in `environment`.

---

## 5. Skills via Den
Confirmed both paths from the prior doc: (1) `skill://index.json` + `skill://<name>/SKILL.md` over the cloud MCP (v1 prompt catalog `S/connect-skill-catalog.ts`; v2 materialized into `<runtime>/cloud-skills/...` and registered via `setSkills` `S/engine-v2-preview.ts:338-347`, `S/managed-opencode-v2.ts:129`). (2) Cloud plugin `objectType:"skill"` → `.opencode/skills/<ns>/<name>/SKILL.md` in the workspace with regenerated frontmatter (`S/cloud-plugins.ts:242, 260-271, 580-583`), auto-discovered by OpenCode/OpenWork (`S/skills.ts:192-202`). Nothing writes `skills.paths` in the v1 engine config (`grep skills.paths` → none); not needed.

---

## 6. Bootstrap / enterprise
- File: `~/.config/openwork/desktop-bootstrap.json` (override `OPENWORK_DESKTOP_BOOTSTRAP_PATH`; `packages/paths/index.mjs:194-203`). Normalizer `E/workspace-store.mjs:209-303`: `baseUrl` (required), `apiBaseUrl`, `requireSignin`, `requireActivation`, `brandAppName/LogoUrl/IconUrl`, `writtenAt`, `claimLinks[{id,role,token,url,expiresAt}]`, `handoff{grant,denBaseUrl,orgId,orgName,orgSlug,skillId,skillTitle,createdAt}` (one-time sign-in grant, `:214-234`), `prepared{...skillPath}`, `enterpriseActivation{activatedAt, denBaseUrl}`. Public schema: `packages/install-config/src/index.ts:28-37`.
- Read by Electron (never written by it except via IPC/connect-link, `E/main.mjs:2004-2028`); `requireActivation:false` cannot be self-written by a locked install (`:2008-2013`).
- Flavors: public/cloud/enterprise are build-time (`E/desktop-distribution.mjs:1-49`); enterprise = `requireSignin+requireActivation` and only `connectLinkAccept/Verify`, `get/setDesktopBootstrapConfig` allowed pre-activation (`:73-86`).
- Enterprise activation effects: stamped after connect-link/handoff verify (`E/main.mjs:1203-1213`, `A/react-app/domains/cloud/forced-signin-page.tsx:112-121`); its origin becomes the trusted origin for global `openwork-cloud` persistence and App-host catalog (`S/enterprise-den-origin.ts:31-66`, cloud-mcp-health `:727-745`), chain-repair origins (`E/runtime.mjs:795`), and gates outbound egress until desktop-config resolves (`A/app/lib/enterprise-activation.ts:16-45`). `requireSignin:true` holds the UI at `/signin` (`A/react-app/shell/app-root.tsx:73-100`).
- Pre-seeding: an installer/MDM can drop the JSON file (`writtenAt` newest wins over legacy path, `E/workspace-store.mjs:305-437`); or use `GET /v1/install-config?token=` served by the Den (`{appName, clientName, webUrl, apiUrl, requireSignin, logoUrl, iconUrl}`, `packages/install-config/src/index.ts:5-13`), consumed by the Join dialog / filename tag `OpenWork--<host>--<token>.exe` (`:90-154`, `A/react-app/domains/cloud/join-organization-dialog.tsx:145-165`). Handoff exchange writes `enterpriseActivation` in the same commit (`A/app/lib/den-handoff.ts:226-252`).

---

## 7. Deliverable table

| Manual step today | Den-driven equivalent | Payload / endpoint | Gaps |
|---|---|---|---|
| `enabled_providers:["ackstorm"]` | `allowCustomProviders:false` (+`allowZenModel:false`) | `GET /v1/me/desktop-config` → `enabled_providers` computed from lpr_/ipr_/openwork keys (`openwork-runtime-config.ts:68-71`) | key is `lpr_…`, not `ackstorm`; hides everything else incl. user's own opencode.json providers |
| `OPENCODE_MODELS_URL` catalog (provider `ackstorm`, models with modalities/cost/limit/…) | llmProvider with inline models | `GET /v1/llm-providers` + `/v1/llm-providers/:id/connect` (§1 shape); per-model `config` passthrough keys `:223-239` | **no Den field for a catalog URL**; default engine catalog is `models.openworklabs.com`; env var only via launcher env (env.json rejects `OPENCODE_*`) |
| Per-request JWT via `opencode-auth` plugin | none | — | Den only delivers a static `apiKey` → env.json + `PUT /auth/lpr_…`. Closest: mint a long-ish per-member key Den-side (`memberCredential.state:"active"`, rotate on each 5-min sync — rotation triggers auth re-delivery `:1301-1312`) |
| `plugin:["…/opencode-auth", "./plugins/ach-memory.js"]` | none | only local `POST /workspace/:id/plugins` (`server.ts:3405`) | **cannot push OpenCode plugins**; cloud plugin objectTypes exclude `plugin`. Closest: `tool` objectType (`.opencode/tools/*.ts`) or a Den-hosted skill instructing the user |
| `mcp["ach-memory"]` local stdio + `environment` | cloud plugin MCP component | `/v1/plugins/:id/resolved` configObject `{objectType:"mcp", latestVersion.normalizedPayloadJson:{mcp:{"ach-memory":{command:[…],environment:{…},enabled:true}}}}` (`cloud-plugins.ts:353-407`) | user must click Install per workspace (`extensions-store.ts:1230`), blocked if `allowManageExtensions:false`; name becomes `<plugin>-plugin-ach-memory`; secrets shared unless `{env:}` + env.json |
| `ACH_MEMORY_API_KEY`/`ACH_MEMORY_HEADER` env | only provider-credential env names | llmProvider `providerConfig.env:[…]` + `/connect` `apiKeys:{NAME:value}` (`cloud-provider-sync.ts:603-614`) | hack: values are per-member only if Den returns member-specific `/connect`; engine picks them up after restart |
| `OPENCODE_ENABLE_EXA=true` | none | — | UI toggle is dead (`runtime.mjs:2212`), Den can only deny websearch via `execution.browserOrigins` |
| `skills.paths` | skill:// resources or cloud plugin skills | §5 | cloud plugin skills are workspace files, manual install; MCP skills need the Connect endpoint (prior doc §5) |
| Pointing the app at the org server | `desktop-bootstrap.json` / `/v1/install-config` | §6 | enterprise flavor needs signed connect-link/handoff to set `enterpriseActivation` (trusted origin); public flavor can pre-seed `baseUrl`+`requireSignin` by file |

Key absolute files: `/home/jcm/Projects/openwork/apps/server/src/cloud-provider-sync.ts`, `.../managed-provider-auth.ts`, `.../openwork-runtime-config.ts`, `.../runtime-opencode-config-store.ts`, `.../managed-desktop-policy.ts`, `.../managed-policy-rules.ts`, `.../env-file.ts`, `.../opencode-models-url.ts`, `.../embedded.ts`, `.../managed-opencode.ts`, `.../cloud-plugins.ts`, `.../desktop-cloud-sync.ts`, `.../mcp.ts`, `.../validators.ts`, `.../plugins.ts`, `.../enterprise-den-origin.ts`; `/home/jcm/Projects/openwork/apps/app/src/app/lib/den.ts`, `.../react-app/domains/settings/state/extensions-store.ts`, `.../react-app/domains/settings/state/debug-view-model.ts`; `/home/jcm/Projects/openwork/apps/desktop/electron/runtime.mjs`, `.../workspace-store.mjs`, `.../main.mjs`, `.../desktop-distribution.mjs`; `/home/jcm/Projects/openwork/packages/types/src/den/desktop-policies.ts`, `.../inference.ts`; `/home/jcm/Projects/openwork/packages/install-config/src/index.ts`; `/home/jcm/Projects/openwork/packages/paths/index.mjs`.
