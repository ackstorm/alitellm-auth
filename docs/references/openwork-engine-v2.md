<!-- Research report, 2026-09-19, from the OpenWork source @8c18c952a. The OpenCode v2 (preview)
     sidecar engine and what it changes for a self-hosted Den. Companion to openwork-provisioning.md. -->

# OpenCode v2 (preview) engine — research report

Repo `/home/jcm/Projects/openwork` @ `8c18c952a`. `S` = `apps/server/src`, `A` = `apps/app/src`, `D` = `docs/opencode-v2-parallel-lane.md`. Pinned v2 = `@opencode-ai/cli 0.0.0-beta-19086` (`constants.json:3`), binary `opencode2`. No v2 engine source is vendored; engine-internal claims come from `D` (written against beta-18707) and are marked *(design doc)*.

---

## 1. How v2 is configured

### Spawn (`S/managed-opencode-v2.ts`)
| Item | Value | Cite |
|---|---|---|
| Binary | `OPENWORK_OPENCODE2_BIN` env → `opencode2` on PATH → verified sha512 download from npm registry into `<runtime>/opencode-v2-verified/<ver>/<platform>/opencode2` (not bundled by the desktop) | `S/engine-v2-preview.ts:147-167`, `S/opencode-v2-binary.ts:11-52`, `S/opencode-v2-artifacts.json` |
| Args | `opencode2 serve --hostname 127.0.0.1 --port 0` | `:174` |
| Env | **allowlist only** (PATH/HOME/USER/SHELL/TMP/LANG/TZ/XDG_*/SSL certs) + `OPENCODE_PASSWORD` (random, Basic auth user `opencode`), `OPENCODE_DB=<root>/opencode.db`, `OPENCODE_CONFIG_DIR=<root>/config`, `OPENCODE_MODELS_URL` (if resolved). `OPENCODE_CONFIG` only if the caller passes it explicitly — the preview never does. `process.env` is **not** spread (v1 does: `S/managed-opencode.ts:164-170`) | `:146-183` |
| Root | `<runtime>/opencode-v2/state/` (`config/opencode.json`, `opencode.db`, `workspace/`, `cloud-skills/`) | `S/engine-v2-preview.ts:313-314, 338`; `S/runtime-db.ts:44` |
| cwd | not set; every API call is scoped by `?location[directory]=<workspace.path>` (one daemon, many dirs) | `:218-221`; `S/server.ts:1203-1209` |
| Readiness | stdout `server listening on <url>` then `GET /api/health {healthy,version,pid}`; pid must match child | `:189-192, 241-252, 323-358` |

### Generated config
`renderOpencodeV2Config` writes the **entire** `<root>/config/opencode.json` atomically (tmp+rename) on every change, with exactly four keys: `$schema`, `providers` (v2 dialect), `permissions`, `skills` (`S/managed-opencode-v2.ts:80-131, 254-271`). No `mcp`, no `plugin`, no `instructions`, no `enabled_providers`/`disabled_providers`.

### Does v2 read the user's `~/.config/opencode/opencode.json` / `.opencode/`?
- `OPENCODE_CONFIG_DIR` is overridden to the private dir, and it is the "always-watched global configuration directory" *(design doc `D:116, 229`)* → the user's global `~/.config/opencode/opencode.json` is **not** the global config for the sidecar. `OPENCODE_CONFIG` is deliberately not inherited (`:160-162`). The provider-hot-inject spec confirms the sandboxing: "inherited OPENCODE_*, credentials and DB paths cannot enter this child" (`evals/specs/opencode-v2-provider-hot-inject.test.ts:73-75`).
- Project `.opencode/skills`, `.opencode/skill`, `.claude/skills` **are** scanned natively by the engine (`S/opencode-v2-instructions.ts:14-16`, `:65-110`).
- Whether v2 also loads a project-level `opencode.json`/`.opencode/opencode.json` (mcp/plugin/provider) from the location dir is **not verified in-repo**; the chat-routing eval writes a v1-dialect `provider` block into the workspace `opencode.json` and only expects it to serve the v1 lane (`evals/specs/opencode-v2-chat-routing.e2e.test.ts:509-517, 557-559`); the v2 provider is delivered via `PATCH /workspace/:id/config` → runtime store → mirror (`:581-604`). Assume **no** for planning.

