# Changelog

## [unreleased]

## [0.2.0] - 2026-06-02
- BREAKING: rename GET /api/oauth/me → GET /api/oauth/whoami; old path now returns 404
- BREAKING: API header renamed x-ackstorm-api-key → x-alitellm-auth-api-key for /whoami and /api/oauth/tokens/{id}
- feat: create a LiteLLM User (user_id=email) on every login via /user/new before key generation; keys scoped to user_id
- feat: admin CRUD — GET /api/users, GET /api/users/{email}, DELETE /api/users/{email} (master-key authz via hmac.compare_digest)
- fix: harden user lookup for LiteLLM v1.83 — default_user_id placeholder triggers /user/list fallback; teams returned as objects normalized to alias-preferred strings
- fix: treat "already exists" 400/409 on /user/new as idempotent success (mirrors team-creation behavior)
- chore: rename package platform-api → alitellm-auth (version 0.2.0); k8s resources, secret name, configmap name updated accordingly
- docs: Dex/Keycloak OIDC integration guide (docs/dex-integration.md); README rewrite; CLAUDE.md corrected (removed false _email_to_team_id pattern, added real shared-team + User model, v1.83 quirks)
- feat: deploy/ — Helm chart + Kustomize base/overlays (replaces k8s/); chart published as an OCI artifact to ghcr.io/ackstorm/charts/alitellm-auth alongside the image

## [0a57794] - 2026-04-23
- Format pydantic ValidationError startup failures as a friendly list of missing env vars (no traceback) with a hint pointing at the k8s secret

## [b083d4c] - 2026-04-23
- Log traceback when create_app() fails at import time so real startup errors surface in pod logs (was silently setting app=None, causing cryptic "NoneType object is not callable" in uvicorn)

## [7f4fc93] - 2026-03-03
- Remove unrecoverable key hash from /reveal HTML and /tokens JSON response
- success.html: hide "Your API Key" section when key is None
- tokens action: strip "key" field from each token in JSON response

## [1a39192] - 2026-03-03
- Unify all OIDC flows into single /api/oauth/callback via session["oauth_action"]
- Remove /api/oauth/reveal/callback and /api/oauth/tokens/callback routes
- Add 3 new tests for login/reveal/tokens action dispatching (24 tests total)

## [f21333e] - 2026-03-03
- Simplify /api/oauth/me handler: pass-through dict from get_key_info instead of manual field mapping
- Add spend/max_budget/budget_duration/tpm_limit/rpm_limit/last_active to /me response
- Normalize spend default to 0.0 consistently across litellm_client and auth handler
- Remove dead _delete_key_by_alias function (superseded by timestamp-unique aliases)
- Fix get_key_info error message (was incorrectly referencing /key/delete)
- Refactor test_auth.py: shared client fixture, consolidated imports, full field assertions

## [f342a12] - 2026-03-02
- Add GET /api/oauth/me endpoint: validates x-ackstorm-api-key header against LiteLLM and returns user email + metadata as JSON
- Add get_key_info() to litellm_client; extract _admin_headers() helper to remove duplication
- Document endpoint in CLAUDE.md with curl example and response schema

## [87712be] - 2026-03-01
- Fixed access group API endpoint to /v1/access_group (confirmed via OpenAPI spec)

## [ccf551f] - 2026-03-01
- Fixed access group API: endpoint is /access_group, field is access_group_name, list returns array directly

## [a9bf980] - 2026-03-01
- Access group with same name as OAUTH_CLIENT_ID is created idempotently and each generated key is assigned to it via access_group_ids

## [01a7152] - 2026-03-01
- Key metadata now includes name (from OIDC), created_at (UTC ISO timestamp), and key_alias

## [3d1a88b] - 2026-03-01
- models and allowed_routes are now hardcoded defaults (all-team-models, llm_api_routes), overridable via configmap
- configmap: added rpm/tpm limits, max_parallel_requests, budget settings matching test key

## [0c78877] - 2026-03-01
- COPY button is now gray and right-aligned
- Key alias format changed to tf-{timestamp}-{email} — unique per login, no deletion of previous keys
- _delete_key_by_alias helper kept for future use

## [1bdefd0] - 2026-03-01
- Error page now shows the human-readable message from LiteLLM JSON response (error.message) instead of raw JSON

## [45ccd08] - 2026-03-01
- Key rotation on re-login: if alias already exists, old key is deleted and a fresh one is issued

## [dad43e1] - 2026-03-01
- Added factory_config_path to Settings (optional, defaults to None)
- Made platform-factory-config configmap volume optional in deployment.yaml so pod starts without it
- Added configmap.yaml example with user budget defaults
