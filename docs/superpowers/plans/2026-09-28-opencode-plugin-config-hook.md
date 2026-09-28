# OpenCode auth plugin: backend bootstrap + config hook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Size note (CLAUDE.md "measure first")**: ~180 lines of JS in one file plus tests,
> one subsystem. Execute INLINE, one review at the end.
>
> **Depends on**: `docs/superpowers/plans/2026-09-28-opencode-config-endpoint.md`
> (server: `/clients/opencode/config`, tgz with `package/platform.json`). The plugin
> tests use a fake backend, so both plans can run in parallel; the end-to-end check
> (spec T6) needs both.

**Goal:** The product-neutral `ackstorm` plugin finds its backend from `platform.json` (or plugin options), and at every OpenCode start fetches `/clients/opencode/config` with the user's OAuth token and merges it UNDER the user's config (models, MCP servers, skills).

**Architecture:** One file, `clients/opencode/index.mjs`. `backend()` reads `platform.json` next to the module, overridden by plugin options. `discover()` takes its API URL from there (legacy fallback: the provider in config). Token refresh becomes one module-level function shared by `loader.fetch` and the new `config` hook. The hook reads OpenCode's `auth.json`, refreshes if needed, fetches the config (2 s), caches it (30 d, same user), fills missing keys into `cfg`, writes skills to a data dir and adds it to `cfg.skills.paths`. It never throws.

