# TODO — OAuth front door (api.*)

Live since 2026-09-17 (v0.8.1). Items still open, by owner.

## Platform / gitops

- [ ] **NetworkPolicy on `litellm:4000`** — decided ("no direct access to LiteLLM"),
  not applied: 8 in-cluster consumers call it directly (librechat, hindsight, ach,
  ach-memory, muster, guardrails, alitellm-operator, ach-memory-mcp). Either an
  allow-list of all of them or move them to the gateway first.
- [ ] **Terraform the AS secrets** — `INTERNAL_TOKEN`, `AS_SIGNING_KEY_PEM`,
  `AS_KEY_ENCRYPTION_KEY`, `AS_REDIS_URL` were put by hand into SM
  `genai/platform-api` (a hand-made secret, like `SESSION_SECRET_KEY` there).
  `AS_REDIS_URL` embeds the mcp valkey password, which mittwald generates in-cluster;
  moving it to terraform means the valkey secret becomes an ExternalSecret too.
- [ ] `AS_SERVICES` lists only `mcp-aws-eks-ro` and `mcp-google-drive`; every other
  MCP service needs `AUTH_BROKER_ENABLED=true` + the `/<svc>-callback/` prefix route
  before it can be a token scope.
- [ ] hindsight.* / guardrails.* lost their gateway SSO when the oauth2-proxy CUSTOM
  policies were retired (Istio: one ext_authz provider per workload). Confirm they
  are meant to be open, or put them behind the front door.
- [ ] Dex → LiteLLM offboarding sync (the refresh-time LiteLLM re-check is a stopgap).

## Clients

- [x] **OpenCode model-path OAuth** — plugin `~/.config/opencode/plugins/ackstorm-auth.mjs`
  (DCR + PKCE + loopback + refresh in a custom `fetch`) works: `opencode auth login -p
  ackstorm` → Dex → token in `auth.json`; `opencode run -m ackstorm/ackstorm.fast` answers
  through the front door. The literal `apiKey` is gone from `opencode.json`
  (2026-09-17, Juan Carlos's box only).
- [ ] **Distribute the plugin**: the served catalog (`/public/opencode/api.json`, models.dev
  format) cannot express OAuth — opencode only does provider OAuth through a plugin
  `auth` hook. Publish `ackstorm-auth.mjs` as an npm package and list it in the
  opencode config the platform serves (`.well-known/opencode` → `config.plugin`), so a
  user runs `opencode auth login https://platform.ackstorm.ai` once and never installs
  anything by hand. Source of truth for the plugin: this repo (`clients/opencode/`?).
- [ ] **Upstream the opencode method**: no client does OAuth (8414 + DCR + PKCE) for a
  *model* provider; opencode's OpenAI/Anthropic/Copilot logins are vendor-specific
  plugins. Propose a generic `oauth` auth method keyed on `provider.<id>.options.oauth.issuer`
  to anomalyco/opencode; the plugin is the reference implementation.
- [ ] **Claude Code / Codex model path**: their contract is "a command that prints a
  credential" (`apiKeyHelper`, `auth.command`). Ship a small CLI (`alitellm-auth token`?)
  that logs in once (DCR + PKCE + loopback), keeps the refresh token in the OS keyring
  or a 0600 file, and prints a fresh access token; hydrate points the two settings at it.
- [ ] Runbook rows not yet exercised: 4d/4e (Claude Code model path via
  `ANTHROPIC_CUSTOM_HEADERS=x-genai-api-key: …` with a LiteLLM key and with a front
  JWT), 7d (revoke the grant → next refresh drops the scope → 403 again).
- [ ] Claude Code loopback: when the browser is on another machine the redirect to
  `localhost:<port>` fails; the "paste the URL" fallback works. Document.

## Code

- [ ] `pending["scope"]` records written by v0.7.x error with KeyError for the
  600 s after an upgrade (`routes.py` `as_callback`). Harmless once past; guard or ignore.
- [ ] `brokerclient` DCR cache (90 d): if a broker loses its client registry the
  chain dead-ends at the broker with no self-heal. Recovery: `DEL <prefix>:brokerclient:<broker>`.
- [ ] The MCP broker keys its grant by the identity *its* Dex leg resolves; if that
  ever differs from the front's `sub` (e.g. a different Google account at the
  provider), the scope never appears. One sentence in `grants.py` once verified.
- [ ] `offline_access` is not advertised; if it ever is, `authorize` must accept it.
- [ ] Local `uv run ruff` (0.14) and the devtools/CI ruff (0.8.4) disagree on one
  assert style; CI is the gate. Pin one.

## Security hygiene (Juan Carlos)

- [ ] Rotate the glab token an implementation agent displayed on 2026-09-17.
- [ ] Rotate `LITELLM_API_KEY` leaked in a transcript the same day; `chmod 600 ~/.config/ackstorm-ai.env`.