### "Live provider updates, no engine reloads" — mechanics
There is no push API for providers. OpenWork rewrites the watched config file; v2's file watcher rebuilds its catalog in ~100-600 ms *(design doc `D:194-199`)*. Trigger chain:
1. any write to the ENGINE_GLOBAL runtime row → `onRuntimeOpencodeConfigWrite` → `scheduleMirror()` (`S/engine-v2-preview.ts:546-548`); env.json change → same (`:563`, `S/env-file.ts:164`).
2. `mirrorProviders()` reads the global row + env.json, maps, `setProviders()` → file write (`:451-481`), then polls `GET /api/model?location[directory]=<root>/workspace` up to 60 s until all mirrored model ids appear (`:43, 464-480`).
3. Per workspace, `ensureWorkspaceReady` polls `GET /api/provider` until every mirrored provider is present *with the same apiKey* (`:635-661`).

Runtime APIs actually used on the sidecar: `GET /api/health`, `GET /api/model`, `GET /api/model/default`, `GET /api/provider`, `PUT|DELETE /api/mcp/:name`, `GET /api/mcp`, `GET /api/skill`, `PUT /api/session/:id/instructions/entries/openwork.context`, `POST /api/session` (+ v2 session/permission routes from the app adapter). No `/api/config`, `/api/auth`, `/api/integration/*` calls. The proxy 403s renderer access to `/api/config*`, writes to `/api/mcp*`, and writes to the managed instruction entry (`S/server.ts:1191-1197, 1250-1253`).

Preview state: `OPENWORK_ENGINE_V2_PREVIEW=1|chat` (enabled+routing), `=sidecar` (mirror only), else persisted `<runtime>/engine-v2-preview.json {enabled, chatRouting}` (`S/engine-v2-preview.ts:87-95, 114-136`). Routes `GET /experimental/engine-v2-preview/status`, `PUT /experimental/engine-v2-preview` (policy action `settings`) (`S/server.ts:3095-3115`; `S/managed-policy-rules.ts:134`).

---

## 2. Providers / models in v2

**Source**: same ENGINE_GLOBAL runtime row (`readGlobalRuntimeOpencodeConfig` → `runtimeProviderMap`, `:454`). `cloud-provider-sync.ts` has no v2 branch — Den llmProviders reach v2 because they land in that row. Workspace-row providers are not mirrored (migrated to global anyway, `S/runtime-opencode-config-store.ts:295-330`).

**Mapping `mapRuntimeProvidersToV2Specs` (`S/engine-v2-preview.ts:169-253`)** — a provider is **skipped** when:
| Condition | Line |
|---|---|
| `npm` not in {`@ai-sdk/openai`, `@ai-sdk/anthropic`, `@openrouter/ai-sdk-provider`, `@ai-sdk/openai-compatible`} (e.g. google, bedrock, azure, vertex) | `:181-188, 210-215` |
| no `options.baseURL` and `api` origin isn't the native adapter's trusted origin (so `api` alone never works for openai-compatible) | `:190-209` |
| `@ai-sdk/openai-compatible` (or no npm) without `options.baseURL` | `:211-215` |
| `env:[...]` declared but no key resolvable | `:225-228` |