**Tech Stack:** Node ESM (runs inside OpenCode/Bun), `node:test`, no dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-27-opencode-client-config-and-den.md` — **Rev 4 wins**; §4.3 for the hook; §4.7 T-P1..T-P5.
- Product-neutral: no product URL or name hardcoded; everything from `platform.json` / options. Provider id stays `ackstorm`.
- `platform.json` = `{"api": "<gateway>/v1", "platform": "<origin serving /clients/*>"}`. Options (`["<url>", {"api": …, "platform": …}]` in `opencode.json`) override field by field.
- Config URL = `${platform}/clients/opencode/config`; schema `ackstorm.opencode-config/1`; timeout 2000 ms.
- Merge: only `provider`, `mcp`, `instructions` read from the server; user keys always win; `instructions` append-missing.
- Cache `$XDG_DATA_HOME/opencode/ackstorm-config.json` (0600) `{user, fetchedAt, body}`; used only when `user` == the token's `sub` and < 30 d old. Skills in `$XDG_DATA_HOME/opencode/ackstorm-skills/<name>/SKILL.md` (dirs 0700, files 0600).
- The hook never throws and never writes `auth.json` (OpenCode owns it; tokens go through `client.auth.set`).
- Verified in opencode 1.18.31 (v1 loader), do not re-litigate: the `config` hook is awaited and errors are ignored; `skills.paths` takes absolute/`~/` paths and scans `**/SKILL.md`; `instructions` accepts only paths/globs/URLs (**no inline notice** — spec §4.3.4 notice is dropped); the plugin `client` works in-process when no server is listening; `opencode auth login -p ackstorm` finds the plugin via `auth.provider` without any provider in config; a config provider with zero models is pruned (so **no "minimal provider"** is injected — `platform.json.api` alone makes the first sign-in work).
- Commits only after user approval, via `git:commit-push` subagent.

## File Structure

| File | Change |
|---|---|
| `clients/opencode/index.mjs` | header, `backend()`, `discover()`, shared `fresh()`, `config` hook, `fillMissing` (exported), skills |
| `clients/opencode/package.json` | version `0.3.0`; `files` += `platform.json`, `README.md` |
| `clients/opencode/README.md` | new: install, `platform.json` contract, options, files it writes |
| `test/opencode-auth.test.mjs` | pass backend via options instead of a fake `config.providers` |
| `test/opencode-config-hook.test.mjs` | new: T-P1..T-P5 |
| `Makefile` | `test-plugin` (or the existing target at line ~95) runs both files |
| `CHANGELOG.md` | entry |

---

### Task 1: Backend bootstrap + shared refresh

**Files:** Modify `clients/opencode/index.mjs`, `test/opencode-auth.test.mjs`

**Interfaces:**
- Produces (module-internal, used by Task 2):
  - `backend(options) -> Promise<{api?: string, platform?: string}>`
  - `discover(client, options) -> Promise<{issuer, as, scope}>`
  - `fresh(cur, {client, options, getAuth}) -> Promise<{type:"oauth", access, refresh, expires}>` — returns `cur` if valid ≥ 60 s, else ONE in-flight refresh per process; errors carry `.status` (HTTP) when the AS answered.
- `SsoAuth(input, options = {})` — OpenCode passes the tuple options as 2nd arg.

- [ ] **Step 1: Update the existing test to the new bootstrap** (`test/opencode-auth.test.mjs`)

In `fakeClient()`, delete the `config: { providers: … }` line. Every `SsoAuth({ client })` call becomes:

```js
SsoAuth({ client }, { api: "https://api.test/v1", platform: "https://api.test" })
```

(and the same for `Fresh`). Add one test at the end:

```js
test("the legacy install (no platform.json, no options) still discovers from the configured provider", async () => {
  const { SsoAuth: Legacy } = await import("../clients/opencode/index.mjs?legacy")
  const { client } = fakeClient()
  client.config = { providers: async () => ({ data: { providers: [{ id: "ackstorm", options: { baseURL: "https://api.test/v1" } }] } }) }
  const hooks = await Legacy({ client })
  const { url } = await hooks.auth.methods[1].authorize()
  assert.match(url, /^https:\/\/as\.test\/device/)
})
```

- [ ] **Step 2: Run, expect FAIL** — `node --test test/opencode-auth.test.mjs` → the existing tests fail (`client.config` undefined).

- [ ] **Step 3: Implement** in `clients/opencode/index.mjs`

Replace the header comment (lines 1–22) with:

```js
// opencode plugin: SSO (OAuth) sign-in to an ACKstorm backend's model gateway,
// and that backend's per-user OpenCode config at every start.
//
//   opencode plugin https://<origin>/clients/opencode/plugin -g
//   opencode auth login -p ackstorm
//
// Product-neutral: the backend that served the tarball wrote platform.json next
// to this file ({"api": "<gateway>/v1", "platform": "<origin serving /clients/*>"});
// plugin options in opencode.json override it. See README.md.
//
// Sign-in: `api` -> RFC 9728 protected-resource document -> RFC 8414 AS metadata;
// browser (loopback + PKCE) or RFC 8628 device grant. opencode stores the tokens
// (auth.json) but never refreshes them: `fresh()` does, for every model request
// and for the config fetch.
//
// Config: the `config` hook fetches <platform>/clients/opencode/config
// (ackstorm.opencode-config/1) and fills in what the user's own config lacks.
// The user's config always wins. PROVIDER is that config's provider id.
```

Change the fs import to:

```js
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises"
```

Make `json()` errors carry the status:

```js
async function json(url, init) {
  const r = await fetch(url, { signal: AbortSignal.timeout(15_000), ...init })
  if (!r.ok) throw Object.assign(new Error(`${r.status} ${url}`), { status: r.status })
  return r.json()
}
```

Replace `discover` with:

```js
// Where this plugin's backend is. platform.json is written into the tarball by
// the backend that served it; options come from ["<url>", {...}] in opencode.json.
let platformFile
async function backend(options) {
  platformFile ??= readFile(new URL("./platform.json", import.meta.url), "utf8")
    .then(JSON.parse)
    .catch(() => ({}))
  return { ...(await platformFile), ...options }
}

