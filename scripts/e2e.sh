#!/usr/bin/env bash
# E2E runner: pre-cleanup, compose up --wait, headless OIDC login from inside
# compose network, all D-09 assertions, compose down on exit.
# Exits non-zero on any failure. Usable locally and from CI.
set -euo pipefail

# Always run from repo root regardless of where the script is invoked from.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMPOSE_FILE="test/e2e/docker-compose.yml"

# Compose CLI resolution: prefer the Docker Compose v2 plugin ("docker compose"),
# fall back to the standalone "docker-compose" binary (also Compose v2 in modern
# installs). Lets `make e2e` run on hosts that have only one of the two — no manual
# ~/.docker/cli-plugins symlink required. Use the `dc` wrapper for every call below.
if docker compose version >/dev/null 2>&1; then
  dc() { docker compose "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
  dc() { docker-compose "$@"; }
else
  echo "FAIL: no Compose CLI found — install the 'docker compose' plugin or the 'docker-compose' binary" >&2
  exit 1
fi

MASTER_KEY="sk-test-master-key"
APP_URL="http://localhost:8080"
# CR-01: the Dex mockCallback connector (test/e2e/dex-config.yaml) returns a
# FIXED, non-configurable identity — email "kilgore@kilgore.trout". The app
# provisions user_id=<that email> verbatim, so seeding + every assertion MUST
# target it. Using any other address makes the seed sentinel exit 1 before any
# assertion runs. Keep this aligned with the mockCallback identity.
TEST_EMAIL="kilgore@kilgore.trout"

# ---------------------------------------------------------------------------
# cleanup: tear down the compose stack on all exit paths (success and failure)
# ---------------------------------------------------------------------------
cleanup() {
  dc -f "$COMPOSE_FILE" down --volumes --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# PRE-UP CLEANUP: remove stale state from any previously interrupted run.
# Prevents stale LiteLLM Postgres data or running containers from masking failures.
# ---------------------------------------------------------------------------
dc -f "$COMPOSE_FILE" down --volumes --remove-orphans 2>/dev/null || true
echo "e2e: pre-up cleanup done"

# ---------------------------------------------------------------------------
# STACK UP: use healthcheck-based blocking (D-10: no naked polling loops).
# Falls back to bounded ok-sentinel curl retry if --wait is unavailable.
# ---------------------------------------------------------------------------
if dc -f "$COMPOSE_FILE" up --wait --timeout 120 2>/dev/null; then
  echo "e2e: stack healthy via --wait"
else
  echo "e2e: --wait unsupported or timed out; falling back to curl readiness poll" >&2
  ok=0
  for i in $(seq 1 30); do
    curl -sf "$APP_URL/health" && { ok=1; break; }
    sleep 4
  done
  [ "$ok" -eq 0 ] && { echo "FAIL: app never ready after 120s" >&2; exit 1; }
fi

# ---------------------------------------------------------------------------
# HEADLESS OIDC LOGIN — compose-internal topology.
# The app's OAUTH_ISSUER_URL is http://dex:5556/dex and APP_BASE_URL is
# http://app:8080, both resolvable only inside the compose network.
# Drive the full redirect chain from inside the app container where dex resolves.
# ---------------------------------------------------------------------------
echo "e2e: running headless OIDC login inside compose network..."
dc -f "$COMPOSE_FILE" exec -T app \
  python -c "
import urllib.request, http.cookiejar

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
opener.addheaders = [('User-Agent', 'e2e-runner/1.0')]

# Follow redirect chain: /api/oauth/login -> dex auth -> dex mockCallback -> /api/oauth/callback
# All URLs are compose-internal and resolvable from inside the app container.
resp = opener.open('http://app:8080/api/oauth/login')
print('login chain completed, final URL:', resp.geturl())
"

# Bounded sentinel: verify user was seeded (host-side curl, admin API only — no OIDC)
ok=0
for i in $(seq 1 10); do
  status=$(curl -sS -o /dev/null -w "%{http_code}" \
    -H "x-alitellm-auth-api-key: $MASTER_KEY" \
    "$APP_URL/api/users/$TEST_EMAIL" 2>/dev/null || echo "000")
  [ "$status" = "200" ] && { ok=1; break; }
  sleep 2
done
[ "$ok" -eq 0 ] && { echo "FAIL: seeding did not create user $TEST_EMAIL (last status: $status)" >&2; exit 1; }
echo "e2e: user $TEST_EMAIL confirmed seeded"

# ---------------------------------------------------------------------------
# E2E-01: GET /api/users with master key returns 200
# ---------------------------------------------------------------------------
status=$(curl -sS -o /dev/null -w "%{http_code}" \
  -H "x-alitellm-auth-api-key: $MASTER_KEY" "$APP_URL/api/users")
[ "$status" = "200" ] || { echo "FAIL E2E-01: expected 200, got $status"; exit 1; }
echo "E2E-01 PASS: GET /api/users returned 200"

# ---------------------------------------------------------------------------
# E2E-02.1: token strip — keys array is non-empty AND no entry contains a "key" field.
# Two-part assertion: (a) non-empty proves OIDC login minted a key and /key/list->
# /key/info hydration ran; (b) no "key" field proves token stripping works.
# Uses stdin pattern to avoid apostrophe/quote injection from shell substitution.
# ---------------------------------------------------------------------------
response=$(curl -sS "$APP_URL/api/users/$TEST_EMAIL" \
  -H "x-alitellm-auth-api-key: $MASTER_KEY")
echo "$response" | dc -f "$COMPOSE_FILE" exec -T app \
  python -c "
import json, sys
d = json.loads(sys.stdin.read())
keys = d.get('keys', [])
if len(keys) == 0:
    print('FAIL E2E-02.1: keys array is empty -- OIDC login did not mint a key or hydration failed')
    sys.exit(1)
bad = [k for k in keys if 'key' in k]
if bad:
    print(f'FAIL E2E-02.1: {len(bad)} key entries contain a raw key field -- token strip broken')
    sys.exit(1)
print(f'E2E-02.1 PASS: {len(keys)} key(s) found, none contain raw key field')
" || { echo "FAIL E2E-02.1"; exit 1; }

# ---------------------------------------------------------------------------
# E2E-02.2a: DELETE returns 404 for a genuinely absent user.
# Uses -sS -o /dev/null -w "%{http_code}" (not -f) to capture status code
# without curl exit-code interference under set -e.
# ---------------------------------------------------------------------------
status=$(curl -sS -o /dev/null -w "%{http_code}" -X DELETE \
  -H "x-alitellm-auth-api-key: $MASTER_KEY" \
  "$APP_URL/api/users/absent@never-existed.example.com")
[ "$status" = "404" ] || { echo "FAIL E2E-02.2a: expected 404 for absent user, got $status"; exit 1; }
echo "E2E-02.2a PASS: absent user returns 404"

# ---------------------------------------------------------------------------
# E2E-02.2b: DELETE returns 502 when LiteLLM is stopped mid-flight.
# ---------------------------------------------------------------------------
dc -f "$COMPOSE_FILE" stop litellm
sleep 1
status=$(curl -sS -o /dev/null -w "%{http_code}" -X DELETE \
  -H "x-alitellm-auth-api-key: $MASTER_KEY" \
  "$APP_URL/api/users/$TEST_EMAIL")
[ "$status" = "502" ] || { echo "FAIL E2E-02.2b: expected 502 when LiteLLM stopped, got $status"; exit 1; }
echo "E2E-02.2b PASS: stopped backend returns 502"
dc -f "$COMPOSE_FILE" start litellm

# Bounded sentinel: wait for LiteLLM to recover before running next assertion.
ok=0
for i in $(seq 1 20); do
  curl -sf http://localhost:4000/health/readiness && { ok=1; break; }
  sleep 3
done
[ "$ok" -eq 0 ] && { echo "FAIL: LiteLLM did not recover after restart within 60s" >&2; exit 1; }
echo "e2e: LiteLLM recovered"

# ---------------------------------------------------------------------------
# E2E-02.3: non-ASCII header byte returns 403 (not 500).
# MUST use curl with raw byte (not httpx TestClient — TestClient cannot transmit
# 0x80-0xFF header bytes). Uses -sS -o /dev/null -w "%{http_code}" (not -f).
# ---------------------------------------------------------------------------
status=$(curl -sS -o /dev/null -w "%{http_code}" \
  -H "$(printf 'x-alitellm-auth-api-key: sk-\x80')" \
  "$APP_URL/api/users")
[ "$status" = "403" ] || { echo "FAIL E2E-02.3: expected 403 for non-ASCII header byte, got $status"; exit 1; }
echo "E2E-02.3 PASS: non-ASCII header returns 403"

echo "E2E: all assertions passed."
