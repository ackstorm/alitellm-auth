#!/usr/bin/env bash
# Fail loudly when the version files are out of lockstep with the version being
# released. Guards against `make release-cut` without `make release-bump` first:
# the chart then ships with the PREVIOUS image.tag and the cluster silently keeps
# running the old image (bit us on v0.7.2). Never auto-fix — a self-healing
# release hides that someone skipped a step.
#
# Usage: scripts/release-check.sh X.Y.Z
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

V="${1:?usage: $0 X.Y.Z}"
CHART=deploy/helm/alitellm-auth/Chart.yaml
VALUES=deploy/helm/alitellm-auth/values.yaml
PYPROJECT=src/api/pyproject.toml
MAIN=src/api/app/main.py

# Same anchors `make release-bump` writes through (Makefile). Keep them in sync.
chart_ver=$(sed -nE 's/^version: *(.*)$/\1/p' "$CHART")
chart_app=$(sed -nE 's/^appVersion: *(.*)$/\1/p' "$CHART")
img_tag=$(sed -nE 's/^  tag: *"?([^"]*)"?$/\1/p' "$VALUES")
py_ver=$(sed -nE 's/^version = "(.*)"$/\1/p' "$PYPROJECT")
app_ver=$(sed -nE 's/.*version="([^"]*)".*/\1/p' "$MAIN")

rc=0
check() { # check <label> <actual> <expected>
  if [ "$2" != "$3" ]; then
    echo "RELEASE CHECK FAIL: $1 is '$2', releasing v$V (expected '$3')" >&2
    rc=1
  fi
}
check "$CHART version"    "$chart_ver" "$V"
check "$CHART appVersion" "$chart_app" "v$V"
check "$VALUES image.tag" "$img_tag"   "v$V"
check "$PYPROJECT version" "$py_ver"   "$V"
check "$MAIN FastAPI version" "$app_ver" "$V"

[ "$rc" -eq 0 ] || { echo "run 'make release-bump VERSION=$V' and commit BEFORE 'make release-cut'" >&2; exit 1; }
echo "release check OK: all version files at $V"