async function apiUrl(client, options) {
  const { api } = await backend(options)
  if (api) return api
  // ponytail: installs from before platform.json read the provider from config
  // (the served api.json). Drop once every user has reinstalled.
  const { data } = await client.config.providers()
  const provider = data?.providers?.find((p) => p.id === PROVIDER)
  return Object.values(provider?.models ?? {})[0]?.api?.url ?? provider?.options?.baseURL
}

// API URL -> protected-resource document (RFC 9728) -> authorization-server
// metadata (RFC 8414). Once per process.
let discovered
function discover(client, options) {
  return (discovered ??= (async () => {
    const api = await apiUrl(client, options)
    if (!api) throw new Error(`no backend for ${PROVIDER}: reinstall the plugin from <origin>/clients/opencode/plugin`)
    const u = new URL(api)
    const prm = await json(`${u.origin}/.well-known/oauth-protected-resource${u.pathname.replace(/\/$/, "")}`)
    const issuer = prm.authorization_servers[0]
    const as = await json(`${issuer}/.well-known/oauth-authorization-server`)
    if (as.issuer !== issuer) throw new Error(`issuer mismatch: ${as.issuer} != ${issuer}`) // RFC 8414 §3.3
    return { issuer, as, scope: (prm.scopes_supported ?? []).join(" ") }
  })().catch((e) => { discovered = undefined; throw e })) // a blip must not poison the process
}
```

Add after `token()` the shared refresh (module-level, so the hook and `loader.fetch` share one in-flight refresh):

```js
// One in-flight refresh per process, shared by loader.fetch and the config hook.
// ponytail: a lost race across processes spends a rotated refresh token.
let refreshing
// Tokens from a refresh whose client.auth.set failed; preferred until saved.
let unsaved
async function fresh(cur, { client, options, getAuth }) {
  if (unsaved && unsaved.expires > (cur?.expires ?? 0)) cur = unsaved
  if (cur.expires >= Date.now() + 60_000) return cur
  refreshing ??= (async () => {
    // Re-read: a caller that read stale auth just after the previous refresh
    // cleared would otherwise spend an already-rotated token.
    const again = (await getAuth()) ?? cur
    if (again?.type === "oauth" && again.expires >= Date.now() + 60_000) return again
    const d = await discover(client, options)
    const client_id = await savedClientId(d.issuer)
    if (!client_id) throw new Error(`SSO client identity lost, run \`opencode auth login -p ${PROVIDER}\``)
    const t = { type: "oauth", ...(await token(d, { grant_type: "refresh_token", refresh_token: again.refresh, client_id })) }
    t.refresh ||= again.refresh
    try {
      await client.auth.set({ path: { id: PROVIDER }, body: t })
      unsaved = undefined
    } catch {
      unsaved = t // opencode's store unreachable: never lose a rotated refresh token
    }
    return t
  })().finally(() => { refreshing = undefined })
  return refreshing
}
```

In `SsoAuth`: signature `export async function SsoAuth({ client }, options = {})`; delete its local `let refreshing`; `discover(client)` → `discover(client, options)` in both `authorize()` methods; replace the body of `loader.fetch` with:

```js
          async fetch(input, init) {
            let auth = await getAuth()
            if (auth?.type !== "oauth") return fetch(input, init)
            auth = await fresh(auth, { client, options, getAuth })
            const req = new Request(input, init) // normalises url/Request + any headers shape
            req.headers.set("authorization", `Bearer ${auth.access}`)
            return fetch(req)
          },
```

- [ ] **Step 4: Run, expect PASS** — `node --test test/opencode-auth.test.mjs`.

---

### Task 2: `config` hook, merge, cache, skills

**Files:** Modify `clients/opencode/index.mjs`; Create `test/opencode-config-hook.test.mjs`

**Interfaces:**
- Consumes: `backend`, `fresh` (Task 1).
- Produces: `export function fillMissing(target, source) -> target`; hook `config(cfg)` on the object `SsoAuth` returns.

- [ ] **Step 1: Failing tests** — `test/opencode-config-hook.test.mjs`

```js
// node --test test/opencode-config-hook.test.mjs
// Spec 2026-09-27-opencode-client-config-and-den.md §4.3, T-P1..T-P5.
import { test, beforeEach } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync, statSync } from "node:fs"
import { tmpdir } from "node:os"

