# TODO — OAuth clients

The authorization server and the gateway that maps a token to a LiteLLM key live in
another service (removed here 2026-09-19); this repo ships only the clients. Items still open.

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
  Codex `[model_providers.<id>.auth] command = "…"` (a string, not an array) both work.
- [ ] Distribute `ackstorm-token` (package/installer; hydrate writes the two settings)
  and decide keyring vs file for the refresh token.
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
- [ ] Claude Code loopback: when the browser is on another machine the redirect to
  `localhost:<port>` fails; the "paste the URL" fallback works. Document.

## Code

- [ ] Local `uv run ruff` (0.14) and the devtools/CI ruff (0.8.4) disagree on one
  assert style; CI is the gate. Pin one.

## Security hygiene (Juan Carlos)

- [ ] Rotate the glab token an implementation agent displayed on 2026-09-17.
- [ ] Rotate `LITELLM_API_KEY` leaked in a transcript the same day; `chmod 600 ~/.config/ackstorm-ai.env`.
