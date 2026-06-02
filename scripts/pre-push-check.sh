#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
EXPECTED_REMOTE="git@github.com:ackstorm/alitellm-auth.git"
fail() { echo "PRE-PUSH FAIL: $*" >&2; exit 1; }

# 1. gitleaks
docker run --rm -v "$PWD:/repo:ro" zricethezav/gitleaks:latest \
  detect --source=/repo --redact --no-banner --config=/repo/.gitleaks.toml || fail "gitleaks"

# 2. trufflehog (verified secrets only — pre-push only per D-03)
docker run --rm -v "$PWD:/pwd:ro" trufflesecurity/trufflehog:latest \
  git file:///pwd --only-verified --fail --no-update || fail "trufflehog"

# 3. large files (>2MB tracked)
while IFS= read -r -d '' f; do
  sz=$(stat -c%s "$f"); [ "$sz" -gt 2097152 ] && fail "large file $f ($sz B)"
done < <(git ls-files -z)

# 4. sensitive filenames
git ls-files | grep -E '(\.env$|\.pem$|\.key$|id_rsa|kubeconfig|credentials\.json)' \
  && fail "sensitive file tracked" || true

# 5. LICENSE + README present (warn-only — LICENSE is Phase 7 scope)
[ -f LICENSE ] && [ -f README.md ] || echo "WARN: LICENSE/README missing (expected at Phase 7 publish)" >&2

# 6. remote check (warn-only per D-02 until Phase 7 remote switch)
url=$(git remote get-url origin 2>/dev/null || echo "")
[ "$url" = "$EXPECTED_REMOTE" ] || echo "WARN: origin is '$url' (expected $EXPECTED_REMOTE)" >&2

# 7. SPDX headers on .py
while IFS= read -r f; do
  head -1 "$f" | grep -qx "# SPDX-License-Identifier: Apache-2.0" \
    || fail "missing SPDX header: $f"
done < <(git ls-files 'src/api/**/*.py')

# 8. lint + tests (in container)
./scripts/dev.sh make _lint || fail "ruff"
./scripts/dev.sh make _test-fast || fail "pytest"

echo "pre-push: all gates passed."