**API key delivery** (`:216-224`): `options.apiKey` literal wins **unless it contains `{env:`**; else `env.json` value for `selectPrimaryCredentialEnvName(env[], env.json keys)` (`S/managed-provider-auth.ts:224-237`); else provider skipped (or sentinel `openwork-engine-v2-preview-unset` when `env:[]`, `:39, 245`). Key is written literally into `settings.apiKey` in the generated file (0600) (`S/managed-opencode-v2.ts:115-120`). **No `PUT /auth/:provider`** for v2; `managed-provider-auth.ts` is v1-only; the app adapter has no `auth.set` (grep → none).

**Why `{env:` is filtered** (`:221-223` comment): the sidecar doesn't inherit the server env, so `{env:X}` could never be substituted inside it; and the mirror refuses to resolve arbitrary env names — only the provider's own declared `env[]` names, from env.json, "never inherit the server environment or copy unrelated secrets into the sidecar" (test `S/engine-v2-preview.test.ts:211-222`). Net: `options.apiKey:"{env:ACKSTORM_API_KEY}"` → treated as no explicit key → falls back to env.json lookup by `env[]` name → works only if `env:["ACKSTORM_API_KEY"]` is declared and env.json has it.

**Hot rotation**: env.json change or Den `/connect` re-sync re-mirrors without restart (`:563`) — v1 needs `/auth` re-delivery + reload.

**`OPENCODE_MODELS_URL`**: yes — `resolveOpencodeModelsUrl()` (env override → `models.openworklabs.com`) is passed at spawn (`S/engine-v2-preview.ts:529-533`; `S/managed-opencode-v2.ts:146, 180`; `S/opencode-models-url.ts:11-17`). Boot-fixed *(design doc `D:238-241`)*. Still only settable via launcher env.

**Per-model metadata** (`S/managed-opencode-v2.ts:88-111`) vs v1 passthrough (`cloud-provider-sync.ts:223-239`):
| v1 key | v2 |
|---|---|
| `name` | `name` |
| `id` | `modelID` |
| `tool_call` | `capabilities.tools` (default true) |
| `modalities.input/output`, `reasoning` | `capabilities.input/output` (+`"reasoning"` appended) |
| `limit` | `limit` (default `{context:128000, output:8192}`) |
| `family`, `options`→`settings`, `headers`, `variants`→`nativeModelVariants` (`packages/types/src/cloud-model-fast.ts:45-69`), `status:"deprecated"`→`disabled` | kept |
| `cost`, `attachment`, `temperature`, `interleaved`, `release_date`, `provider`; provider `whitelist`/`blacklist`, `disabled_providers`, `enabled_providers` | **dropped** |

Provider `options` minus `apiKey/baseURL/headers` → `settings`; `headers` → provider `headers` (`:216, 243-244`).

---

## 3. MCP in v2

- Delivered via **runtime API**, not config: `syncWorkspaceMcp(workspaceId, dir)` reads the effective (global ⊕ workspace) runtime `mcp` map, maps with `mapRuntimeMcpToV2`, `DELETE` stale then `PUT /api/mcp/:name?location[directory]=…` `{config}`, waits for `GET /api/mcp` status ≠ `pending` (30 s) + 250 ms ToolsChanged settle (`S/engine-v2-preview.ts:361-433`). Runs before every non-read proxied request (`S/server.ts:922-927`) and on any runtime-row write for open locations (`:554-561`).
- `mapRuntimeMcpToV2` (`:286-309`): local `{type:"local", command[], environment (string map), cwd?}`; remote `{type:"remote", url http(s), headers, oauth:false|{client_id,client_secret,scope}}`; `enabled:false` → removed; `timeout` → `{startup,catalog,execution}`; `codemode`. Local stdio `environment` values pass verbatim; no `{env:}` substitution possible from OpenWork's env (sidecar env is allowlisted).
- `openwork-cloud`: global runtime row entry `{type:"remote", url, headers:{Authorization:Bearer}, oauth:false}` (unchanged from `cloud-mcp-reconciler.ts:194-203`) → same PUT path. Also read directly for skills (`:341`). Connect-readiness for the prompt = `GET /api/mcp` shows `openwork-cloud` `status.status==="connected"` (`S/server.ts:1259-1263`).
- Cloud-plugin MCP components (workspace row, `S/cloud-plugins.ts:559-575`) reach v2 through the effective merge (`S/runtime-opencode-config-store.ts:281-293`). Unlike v1's file render, v2 does **not** filter `openwork-connect-*` entries (`S/openwork-runtime-config.ts:112` vs none in `syncWorkspaceMcp`).
- User `opencode.json` `mcp` block: not delivered by OpenWork; engine-side project config loading unverified (§1).
- `dynamicMcp:yes` in Diagnostics is a hardcoded `true` in the **v1** Cloud-MCP health snapshot (`S/cloud-mcp-health.ts:2168`) — v1 already pushes MCP dynamically with `POST /mcp` (`S/server.ts:5037-5054`). Not a v2 probe. In v2 the app's `mcp.status` stub returns `{}` (`A/app/lib/opencode-v2-adapter.ts:2151-2153`), so the MCP settings view is blind on v2.

