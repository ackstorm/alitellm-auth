#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
./scripts/dev.sh make _lint
./scripts/dev.sh make _test-fast