process.env.XDG_DATA_HOME = mkdtempSync(`${tmpdir()}/opencode-hook-`)
const DATA = `${process.env.XDG_DATA_HOME}/opencode`
const CACHE = `${DATA}/ackstorm-config.json`
const SKILLS = `${DATA}/ackstorm-skills`
const { SsoAuth, fillMissing } = await import("../clients/opencode/index.mjs")

const ISSUER = "https://as.test"
const OPTIONS = { api: "https://api.test/v1", platform: "https://api.test" }
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url")
const jwt = (sub) => `h.${b64({ sub })}.s`

let server // (url, init) => Response | throws; per test
let configCalls, tokenCalls
globalThis.fetch = async (input, init) => {
  const url = typeof input === "string" ? input : input.url
  if (url.startsWith("https://api.test/.well-known/oauth-protected-resource")) {
    return Response.json({ authorization_servers: [ISSUER], scopes_supported: ["alitellm"] })
  }
  if (url === `${ISSUER}/.well-known/oauth-authorization-server`) {
    return Response.json({ issuer: ISSUER, token_endpoint: `${ISSUER}/token`, registration_endpoint: `${ISSUER}/register`, authorization_endpoint: `${ISSUER}/authorize` })
  }
  if (url === `${ISSUER}/token`) {
    tokenCalls += 1
    return server.token ? server.token(init) : Response.json({ access_token: jwt("alice@example.com"), refresh_token: "r2", expires_in: 3600 })
  }
  if (url === "https://api.test/clients/opencode/config") {
    configCalls += 1
    assert.equal(init.headers.authorization.split(".")[0], "Bearer h")
    return server.config(init)
  }
  throw new Error(`unexpected ${url}`)
}

const BODY = (over = {}) => ({
  schema: "ackstorm.opencode-config/1",
  version: "sha256:1",
  user: "alice@example.com",
  environment: null,
  auth: "ok",
  stale: false,
  config: {
    provider: { ackstorm: { name: "ACKstorm", npm: "@ai-sdk/openai-compatible", options: { baseURL: "https://api.test/v1" },
      models: { "ackstorm.smart": { name: "ackstorm.smart", limit: { context: 1, output: 1 } } } } },
    mcp: { "mcp-x": { type: "remote", url: "https://api.test/mcp/mcp-x", enabled: false } },
    plugin: ["https://evil.test/p"],
    permission: { bash: "allow" },
  },
  skills: [{ name: "mcp-setup", version: "sha256:a", files: { "SKILL.md": "---\nname: mcp-setup\n---\nv1" } }],
  ...over,
})

function signIn(sub = "alice@example.com", expires = Date.now() + 3_600_000) {
  mkdirSync(DATA, { recursive: true })
  writeFileSync(`${DATA}/auth.json`, JSON.stringify({ ackstorm: { type: "oauth", access: jwt(sub), refresh: "r1", expires } }))
  writeFileSync(`${DATA}/ackstorm-client.json`, JSON.stringify({ issuer: ISSUER, client_id: "c1" }))
}

let saved
async function hook() {
  saved = []
  const client = { auth: { set: async ({ body }) => { saved.push(body) } } }
  return (await SsoAuth({ client }, OPTIONS)).config
}

beforeEach(() => {
  rmSync(DATA, { recursive: true, force: true })
  configCalls = 0
  tokenCalls = 0
  server = { config: () => Response.json(BODY()) }
})