---

## 4. Skills in v2

Confirmed: on every `POST /api/session/:id/(prompt|command|generate)` the proxy (1) `syncCloudSkills()` = fresh `skill://index.json` + all `SKILL.md` via the `openwork-cloud` MCP (lenient index schema, ≤200 skills, ≤256 KiB each), materialized to `<root>/cloud-skills/<scope-hash>/openwork-cloud-<sha16>/SKILL.md` with atomic renames, registered via `setSkills([dir])` → config `skills:[dir]` (`S/cloud-native-skills.ts:82-146, 174-215`; `S/engine-v2-preview.ts:338-359`; `S/server.ts:1264-1280`); failures fail closed (skills cleared, prompt admitted) (`S/cloud-native-skills.ts:274-284`). (2) `waitForOpenWorkV2Skills` polls `GET /api/skill` until workspace `.opencode/skills|skill`, `.claude/skills` bodies and cloud bodies match (5 s) (`S/opencode-v2-instructions.ts:65-110`; `S/server.ts:1281-1286`). (3) `PUT .../instructions/entries/openwork.context` with `{operatingInstructions, connect, skillInstructions}` (≤7 KiB) replacing the v1 "remote skills via Connect" text with "native skill catalog, ids `openwork-cloud-*`, do not fetch skills through Connect" (`S/opencode-v2-instructions.ts:113-124`; `S/server.ts:1287-1293`).

Cloud-plugin skills (`.opencode/skills/<ns>/<name>/SKILL.md`) work: scan is `{*.md,**/SKILL.md}` under the managed roots (`:18-40`). Non-owner tokens see only `id/name/description/slash` for cloud skills (`S/server.ts:1310-1325`). Lost vs v1: `<available_automations>` and routing-steering text (no plugin in v2).

---

## 5. Plugins in v2

- `renderOpencodeV2Config` emits **no `plugin` key**; `grep plugin` in the three v2 server files → only a comment. OpenWork injects **none** of its v1 plugins (chrome-devtools, capabilities-knowledge, extensions-preview, office/spreadsheet/pdf, anthropic adaptive-thinking/tool-schema, title-recovery; `S/openwork-runtime-config.ts:94-107`) into v2. Their roles are partly replaced by the native instruction entry (§4) and native skills; app-control tools (`openwork_docs_search`, `openwork_query`, extensions tools) do not exist on v2.
- Runtime-row `plugin:[...]` (local `POST /workspace/:id/plugins`) is ignored by the mirror (only `runtimeProviderMap`/`runtimeMcpMap` are read).
- v2 has a plugin system (`PluginSupervisor`, *design doc `D:197-199, 400`*: "Plugin and tool ecosystems differ"), but nothing in OpenWork registers plugins and the private `OPENCODE_CONFIG_DIR` excludes the user's global config. **A URL plugin like `https://platform.ackstorm.ai/public/opencode-auth` will not run under v2** through any OpenWork-managed path (project-level config is the only unverified hope, §1). Even if loaded, it would be a v2-API plugin (different hook contract from v1's `auth`/fetch hooks).
- `OPENCODE_PURE` is explicitly not inherited (`S/managed-opencode-v2.ts:160-161`).

