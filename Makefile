# alitellm-auth — all targets run inside the devtools container (no host pip/venv).
# Public target `foo` re-execs `_foo` via scripts/dev.sh unless IN_DEVTOOLS=1.
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

OWNER ?= ackstorm
IMG   ?= ghcr.io/$(OWNER)/alitellm-auth
APP_DIR := src/api
UI_DIR := src/ui

IN_DEVTOOLS ?=
define container_target
	@if [ "$(IN_DEVTOOLS)" = "1" ]; then \
		$(MAKE) --no-print-directory $(1); \
	else \
		./scripts/dev.sh $(MAKE) --no-print-directory $(1); \
	fi
endef

##@ General
.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n"} \
		/^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Setup
.PHONY: hooks
hooks: ## Install git pre-push hook
	./scripts/install-hooks.sh

.PHONY: devtools-image
devtools-image: ## Build the devtools image locally
	docker build -t ghcr.io/$(OWNER)/alitellm-auth-devtools:$$(sha256sum Dockerfile.devtools | cut -c1-12) -f Dockerfile.devtools .

##@ Dev (containerized)
# Deps install to .devdeps/ under the repo root (host-user writable)
# so -u $(id -u):$(id -g) in dev.sh does not hit root-owned site-packages.
# PYTHONPATH makes pytest and ruff importable from .devdeps.
DEVDEPS_DIR := .devdeps
PYTEST_ENV := PYTHONPATH=/app/$(DEVDEPS_DIR)

.PHONY: deps _deps
deps: ## Install project deps into the container layer
	$(call container_target,_deps)
_deps:
	uv pip install --target /app/$(DEVDEPS_DIR) --no-cache-dir "$(APP_DIR)[dev]"

.PHONY: lint _lint
lint: ## ruff check + format --check
	$(call container_target,_lint)
_lint: _deps
	cd $(APP_DIR) && $(PYTEST_ENV) ruff check . && $(PYTEST_ENV) ruff format --check .

.PHONY: fmt _fmt
fmt: ## ruff format (mutates)
	$(call container_target,_fmt)
_fmt:
	cd $(APP_DIR) && ruff check --fix . && ruff format .

.PHONY: test _test
test: ## pytest with coverage
	$(call container_target,_test)
_test: _deps
	cd $(APP_DIR) && $(PYTEST_ENV) pytest tests/ -v --cov=app --cov-report=term-missing --cov-report=xml

.PHONY: test-fast _test-fast
test-fast: ## pytest quiet (inner loop / hooks)
	$(call container_target,_test-fast)
_test-fast: _deps
	cd $(APP_DIR) && $(PYTEST_ENV) pytest tests/ -q

##@ UI (containerized)
# npm runs ONLY inside the devtools container (BUILD-01) — no host node. Both
# targets reuse the container_target macro like deps/lint/test do. `_build-ui`
# is non-interactive and needs no published port, so it runs under the default
# scripts/dev.sh invocation. `dev-ui` runs the Vite HMR server and DOES need the
# host to reach :5173 and the container to reach the host FastAPI on :8080, so it
# sets DEV_NET=host (see scripts/dev.sh) to share the host network.

# The devtools container runs as the host UID/GID (dev.sh `-u`), which has no
# home dir, so npm's default cache (/.npm) is unwritable. Pin it to a repo-local,
# host-writable, gitignored path so npm ci works under the arbitrary UID.
NPM_CACHE := /app/.npm-cache

.PHONY: build-ui _build-ui
build-ui: ## Build the SPA to src/ui/dist (containerized)
	$(call container_target,_build-ui)
_build-ui:
	cd $(UI_DIR) && npm_config_cache=$(NPM_CACHE) npm ci && npm run build

.PHONY: test-ui _test-ui
.PHONY: test-plugin
test-plugin: ## OpenCode auth plugin self-check (host node, no deps)
	node --test test/opencode-auth.test.mjs

test-ui: ## Run the UI vitest suite (containerized)
	$(call container_target,_test-ui)