// T-P1
test("fillMissing: user wins, recursion, arrays kept, instructions appended, allow-list", () => {
  const target = {
    provider: { ackstorm: { models: { "ackstorm.smart": { limit: { context: 5 } } } } },
    mcp: { "mcp-x": { enabled: true } },
    instructions: ["a.md"],
    plugin: ["mine"],
  }
  fillMissing(target, {
    provider: { ackstorm: { npm: "n", models: { "ackstorm.smart": { name: "S", limit: { context: 1, output: 2 } }, other: { name: "O" } } } },
    mcp: { "mcp-x": { type: "remote", url: "u", enabled: false }, "mcp-y": { enabled: false } },
    instructions: ["a.md", "b.md"],
    plugin: ["evil"],
    permission: { bash: "allow" },
  })
  assert.deepEqual(target, {
    provider: { ackstorm: { npm: "n", models: { "ackstorm.smart": { name: "S", limit: { context: 5, output: 2 } }, other: { name: "O" } } } },
    mcp: { "mcp-x": { type: "remote", url: "u", enabled: true }, "mcp-y": { enabled: false } },
    instructions: ["a.md", "b.md"],
    plugin: ["mine"],
  })
})

// T-P2
test("success merges under the user's config, writes the cache and the skill", async () => {
  signIn()
  const cfg = { mcp: { "mcp-x": { enabled: true } }, skills: { paths: ["/mine"] } }
  await (await hook())(cfg)
  assert.deepEqual(Object.keys(cfg.provider.ackstorm.models), ["ackstorm.smart"])
  assert.equal(cfg.mcp["mcp-x"].enabled, true)
  assert.equal(cfg.plugin, undefined)
  assert.equal(cfg.permission, undefined)
  assert.deepEqual(cfg.skills.paths, ["/mine", SKILLS])
  assert.equal(readFileSync(`${SKILLS}/mcp-setup/SKILL.md`, "utf8"), "---\nname: mcp-setup\n---\nv1")
  assert.equal(statSync(CACHE).mode & 0o777, 0o600)
  assert.equal(JSON.parse(readFileSync(CACHE, "utf8")).user, "alice@example.com")
})

test("backend down: the same user's recent cache is used", async () => {
  signIn()
  await (await hook())({})
  server.config = () => { throw new Error("timeout") }
  const cfg = {}
  await (await hook())(cfg)
  assert.ok(cfg.provider.ackstorm)
})

test("backend down: another user's cache is ignored", async () => {
  signIn("bob@example.com")
  writeFileSync(CACHE, JSON.stringify({ user: "alice@example.com", fetchedAt: Date.now(), body: BODY() }))
  server.config = () => { throw new Error("timeout") }
  const cfg = {}
  await (await hook())(cfg)
  assert.deepEqual(cfg, {})
})

test("backend down: a cache older than 30 days is ignored", async () => {
  signIn()
  writeFileSync(CACHE, JSON.stringify({ user: "alice@example.com", fetchedAt: Date.now() - 31 * 86_400_000, body: BODY() }))
  server.config = () => new Response("bad gateway", { status: 502 })
  const cfg = {}
  await (await hook())(cfg)
  assert.deepEqual(cfg, {})
})

test("auth invalid: the cache is deleted and nothing is delivered", async () => {
  signIn()
  writeFileSync(CACHE, JSON.stringify({ user: "alice@example.com", fetchedAt: Date.now(), body: BODY() }))
  server.config = () => Response.json(BODY({ auth: "invalid", user: null, config: {}, skills: [] }))
  const cfg = {}
  await (await hook())(cfg)
  assert.deepEqual(cfg, {})
  assert.equal(existsSync(CACHE), false)
})

test("an unknown schema is treated as backend down", async () => {
  signIn()
  server.config = () => Response.json(BODY({ schema: "other/9" }))
  const cfg = {}
  await (await hook())(cfg)
  assert.deepEqual(cfg, {})
})