---

## 6. Env in v2

| Question | Answer | Cite |
|---|---|---|
| Inherits `process.env`? | No — allowlist of OS/locale/XDG/cert vars only | `S/managed-opencode-v2.ts:147-159` |
| env.json injected? | Not as env. env.json is read by the mirror solely to resolve provider `env[]` names into `settings.apiKey`; env.json changes trigger re-mirror | `S/engine-v2-preview.ts:455, 563` |
| `OPENCODE_ENABLE_EXA` | never set (also not in v1) | grep → none |
| `OPENCODE_MODELS_URL` | passed from `resolveOpencodeModelsUrl` | `:529-533` |
| `OPENCODE_CONFIG`/`OPENCODE_CONFIG_CONTENT` | never passed by the preview; `OPENCODE_CONFIG_DIR` private | `:160-162, 179` |
| `{env:X}` | in provider `apiKey` → ignored (§2); in MCP `environment` → passed verbatim, cannot resolve from OpenWork env | `:223, 298` |
| Sidecar HOME/XDG | real user HOME (so `~/.cache`, `~/.local/share/opencode` etc. are shared with v1), but DB and config dir are private | `:150-153, 178-179` |

---

## 7. Maturity / gaps

Gated behind the flag: sidecar start (`enabled`), and `chatRouting` which flips the workspace's `opencodeBaseUrl` to `/workspace/:id/opencode2` (`A/react-app/shell/route-workspaces.ts:56-68`, `use-workspace-route-state.ts:274, 1308`); local workspaces only (`:437`). Sessions live in the v2 SQLite DB; the app lists whichever engine is routed — hence "sessions stay in that engine's list" (`evals/specs/opencode-v2-chat-routing.e2e.test.ts:617-641`). No migration wired (v1 importer only mentioned, *`D:364-367`*).

Enforced on v2: managed desktop policy `assertRequest(..., engine=true)` strips `/opencode2` and checks sync/shell/terminal/saved_command/engine_config/extensions/provider/model actions (`S/managed-desktop-policy.ts:175-213`; mounted at `S/server.ts:916`); execution rules (`commands:deny`, `blockedCommands`, `browserOrigins` → webfetch/websearch deny) rendered as v2 `permissions` and refreshed on every config write (`S/managed-policy-rules.ts:27-38`; `S/engine-v2-preview.ts:534`; `S/managed-opencode-v2.ts:128, 262-269`). Permissions and questions (`form.*`) are bridged (`A/app/lib/opencode-v2-adapter.ts:1316-1338, 1639-1660`). App-host sessions tag `engine:"v2"` (`S/server.ts:3679-3720`).

Not working / stubbed on v2:
| Gap | Cite |
|---|---|
| session archive, fork, revert, unrevert, summarize, shell, command → 501 `UnsupportedInV2Preview` | `A/app/lib/opencode-v2-adapter.ts:85, 1580-1585, 2015-2016, 2041-2046` |
| `config.get` `{}`, `app.agents` `[]`, `command.list` `[]`, `find.files` `[]`, `mcp.status` `{}`, `todo` `[]` (agents/commands/MCP UI blind) | `:1901, 2059-2061, 2117-2124, 2148-2153` |
| Workspace run modes (approve / run-everything) unsupported | `S/server.ts:2785-2786, 2844` |
| Skill attachment ambiguous → nothing sent | `:1945-1962` |
| No OpenWork plugins → no app-control tools, no Automations catalog, no Connect steering text beyond one line | §5 |
| Provider adapters limited to 4 npm packages; `cost`/`whitelist`/`blacklist`/`disabled_providers` dropped | §2 |
| Beta pin, `/api/experimental/*` may move, models.dev network need, Basic-auth lifecycle | *`D:388-404`* |
| Binary downloaded at runtime from npmjs (needs egress) | `S/opencode-v2-binary.ts:31` |

