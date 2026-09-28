# OpenWork and OpenCode — how we configure them

| | |
|---|---|
| Status | Reference. Applies to any product backend (platform / alitellm-auth, or ACH) |
| Date | 2026-09-28 (rev 3: Den is served by each backend on its own origin) |
| Owner | Juan Carlos Moreno (DREAM) |
| Scope | OpenWork desktop on **engine v1** and the OpenCode CLI |
| Evidence base | `different-ai/openwork` @ `917f672`, `anomalyco/opencode` @ `b471c2b` (both 2026-09-26) |

Placeholders: `<backend>` is the product's public origin (e.g.
`https://platform.example.com`), `<api>` its model/MCP gateway origin (e.g.
`https://api.example.com`). The Den is served by the backend itself on
`<backend>` (platform: inside alitellm-auth; ACH: inside ACH), so the
organization server URL users enter is `<backend>`.

## 1. The pieces

| Piece | What it is | Who runs it |
|---|---|---|
| OpenWork desktop | Electron app; runs a local OpenWork server and an OpenCode engine | User's machine |
| OpenCode engine v1 | The `opencode` binary OpenWork spawns (same one as the CLI) | User's machine |
| Auth plugin | OpenCode plugin: OAuth sign-in to the backend's gateway (browser or device code), token refresh on every model call, and at start fetches the user's config | Installed once per user, globally |
| Backend config endpoint | `GET <backend>/api/opencode/config`: models, capabilities, MCP servers, skills for **this** user, schema `ackstorm.opencode-config/1` | Each product |
| Den | OpenWork organization server: org sign-in, **enforced** desktop policy, branding, onboarding | Each product, on its own origin (`<backend>/api/den`) |
| Gateway | LiteLLM behind the OAuth front door; MCP servers behind mcp-oauth | Each product |

## 2. What comes from where

| Need | Source | Enforced? | When it changes on the client |
|---|---|---|---|
| Model sign-in | Plugin OAuth (`opencode auth login -p ai-platform`) | Yes (gateway) | Tokens refresh per request |
| Model list + capabilities (image input, context, cost) | Backend config endpoint → plugin | No: defaults the user can override | Next OpenCode/OpenWork start |
| MCP servers (disabled by default) | Backend config endpoint → plugin | No | Next start |
| MCP sign-in | OpenCode's own MCP OAuth (on first 401, or `opencode mcp auth <name>`) | Yes (mcp-oauth / gateway) | Per server |
| Skills | Backend config endpoint → plugin writes them as native skills | No | Next start |
| Org identity in the desktop | Den | — | Sign-in |
| Desktop policy (Zen model, extensions, commands, uploads…) | Den `desktop-config` | **Yes**: OpenWork's local server returns 403 `organization_policy_denied` | On config refresh |
| Branding (name, logo, icon, accent) | Den `desktop-config` | — | On config refresh |
| Onboarding (which org server) | Den install link, or MDM bootstrap file | — | Once |

Rules that follow:
- Anything that must be a **limit** lives in the gateway (who can call which
  model or MCP) or in Den policy (what the desktop may do). The plugin's config
  is a convenience layer.
- The user's own `~/.config/opencode/opencode.json` and a project's
  `opencode.json` **always win** over what the backend delivers.
- Nothing needs an environment variable. `OPENCODE_MODELS_URL` and
  `LITELLM_API_KEY` are no longer used.

## 3. User onboarding

### 3.1 OpenCode CLI
```bash
opencode plugin <backend>/public/opencode-auth -g
opencode auth login -p ai-platform      # browser SSO; "device code" for headless hosts
opencode                               # models, MCPs and skills are there
```
Then, per MCP server wanted: enable it (set `"enabled": true` in the global or
project config, or ask the agent to) and run `opencode mcp auth <name>`.

### 3.2 OpenWork desktop (engine v1)
1. Install OpenWork.
2. Join the organization: paste the install link
   (`<backend>/install?token=<token>`) in Welcome → "Join organization", **or** set
   Settings → organization server URL to `<backend>`, **or** have MDM drop the
   bootstrap file (§4.3). Sign in (browser opens, SSO, back to the app).