// T-P3
test("no stored credential: no fetch, no cache", async () => {
  mkdirSync(DATA, { recursive: true })
  writeFileSync(CACHE, JSON.stringify({ user: "alice@example.com", fetchedAt: Date.now(), body: BODY() }))
  const cfg = {}
  await (await hook())(cfg)
  assert.deepEqual(cfg, {})
  assert.equal(configCalls, 0)
})

// T-P4
test("an expiring token is refreshed once and saved through opencode", async () => {
  signIn("alice@example.com", Date.now() + 1_000)
  const config = await hook()
  await Promise.all([config({}), config({})])
  assert.equal(tokenCalls, 1)
  assert.equal(saved.length, 1)
  assert.equal(saved[0].refresh, "r2")
})

test("a rejected refresh means signed out: cache cleared, no fetch", async () => {
  signIn("alice@example.com", 0)
  writeFileSync(CACHE, JSON.stringify({ user: "alice@example.com", fetchedAt: Date.now(), body: BODY() }))
  server.token = () => Response.json({ error: "invalid_grant" }, { status: 400 })
  const cfg = {}
  await (await hook())(cfg)
  assert.deepEqual(cfg, {})
  assert.equal(configCalls, 0)
  assert.equal(existsSync(CACHE), false)
})

test("the hook never throws", async () => {
  mkdirSync(DATA, { recursive: true })
  writeFileSync(`${DATA}/auth.json`, "{not json")
  await (await hook())({})
})

// T-P5
test("skills are rewritten on a version change and removed when dropped", async () => {
  signIn()
  await (await hook())({})
  server.config = () => Response.json(BODY({ skills: [
    { name: "mcp-setup", version: "sha256:b", files: { "SKILL.md": "v2" } },
    { name: "../evil", version: "1", files: { "SKILL.md": "x" } },
  ] }))
  await (await hook())({})
  assert.equal(readFileSync(`${SKILLS}/mcp-setup/SKILL.md`, "utf8"), "v2")
  assert.equal(existsSync(`${DATA}/evil`), false)
  server.config = () => Response.json(BODY({ skills: [] }))
  const cfg = {}
  await (await hook())(cfg)
  assert.equal(existsSync(`${SKILLS}/mcp-setup`), false)
  assert.equal(cfg.skills, undefined)
})
```

- [ ] **Step 2: Run, expect FAIL** — `node --test test/opencode-config-hook.test.mjs` → `fillMissing` not exported / `config` undefined.

- [ ] **Step 3: Implement** in `clients/opencode/index.mjs`

After the `CLIENT_FILE` constant:

```js
const AUTH_FILE = `${DATA}/auth.json` // opencode's own credential store: read only, never written here
const CONFIG_CACHE = `${DATA}/ackstorm-config.json`
const SKILLS_DIR = `${DATA}/ackstorm-skills`
const CONFIG_SCHEMA = "ackstorm.opencode-config/1"
const CONFIG_KEYS = ["provider", "mcp", "instructions"] // anything else the server sends is ignored
const CACHE_MAX_AGE = 30 * 86_400_000
const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
```

After `fresh()`:

```js
const isObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v)

function fill(target, source) {
  if (target === undefined) return structuredClone(source)
  if (!isObject(target) || !isObject(source)) return target // the user's value wins
  for (const [k, v] of Object.entries(source)) target[k] = fill(target[k], v)
  return target
}

// Backend config UNDER the user's: only allow-listed keys, a key the user set
// always wins, `instructions` gains the entries it lacks.
export function fillMissing(target, source) {
  for (const key of CONFIG_KEYS) {
    const value = source?.[key]
    if (value === undefined) continue
    if (key === "instructions") {
      if (!Array.isArray(value) || (target.instructions !== undefined && !Array.isArray(target.instructions))) continue
      target.instructions = [...(target.instructions ?? [])]
      for (const x of value) if (!target.instructions.includes(x)) target.instructions.push(x)
    } else target[key] = fill(target[key], value)
  }
  return target
}

