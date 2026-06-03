#!/usr/bin/env bash
# Run any command inside the content-addressed devtools container.
# No host pip/venv — this is the single entrypoint for all tooling.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OWNER="${GITHUB_REPOSITORY_OWNER:-ackstorm}"
HASH="$(sha256sum Dockerfile.devtools | cut -c1-12)"
IMAGE="ghcr.io/${OWNER}/alitellm-auth-devtools:${HASH}"

# Pull the published image; fall back to a local build if unavailable.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  if ! docker pull "$IMAGE" >/dev/null 2>&1; then
    echo "dev.sh: building devtools image $IMAGE locally..." >&2
    docker build -t "$IMAGE" -f Dockerfile.devtools .
  fi
fi

# Networking: the default invocation publishes NO ports and uses the container's
# own network namespace — correct for build/lint/test/_build-ui (no port needed).
# The Vite dev server (`make dev-ui`) is the ONLY caller that needs the host to
# reach :5173 AND the container to reach the host FastAPI on localhost:8080 for
# its /api proxy. That target sets DEV_NET=host, which shares the host network
# namespace so both hold on Linux without editing vite.config.js. Host networking
# is broader than port-publishing, so it is reserved strictly for the HMR dev loop
# and never used by the release build or CI's _build-ui.
NET_ARGS=()
if [ "${DEV_NET:-}" = "host" ]; then
  NET_ARGS+=(--network host)
fi

# uv/pytest caches persist in a named volume across runs.
# Conditional TTY: appends -t only when stdin is a real TTY (avoids CI "not a TTY" errors).
# Host UID/GID: prevents root-owned files on the mounted source tree.
exec docker run --rm -i $( [ -t 0 ] && echo "-t" ) \
  "${NET_ARGS[@]}" \
  -u "$(id -u):$(id -g)" \
  -e IN_DEVTOOLS=1 \
  -e GITHUB_REPOSITORY_OWNER="$OWNER" \
  -v "$REPO_ROOT:/app" \
  -v alitellm-auth-uvcache:/root/.cache \
  -w /app \
  "$IMAGE" "$@"