3. In a terminal, run the two plugin commands of §3.1. This cannot be done by
   the agent: before the plugin is signed in there is no model to run it.
4. Restart OpenWork. Models, MCP servers (disabled) and skills appear.

## 4. Admin setup per deployment

### 4.1 Backend
- [ ] `GET <backend>/public/opencode-auth` serves the plugin tarball with
      `platform.json` = `{"api": "<api>", "platform": "<backend>"}`.
- [ ] `<api>` publishes RFC 9728 protected-resource metadata and its
      authorization server publishes RFC 8414 metadata with DCR, PKCE S256,
      refresh tokens (and optionally the RFC 8628 device grant).
- [ ] `GET <backend>/api/opencode/config` implements
      `ackstorm.opencode-config/1`: always 200 for a well-formed Bearer
      (baseline with `auth: "invalid"` when the token is not valid), never 5xx,
      last-good cache per user; never emits `plugin`, `permission`, `agent`,
      `command`, secrets or `{env:}`/`{file:}` templates.
- [ ] MCP servers exposed as remote OAuth servers (`<api>/mcp/<name>`).

### 4.2 Den
- [ ] Den answers at the root of `<backend>`: `/api/den/*`, and the sign-in
      entry `/?desktopAuth=1` must reach the handoff page (OpenWork keeps only
      the origin of the org server URL). If `/` redirects elsewhere (e.g. to a
      console), that redirect must not apply when `desktopAuth=1` is present.
- [ ] `/api/den/*` is not behind the gateway's front-door authz; Den
      authenticates every request itself.
- [ ] Sign-in uses the backend's existing web login (Dex).
- [ ] Org name and **slug** (the slug fixes the org id; do not change it after
      users joined).
- [ ] Branding: app name, logo/icon URLs (or files), accent from OpenWork's 22
      Radix families.
- [ ] Policy: §5.
- [ ] Install link tokens (static, one per org or audience). Contract:
      `GET /api/den/v1/install-config?token=<token>` →
      `{appName, clientName, webUrl: "<backend>", apiUrl, requireSignin,
      logoUrl|null, iconUrl|null}`; unknown token → 404 (shown as "expired");
      token matches `^[A-Za-z0-9_-]{8,}$`. Accepted link forms:
      `<backend>/install?token=X` (preferred) and `<backend> X`. The desktop maps
      `/install` to `/api/den/v1/install-config` itself.

### 4.3 MDM bootstrap file (managed fleets)
`~/.config/openwork/desktop-bootstrap.json` (path override
`OPENWORK_DESKTOP_BOOTSTRAP_PATH`):
```json
{
  "baseUrl": "https://platform.example.com",
  "requireSignin": true,
  "brandAppName": "Example AI",
  "brandLogoUrl": "https://platform.example.com/openwork/brand/logo.svg",
  "brandIconUrl": "https://platform.example.com/openwork/brand/icon.svg",
  "writtenAt": "2026-09-27T10:00:00Z"
}
```
The newest `writtenAt` wins. `requireSignin: true` keeps the app at sign-in
until the user joins the org.

## 5. Desktop policy defaults

| Field | Default | Why |
|---|---|---|
| `allowZenModel` | `false` once the plugin-delivered models are live, `true` before | Zen is OpenCode's built-in hosted provider: data leaves the organization's gateway. Before the plugin works it is the only model, so switching it off early leaves users with nothing |
| `allowCustomProviders` | `true` | The `ai-platform` provider comes from OpenCode config (the plugin), not from Den; `false` restricts providers to Den-delivered ones and hides it |
| `allowManageExtensions` | `true` | Users must be able to install the auth plugin |
| `allowBuiltInExtensions` | `true` | No reason to block |
| `allowControlSettings` | `true` | Users need Settings to join the org and see providers |
| `allowMultipleWorkspaces` | `true` | No reason to block |
| `allowAlphaUpdates` | `false` | Stable channel only |
| `showWelcomePage` | `false` | Onboarding is the install link |
| `execution.commands` | `"allow"` | Agents need a shell |
| `execution.blockedCommands` | `[]` | **Any non-empty list disables interactive terminals and saved commands entirely**; use only when that is intended |
| `execution.blockBrowserUploads` | per client (`true` for regulated clients) | Stops file uploads through the in-app browser |
| `automationsEnabled` | `false` | Not offered |
| `dashboardEnabled` | `false` | Not offered |
| `connectEnabled` | `true` | Keeps OpenWork's Connect health green; the Connect catalog is empty |