_test-ui:
	cd $(UI_DIR) && npm_config_cache=$(NPM_CACHE) npm ci && npm test

.PHONY: dev-ui _dev-ui
dev-ui: ## Vite dev server on :5173, proxies /api -> :8080 (containerized, host net)
	DEV_NET=host $(call container_target,_dev-ui)
_dev-ui:
	cd $(UI_DIR) && npm_config_cache=$(NPM_CACHE) npm ci && npm run dev -- --host 0.0.0.0

##@ Security (host docker — secret scanning)
.PHONY: secrets
secrets: ## gitleaks + trufflehog over the working tree
	docker run --rm -v "$(CURDIR):/repo:ro" zricethezav/gitleaks:latest \
		detect --source=/repo --redact --no-banner --config=/repo/.gitleaks.toml
	docker run --rm -v "$(CURDIR):/pwd:ro" trufflesecurity/trufflehog:latest \
		git file:///pwd --only-verified --fail --no-update

##@ Docs (containerized)
.PHONY: docs-build _docs-build
docs-build: ## mkdocs build --strict
	$(call container_target,_docs-build)
_docs-build:
	mkdocs build --strict

.PHONY: docs-serve
docs-serve: ## Live docs preview on :8000
	./scripts/dev.sh mkdocs serve -a 0.0.0.0:8000

##@ E2E
.PHONY: e2e
e2e: ## Run full e2e stack (compose up -> assertions -> teardown) -- runs on host, not in devtools
	./scripts/e2e.sh

##@ Verify
.PHONY: verify
verify: lint test secrets ## Full local gate (mirror of pre-push)

##@ Build / Release
.PHONY: build-image
build-image: ## Build the runtime container image
	docker build -t $(IMG):dev -f Dockerfile .

.PHONY: release-bump
release-bump: ## Bump version everywhere (VERSION=X.Y.Z)
	@test -n "$(VERSION)" || { echo "VERSION required"; exit 1; }
	sed -i -E 's/^version = ".*"/version = "$(VERSION)"/' $(APP_DIR)/pyproject.toml
	sed -i -E 's/(version=")[^"]*(")/\1$(VERSION)\2/' $(APP_DIR)/app/main.py
	@# Helm chart: SemVer version (bare), appVersion + image tag (v-prefixed, matches the image)
	sed -i -E 's/^version: .*/version: $(VERSION)/' deploy/helm/alitellm-auth/Chart.yaml
	sed -i -E 's/^appVersion: .*/appVersion: v$(VERSION)/' deploy/helm/alitellm-auth/Chart.yaml
	sed -i -E 's/^  tag: .*/  tag: "v$(VERSION)"/' deploy/helm/alitellm-auth/values.yaml
	@# Promote the [unreleased] CHANGELOG section to this version (CR-02) so release.yml
	@# can extract version-specific notes. Leaves a fresh empty [unreleased] on top.
	today=$$(date +%F); \
	sed -i -E "0,/^## \[unreleased\].*/s||## [unreleased]\n\n## [$(VERSION)] - $$today|" CHANGELOG.md

.PHONY: release-cut
release-cut: ## Tag-trigger a release (VERSION=X.Y.Z) -- empty commit on main
	@test -n "$(VERSION)" || { echo "VERSION required"; exit 1; }
	@test "$$(git rev-parse --abbrev-ref HEAD)" = "main" || { echo "must be on main"; exit 1; }
	@git diff --quiet || { echo "dirty tree"; exit 1; }
	./scripts/release-check.sh $(VERSION)
	git commit --allow-empty -m "chore(release): v$(VERSION)"
	./scripts/pre-push-check.sh
	git push origin main

##@ Deploy (host helm)
.PHONY: helm-lint
helm-lint: ## helm lint the chart
	helm lint deploy/helm/alitellm-auth

.PHONY: helm-template
helm-template: ## render the chart to stdout
	helm template alitellm-auth deploy/helm/alitellm-auth

.PHONY: helm-package
helm-package: ## package the chart into dist/
	helm package deploy/helm/alitellm-auth -d dist/