---

## 8. Deliverable: v1 → v2 → what changes for a self-hosted Den

| Aspect | v1 | v2 (preview) | Self-hosted Den impact |
|---|---|---|---|
| Engine process | `opencode serve`, `process.env` + env.json, `OPENCODE_CONFIG=<runtime>/runtime-opencode-config.json`; reload on change | `opencode2 serve`, allowlisted env, private `OPENCODE_CONFIG_DIR` + `OPENCODE_DB`; watched-file hot update | Nothing to push from Den; same runtime DB row is the source |
| User `~/.config/opencode/opencode.json` | loaded by OpenCode alongside the runtime file | **not loaded** (config dir overridden) | Users' hand-written `provider`/`plugin`/`mcp` blocks stop applying on v2 |
| Den llmProviders | global row → file → `PUT /auth/lpr_…` → reload | global row → `mapRuntimeProvidersToV2Specs` → file; key from `options.apiKey` or env.json via `env[]`; no reload | Works if `providerConfig.npm` ∈ 4 adapters **and** `options.baseURL` is set; `api` alone is skipped. Key still static (env.json/file) |
| API key rotation | `/connect` re-sync → `/auth` + deferred reload | `/connect` re-sync → env.json → re-mirror (≈1 s) | Shorter-lived per-member keys become practical (no reload) — still not per-request |
| Catalog URL | `OPENCODE_MODELS_URL` env only | same; boot-fixed | unchanged: launcher env only |
| Per-model metadata | full passthrough | subset (loses `cost`, `attachment`, `temperature`) | Cost display/limits behavior differs |
| Per-request auth (`opencode-auth` URL plugin) | works via user `plugin:[...]` in global opencode.json | **does not run** (no plugin injection, global config not read) | **Broken on v2**; only static apiKey path exists |
| OpenCode plugins via Den | impossible | impossible (no `plugin` key rendered, runtime-row plugins ignored) | unchanged: no |
| Env vars via Den | only provider `env[]` names → env.json | same, and env.json is not even in the sidecar env (only provider key resolution) | `ACH_MEMORY_API_KEY`-style hacks reach neither the engine env nor MCP `environment` on v2 |
| MCP | file + `POST /mcp` dynamic; user opencode.json `mcp` honored | `PUT/DELETE /api/mcp/:name` per location, from runtime rows only | Cloud-plugin stdio MCP (`command`+`environment`, secrets shared) still works; per-member secrets: only literal `environment` |
| `openwork-cloud` MCP | reconcile → global row → engine | same row → `PUT /api/mcp/openwork-cloud` | No Den change; `initialize.instructions` still injected by engine |
| Skills | `skill://` prompt catalog + Connect hop; cloud-plugin `.opencode/skills` files | native: materialized `SKILL.md` per prompt + `.opencode/skills` scan | Den `skill://index.json` lenient (`name,type:"skill-md",url`); bodies fetched every prompt (load on Den) |
| Policies | proxy `assertRequest` + config `permission` | proxy `assertRequest(engine)` + config `permissions` | equivalent; `allowCustomProviders` still gates model selection at proxy |
| Features | full | no archive/fork/revert/run-modes/app-control tools/agents+commands UI | user-facing regressions |

**Bottom line for us**: v2 does not unlock any of the previously-impossible items (plugins, env vars, catalog URL, per-request auth). It removes the reload cost for provider/key changes and makes skills native, but it breaks the two things we rely on today (`~/.config/opencode/opencode.json` providers/plugins and the `opencode-auth` URL plugin) and narrows provider support to `@ai-sdk/openai-compatible`-with-`options.baseURL` + static key.