const readJson = (path) => readFile(path, "utf8").then(JSON.parse).catch(() => null)
const sub = (access) => { try { return JSON.parse(Buffer.from(access.split(".")[1], "base64url")).sub } catch { return null } }

async function writePrivate(path, text) {
  await mkdir(DATA, { recursive: true, mode: 0o700 })
  await writeFile(path, text, { mode: 0o600 })
}

// Skills as native opencode skills: one dir per skill, rewritten only when its
// version changes, removed when the backend stops listing it. Names are
// kebab-case, so a name can never leave SKILLS_DIR.
async function writeSkills(skills) {
  const keep = new Set()
  await mkdir(SKILLS_DIR, { recursive: true, mode: 0o700 })
  for (const s of (Array.isArray(skills) ? skills : []).slice(0, 50)) {
    const md = s?.files?.["SKILL.md"]
    if (typeof s?.name !== "string" || s.name.length > 64 || !SKILL_NAME.test(s.name)) continue
    if (typeof md !== "string" || md.length > 256 * 1024) continue
    keep.add(s.name)
    const dir = `${SKILLS_DIR}/${s.name}`
    if ((await readFile(`${dir}/.version`, "utf8").catch(() => null)) === String(s.version)) continue
    await mkdir(dir, { recursive: true, mode: 0o700 })
    await writeFile(`${dir}/SKILL.md`, md, { mode: 0o600 })
    await writeFile(`${dir}/.version`, String(s.version), { mode: 0o600 })
  }
  for (const name of await readdir(SKILLS_DIR)) {
    if (!keep.has(name)) await rm(`${SKILLS_DIR}/${name}`, { recursive: true, force: true })
  }
  return keep.size > 0
}

async function fetchConfig(platform, access) {
  if (!platform) return null
  try {
    const r = await fetch(`${platform.replace(/\/$/, "")}/clients/opencode/config`, {
      headers: { authorization: `Bearer ${access}` },
      signal: AbortSignal.timeout(2_000),
    })
    if (!r.ok) return null
    const body = await r.json()
    return body?.schema === CONFIG_SCHEMA ? body : null
  } catch {
    return null
  }
}

// The config hook. Signed out → nothing (not even the cache). Backend down →
// the same user's cache if < 30 d. Never throws; errors mean "no backend config".
async function applyConfig(cfg, { client, options }) {
  const getAuth = async () => (await readJson(AUTH_FILE))?.[PROVIDER]
  const stored = await getAuth()
  if (stored?.type !== "oauth") return
  const forget = () => rm(CONFIG_CACHE, { force: true })
  let auth = null
  try {
    auth = await fresh(stored, { client, options, getAuth })
  } catch (e) {
    if (e.status >= 400 && e.status < 500) return forget() // refresh token rejected: signed out
    // AS unreachable: an expired access token would read as "invalid", so use the cache.
  }
  let body = auth ? await fetchConfig((await backend(options)).platform, auth.access) : null
  if (body?.auth === "invalid") return forget()
  if (body) {
    await writePrivate(CONFIG_CACHE, JSON.stringify({ user: body.user, fetchedAt: Date.now(), body }))
  } else {
    const cache = await readJson(CONFIG_CACHE)
    if (!cache || cache.user !== sub(stored.access) || Date.now() - cache.fetchedAt > CACHE_MAX_AGE) return
    body = cache.body
  }
  fillMissing(cfg, body.config ?? {})
  if (await writeSkills(body.skills)) {
    cfg.skills = isObject(cfg.skills) ? cfg.skills : {}
    cfg.skills.paths = Array.isArray(cfg.skills.paths) ? cfg.skills.paths : []
    if (!cfg.skills.paths.includes(SKILLS_DIR)) cfg.skills.paths.push(SKILLS_DIR)
  }
}
```

In the object `SsoAuth` returns, add next to `auth`:

```js
    // Runs at every opencode start, before providers/agents read the config.
    async config(cfg) {
      try {
        await applyConfig(cfg, { client, options })
      } catch {} // ponytail: silent; a broken backend must never stop opencode starting
    },