## 6. How it behaves

- **Refresh**: the plugin rebuilds config at every OpenCode/OpenWork start.
  Nothing changes inside a running session; restart to pick up changes.
- **Backend down or slow**: the plugin waits at most 2 s, then uses its last
  good copy (same user, < 30 days). OpenCode always starts.
- **Signed out / revoked**: the backend answers with the baseline; the plugin
  clears its cache and delivers nothing; models stop working until
  `opencode auth login -p ai-platform`.
- **User overrides**: a user or project entry for the same model or MCP server
  wins, field by field. A server the user enabled stays enabled.
- **Removed on the backend**: disappears at the next start, unless the user
  defined it themselves.
- **One backend per OpenCode profile**: the provider id is `ai-platform` in
  every product. Someone using two backends needs separate OpenCode profiles.

## 7. Limitations

- **Engine v1 only.** OpenWork's engine v2 (`opencode2`, preview) uses a
  different config loader and its own config directory; whether it loads the
  user's global plugins is unverified. If it does not, neither model OAuth nor
  config delivery works there. Re-evaluate before OpenWork makes v2 the default.
- **Not policy.** Anything delivered by the plugin can be overridden locally.
- **No server-pushed code.** OpenCode plugins cannot be pushed by Den or by the
  backend; the user installs the auth plugin.
- **Den skills: none.** A skill needs an authenticated model; Den cannot help
  before the plugin is signed in.
- **Rejected on purpose:** OpenCode's `.well-known/opencode` remote config
  (unauthenticated fetch, static `{env:}` token, v1-only, aborts startup on
  failure) and Den `llmProviders` (provider keyed `lpr_…`, breaks the plugin's
  auth binding).

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No `ai-platform` models after install | Not signed in, or OpenCode not restarted | `opencode auth login -p ai-platform`, restart |
| Models present but requests 401 | Refresh token expired or revoked | `opencode auth login -p ai-platform` |
| Old model list after a backend change | Config applies at start | Restart OpenCode/OpenWork |
| Image input not offered for a model | Capability missing in the backend catalog | Fix the model's `modalities` in the backend |
| MCP server listed but unusable | Disabled by default, or not signed in | Enable it, restart, `opencode mcp auth <name>` |
| MCP 403 `insufficient_scope` | Sign-in did not grant that server | `opencode mcp logout <name>` then `auth` again |
| MCP 403 from the gateway after sign-in | User lacks access to that server | Admin grants access (access group) |
| MCP OAuth loops | Same as above: entitlement 403 retried by the client | Fix the access group, not auth |
| OpenWork refuses an action with `organization_policy_denied` | Den policy | Expected; change policy in Den if wrong |
| Terminal disabled in OpenWork | `blockedCommands` is non-empty | Empty it unless intended |
| Zen models still visible | `allowZenModel` true, or desktop has not refreshed config | Set to false; re-sign-in or wait for refresh |

## 9. Verification checklist (new deployment)

- [ ] CLI: two commands, restart, `opencode models` shows the user's models;
      an image-capable model accepts an image.
- [ ] CLI: `opencode mcp list` shows the servers disabled; enabling one and
      `opencode mcp auth <name>` works.
- [ ] CLI: skills from the backend are listed.
- [ ] CLI: with `<backend>` unreachable, OpenCode starts with the cached config.
- [ ] OpenWork v1: join via install link, branding shown, policy enforced
      (try a blocked action), Connect healthy.
- [ ] OpenWork v1: after the plugin commands and a restart, same models, MCPs
      and skills as the CLI.
- [ ] Revoking the user's session makes models fail and the next start deliver
      nothing.
