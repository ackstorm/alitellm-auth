#!/usr/bin/env bash
# End-to-end check for fake-den.mjs: page mints a grant, grant exchanges once,
# token authenticates, replay is rejected.
set -euo pipefail

PORT="${PORT:-8799}"
BASE="http://localhost:${PORT}"
DIR="$(cd "$(dirname "$0")" && pwd)"

PORT="$PORT" node "$DIR/fake-den.mjs" >/tmp/fake-den-smoke.log 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
  curl -sf "$BASE/api/runtime-config" >/dev/null 2>&1 && break
  sleep 0.1
done
curl -sf "$BASE/api/runtime-config" >/dev/null || { echo "FAIL: server never came up"; cat /tmp/fake-den-smoke.log; exit 1; }

GRANT="$(curl -s "$BASE/?mode=sign-in&desktopAuth=1&desktopScheme=openwork" | grep -o 'grant=[A-Za-z0-9_-]\{32,\}' | head -1 | cut -d= -f2)"
[ -n "$GRANT" ] || { echo "FAIL: no grant on sign-in page"; exit 1; }

EXCHANGE="$(curl -s -X POST "$BASE/api/den/v1/auth/desktop-handoff/exchange" \
  -H 'content-type: application/json' -d "{\"grant\":\"$GRANT\"}")"
TOKEN="$(printf '%s' "$EXCHANGE" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
[ -n "$TOKEN" ] || { echo "FAIL: exchange returned no token: $EXCHANGE"; exit 1; }

curl -s "$BASE/api/den/v1/me" -H "authorization: Bearer $TOKEN" | grep -q '"email"' \
  || { echo "FAIL: /v1/me rejected a freshly minted token"; exit 1; }
curl -s "$BASE/api/den/v1/me/orgs" -H "authorization: Bearer $TOKEN" | grep -q '"activeOrgId"' \
  || { echo "FAIL: /v1/me/orgs did not return an active org"; exit 1; }

curl -s -X POST "$BASE/api/den/v1/auth/desktop-handoff/exchange" \
  -H 'content-type: application/json' -d "{\"grant\":\"$GRANT\"}" | grep -q 'grant_not_found' \
  || { echo "FAIL: consumed grant was accepted a second time"; exit 1; }

curl -s "$BASE/api/den/v1/me" -H "authorization: Bearer nope" | grep -q 'unauthorized' \
  || { echo "FAIL: unknown token was accepted"; exit 1; }

MCP_TOKEN="$(curl -s -X POST "$BASE/api/den/v1/mcp/token" -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"scopes":["mcp:read","mcp:write"]}' \
  | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
[ -n "$MCP_TOKEN" ] || { echo "FAIL: no MCP token minted"; exit 1; }

MCP_URL="$BASE/api/den/mcp/agent"
curl -s -X POST "$MCP_URL" -H "authorization: Bearer $MCP_TOKEN" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
  | grep -q '"serverInfo"' || { echo "FAIL: MCP initialize did not return serverInfo"; exit 1; }

TOOLS="$(curl -s -X POST "$MCP_URL" -H "authorization: Bearer $MCP_TOKEN" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}')"
for tool in search_capabilities execute_capability; do
  printf '%s' "$TOOLS" | grep -q "\"$tool\"" || { echo "FAIL: tools/list is missing $tool"; exit 1; }
done

curl -s -o /dev/null -w '%{http_code}' -X POST "$MCP_URL" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/list"}' | grep -q 401 \
  || { echo "FAIL: MCP endpoint served a request with no token"; exit 1; }

# The engine reads the index, then one body per entry, matching on uri.
INDEX="$(curl -s -X POST "$MCP_URL" -H "authorization: Bearer $MCP_TOKEN" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"resources/read","params":{"uri":"skill://index.json"}}')"
printf '%s' "$INDEX" | grep -q "skill-md" || { echo "FAIL: skill index has no skill-md entries: $INDEX"; exit 1; }

FIRST_SKILL="$(printf '%s' "$INDEX" | grep -o 'skill://[a-z0-9-]*/SKILL.md' | head -1)"
[ -n "$FIRST_SKILL" ] || { echo "FAIL: no skill url in the index"; exit 1; }
BODY="$(curl -s -X POST "$MCP_URL" -H "authorization: Bearer $MCP_TOKEN" -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"resources/read\",\"params\":{\"uri\":\"$FIRST_SKILL\"}}")"
printf '%s' "$BODY" | grep -q "\"uri\":\"$FIRST_SKILL\"" \
  || { echo "FAIL: skill body did not echo its uri, the reader matches on it"; exit 1; }
printf '%s' "$BODY" | grep -q 'description:' || { echo "FAIL: skill body has no frontmatter"; exit 1; }

curl -s -X POST "$MCP_URL" -H "authorization: Bearer $MCP_TOKEN" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":6,"method":"resources/read","params":{"uri":"skill://../../etc/passwd/SKILL.md"}}' \
  | grep -q '32002' || { echo "FAIL: path traversal was not rejected"; exit 1; }

# Branding + policy must survive the desktop's strict normalizer, which drops
# any unknown key, a non-enum accent colour, or a non-URL brand asset.
CONFIG="$(curl -s "$BASE/api/den/v1/me/desktop-config" -H "authorization: Bearer $TOKEN")"
printf '%s' "$CONFIG" | grep -q '"brandAccentColor":"mint"' \
  || { echo "FAIL: accent colour missing or not a Radix family: $CONFIG"; exit 1; }
printf '%s' "$CONFIG" | grep -q '"blockedCommands"' || { echo "FAIL: no execution policy"; exit 1; }

for asset in logo.svg icon.svg; do
  TYPE="$(curl -s -o /dev/null -w '%{content_type}' "$BASE/brand/$asset")"
  [ "$TYPE" = "image/svg+xml" ] || { echo "FAIL: $asset served as '$TYPE', not image/svg+xml"; exit 1; }
done
curl -s -o /dev/null -w '%{http_code}' "$BASE/brand/../fake-den.mjs" | grep -q '404\|400' \
  || { echo "FAIL: brand route served a path outside the asset list"; exit 1; }

echo "PASS: mint -> exchange -> authenticated -> replay rejected -> MCP tools served -> skills published -> branded and policed"