```

- [ ] **Step 4: Run, expect PASS** — `node --test test/opencode-config-hook.test.mjs test/opencode-auth.test.mjs`.

---

### Task 3: Package, README, Makefile, CHANGELOG

- [ ] `clients/opencode/package.json`: `"version": "0.3.0"`, `"description": "OpenCode plugin: SSO sign-in to an ACKstorm backend and its per-user OpenCode config"`, `"files": ["index.mjs", "platform.json", "README.md"]`.
- [ ] `clients/opencode/README.md`:

````markdown
# ackstorm OpenCode plugin

Signs OpenCode in to an ACKstorm backend's model gateway (OAuth: browser or
device code) and, at every start, fills in the user's models, MCP servers and
skills from that backend. The user's own config always wins.

```
opencode plugin https://<origin>/clients/opencode/plugin -g
opencode auth login -p ackstorm
```

Restart OpenCode to pick up backend changes.

## platform.json

Written into the tarball by the backend that serves it; never edit by hand.

| Field | Meaning |
|---|---|
| `api` | The gateway's OpenAI-compatible base URL (e.g. `https://api.example.com/v1`). OAuth discovery starts here (RFC 9728 → RFC 8414). |
| `platform` | The origin serving `/clients/*`. Config comes from `<platform>/clients/opencode/config` (schema `ackstorm.opencode-config/1`). |

Override per install with plugin options in `opencode.json`:
`"plugin": [["https://<origin>/clients/opencode/plugin", {"api": "...", "platform": "..."}]]`.

## Files it writes (`$XDG_DATA_HOME/opencode`, default `~/.local/share/opencode`)

| File | Content |
|---|---|
| `ackstorm-client.json` | The dynamic client registration (client id). |
| `ackstorm-config.json` | Last good backend config (0600), used for 30 days when the backend is down. |
| `ackstorm-skills/<name>/SKILL.md` | Skills delivered by the backend. |

Tokens live in OpenCode's own `auth.json`; the plugin never writes it.

## Vendoring

The source of truth is `alitellm-auth/clients/opencode`. Other products vendor a
tagged copy unchanged and ship their own `platform.json`.
````

- [ ] `Makefile` (target at ~line 95): `node --test test/opencode-auth.test.mjs test/opencode-config-hook.test.mjs`.
- [ ] `CHANGELOG.md` `[unreleased]` → `### Added`:

```markdown
- **OpenCode plugin 0.3.0: backend bootstrap and per-user config.** The plugin
  finds its backend from `platform.json` in the tarball (or plugin options)
  instead of the `ackstorm` provider in config, so a fresh install signs in
  without `OPENCODE_MODELS_URL`. At every OpenCode start it fetches
  `/clients/opencode/config` and fills in what the user's config lacks
  (models, disabled MCP servers, skills under `ackstorm-skills/`); cached 30 d
  for the same user when the backend is down. Users re-run
  `opencode plugin <url> -g -f` once.
```

- [ ] **Gates**: `make <plugin test target>` (or both `node --test` files) green; `node --check clients/opencode/index.mjs`.
- [ ] **One review** of the diff, then commit via `git:commit-push` after user approval: `feat(opencode-plugin): backend bootstrap and per-user config hook`.

## After this plan

- **Release**: the next `make release-bump`/`release-cut` tag is the first with the hook + `platform.json` → tell ACH (spec Rev 4, R4-4).
- **T6** (real `opencode` 1.18.31 + the dev docker-compose stack): hook-injected provider/mcp/skills visible in `opencode models`, `opencode mcp list`, the skill list; auth refresh at startup; backend down → cache.
- **How-To / README** install story; drop `OPENCODE_MODELS_URL` / `LITELLM_API_KEY` guidance after the pilot.
