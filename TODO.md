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

- [x] **OpenCode model-path OAuth** — moved to `ackstorm/ach` (`internal/platformapi/opencodeauth`)
  and served by the authorization server: `opencode plugin
  https://api.ackstorm.ai/platform/opencode-auth -g`, then `opencode auth login -p ackstorm`.
  Zero config: provider API URL from opencode → RFC 9728 → RFC 8414. Verified incl. refresh (2026-09-17).
  Measured: opencode fetches the tarball at install and once on the first launch, then
  never — a new release needs `opencode plugin <url> -g -f`. The served `api.json` still
  lists `env: ["LITELLM_API_KEY"]`; an exported key masks a logout (OAuth wins when both
  exist). Drop `env` from `/public/opencode` when everyone is on the plugin.
- [ ] **Upstream the opencode method**: no client does OAuth (8414 + DCR + PKCE) for a
  *model* provider; opencode's OpenAI/Anthropic/Copilot logins are vendor-specific
  plugins. Propose a generic `oauth` auth method keyed on `provider.<id>.options.oauth.issuer`
  to anomalyco/opencode; the plugin is the reference implementation.
- [x] **Claude Code / Codex model path** — `clients/ackstorm-token` (Python 3, stdlib):
  logs in once (DCR + PKCE + loopback), keeps the refresh token in
  `~/.config/ackstorm-ai/token.json` (0600, flock against concurrent refreshes) and
  prints a fresh access token. Verified 2026-09-17: Claude Code `apiKeyHelper` and
  Codex `[model_providers.<id>.auth] command = "…"` (a string, not an array) both
  answer through the front door.
- [ ] Distribute `ackstorm-token` (package/installer; hydrate writes the two settings)
  and decide keyring vs file for the refresh token.
- [ ] authz hardening: when the custom header / `x-api-key` carries OUR JWT and
  `Authorization` carries the same JWT (Claude Code may send the helper's value in
  both), the second copy currently travels to LiteLLM untouched. Strip an
  `Authorization` bearer that equals the mapped token. Measure first whether Claude
  Code does that.
- [ ] **Codex with a ChatGPT subscription through LiteLLM** (like Claude Code's
  Anthropic subscription): Codex side is config-only (custom provider with
  `requires_openai_auth = true`, `base_url`, `http_headers` with our key — never
  `[model_providers.openai]`, silently ignored; `OPENAI_BASE_URL` is not read).
  LiteLLM side blocks: `forward_client_headers_to_llm_api` forwards `Authorization`
  only for `sk-ant-oat*` to provider `anthropic`; the `chatgpt/` provider uses one
  server-side device-code token per proxy. Needs an upstream change (~20 lines:
  ChatGPT-JWT detector scoped to `chatgpt`, `validate_environment` accepting a
  forwarded bearer + `ChatGPT-Account-ID`; discussion BerriAI/litellm#26010) or a
  gitops patch like `patch_mcp_server.py`. Until then Codex = API-key billing.
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
