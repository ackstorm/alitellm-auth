# Brand-neutral product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Size**: ~55 files, mostly mechanical text/data edits; a small API field and one
> How-To section rewrite. Execute INLINE, one review at the end. Run on a branch or
> worktree created from the CURRENT local `main` (`git worktree add … main`), not
> from `origin/main` defaults, and do not leave the tree dirty between tasks.

**Goal:** The product can be resold: nothing a user, operator or reader of the chart/docs sees says "ackstorm"/"ACKstorm"/"Izertis", except ownership/provenance and the wire schema. Includes spec T8 (the How-To's OpenCode section moves to the plugin install).

**Architecture:** User-visible names come from settings already in place (`PROVIDER_NAME`, `brand`, `brand_short`, `APP_BASE_URL`, `API_PUBLIC_URL`); `/api/config` gains `provider_name` so the SPA can print `opencode auth login -p <provider>`. Examples use `example.com` hosts and a `<model>` placeholder. Test data uses neutral model names.

**Tech Stack:** FastAPI, React/Vite/Vitest (npm ONLY inside the devtools container: `make test-ui`, `make build-ui`), Helm, Python stdlib CLI.

## Decisions (owner, 2026-09-28) — do not re-litigate

- **Keep** ownership/provenance: `github.com/ackstorm/...`, `ghcr.io/ackstorm/...` (image repos in `values.yaml`), `NOTICE` (copyright, Apache requires it), `.github/CODEOWNERS`, `MAINTAINERS.md`, `SECURITY.md` contact, Chart.yaml `home`/`sources`/`maintainers`, `authz/go.mod` module path, `Makefile`/`scripts/dev.sh` `OWNER`, `release.yml` comments, `mkdocs.yml` `repo_url`.
- **Keep** the wire schema string `ackstorm.opencode-config/1` (shared with ACH, not user-visible).
- **Keep** dated historical reports `docs/reports/*.html` and `CHANGELOG.md` history (records, not product text).
- `clients/ackstorm-token` → **`clients/genai-token`**.
- How-To model examples: **neutral placeholder `<model>`** (no backend call added).
- Chart defaults: **`example.com`** hosts.
- Neutral replacements: hosts `platform.example.com`, `api.example.com`, `auth.example.com`/`dex.example.com`, `litellm.example.com`, `chat.example.com`; model names in tests/mock/examples `acme.fast`, `acme.smart`, `acme.router`, `acme.lite`; org/brand text "the platform" or the `brand`/`provider_name` setting.

## Acceptance (the gate for the whole plan)

```bash
git grep -il "ackstorm\|izertis" -- . \
  ':!NOTICE' ':!.github/CODEOWNERS' ':!MAINTAINERS.md' ':!SECURITY.md' ':!CHANGELOG.md' \
  ':!docs/reports' ':!docs/superpowers' ':!authz/go.mod' ':!mkdocs.yml' ':!.github/workflows'
```

prints only files whose remaining matches are provenance or the schema. Check each remaining line with
`git grep -in "ackstorm\|izertis" -- <file>`; allowed patterns: `github.com/ackstorm`, `ghcr.io/ackstorm`,
`ackstorm.opencode-config/1`, `OWNER ?= ackstorm`, `GITHUB_REPOSITORY_OWNER:-ackstorm`, Chart.yaml
`name: ACKstorm` under `maintainers`. Anything else is a miss.

---

### Task 1: API — `provider_name` in `/api/config`, neutral comments

**Files:** `src/api/app/public.py`, `src/api/app/config.py`, `src/api/app/session.py`, `src/api/tests/test_public.py`, `src/ui/src/lib/api-types.ts`, `src/ui/src/stores/config.ts` (+ its test)

- [ ] **Step 1: Failing test** — in `tests/test_public.py`, next to the existing `/api/config` tests (reuse their client/settings factory):

```python
def test_public_config_exposes_provider_name(...):  # same fixture args as the neighbouring /api/config test
    resp = client.get("/api/config")
    assert resp.json()["provider_name"] == "ai-platform"
```

and a variant with `provider_name="acme"` in the settings → `"acme"`.

- [ ] **Step 2: Implement** — `public.py` `payload` gains `"provider_name": settings.provider_name,` (after `brand_short`). `api-types.ts` `AppConfig` gains `provider_name: string;`. `stores/config.ts` `DEFAULT_CONFIG` gains `provider_name: 'ai-platform',`; update `stores/config.test.ts` expectations that compare the whole default object.
- [ ] **Step 3: Comments** — `config.py:90` example broker URL → `https://api.example.com/aws-eks-ro-callback`; `session.py:125` → `platform.example.com.evil.com prefix attack`. `opencode_config.py` / `clients/opencode/index.mjs` keep the schema string only.
- [ ] **Step 4:** `cd src/api && .venv/bin/pytest tests/test_public.py -q` green; `make test-ui` green for the store test.

---

### Task 2: Test data and the LiteLLM mock

**Files:** `src/api/tests/{test_opencode_config,test_session,test_openwork,test_stats,test_litellm_client,test_auth,test_config,test_skills,test_public}.py`, `src/api/tests/fixtures/{spend_logs_rows,daily_activity_current}.json`, `docker/mock-litellm/app.py` (+ its `fixtures/` if they match), `test/opencode-config-hook.test.mjs`, `src/ui/src/**/*.test.ts(x)` that match.

- [ ] Replace model names `ackstorm.<x>` → `acme.<x>`; hosts `*.ackstorm.ai` → `*.example.com`; display strings `ACKstorm <X>` → `Acme <X>`; `provider_name="ackstorm"` in tests → `"acme"`. Mechanical: `git grep -l` per file, edit, never touch the schema string.
- [ ] If a test asserts an ordering or a count that depended on the old name (e.g. sorted model lists), fix the expectation, not the code.
- [ ] `test_skills.py::test_genai_api_is_brand_neutral_by_default` stays (it asserts `ackstorm` is absent).
- [ ] Gates: full pytest (`EXIT=0`), both `node --test` files, `make test-ui`.

---

### Task 3: How-To (includes spec T8) and UI comments

**Files:** `src/ui/src/routes/HowTo.tsx`, `src/ui/src/routes/HowTo.test.tsx`, `src/ui/src/components/layout/BrandLockup.tsx`, `src/ui/src/index.css`, `src/ui/src/components/layout/SiteFooter.test.tsx`, `src/ui/src/App.test.tsx`, `src/ui/src/routes/Models.test.tsx`, `src/ui/src/lib/model-classify.test.ts`

- [ ] `MODEL_ALIAS` → `const MODEL_PLACEHOLDER = '<model>';` (rename every use; the picker keeps working: its default becomes the placeholder until the user picks a model). Header comment §1/§4 lines updated accordingly.
- [ ] **OpenCode tool entry**: first variant becomes the plugin (default selected):

```tsx
        {
          id: 'opencode-plugin',
          subLabel: 'SSO plugin',
          ready: true,
          caption: 'terminal (once)',
          // The platform's OpenCode plugin: SSO sign-in, and at every start the
          // user's models, MCP servers (disabled) and skills. No key, no env var.
          code: `opencode plugin ${apiBase}/clients/opencode/plugin -g
opencode auth login -p ${config.provider_name}`,
          note: 'Restart OpenCode afterwards. Models appear under the provider shown above; MCP servers appear disabled (enable one in opencode.json, then `opencode mcp auth <name>`). Unset OPENCODE_MODELS_URL and any exported key for this provider.',
        },
```

  (`config` from the existing config store hook used elsewhere in the SPA; add the import if HowTo lacks it). Keep `opencode-gemini` (no brand) and keep `opencode-openai` renamed `subLabel: 'API key'` with `"models": { "${MODEL_PLACEHOLDER}": { "name": "${MODEL_PLACEHOLDER}" } }` and the note "Replace <model> with a model from the Models tab."
- [ ] Every other `ackstorm.fast`/`ackstorm.smart`/`ACKstorm Fast|Smart` in snippets → `${MODEL_PLACEHOLDER}`; Codex/Qwen `name = "ACKstorm"` → `name = "${config.brand_short}"`.
- [ ] **Chat section**: the hosted card title `ACKstorm Chat` → `{config.brand_short} Chat`; the model line shows `MODEL_PLACEHOLDER`. The OpenWork card is no longer "coming soon": title `OpenWork (desktop)`, text "Settings → organization server: `<APP_BASE_URL origin>`, then sign in. Install the OpenCode plugin (above) for models and MCP servers." — use `window.location.origin` for the console origin (the SPA is served from APP_BASE_URL).
- [ ] `BrandLockup.tsx:8` comment example → `e.g. Acme`; `index.css` theme comment: "Izertis corporate skin … www.izertis.com" → neutral ("red corporate skin: white surfaces, deep navy ink, coral-red primary"), keep the colour values; `Izertis teal/gold` comments → `teal`/`gold`.
- [ ] Update `HowTo.test.tsx` (expects the plugin variant first, the placeholder, `-p <provider_name>` from config) and the other UI tests' fixtures.
- [ ] Gates: `make test-ui`, `make build-ui`.

---

### Task 4: `genai-token` CLI

**Files:** `clients/ackstorm-token` → `clients/genai-token` (`git mv`), `README.md`, `TODO.md`, any test or Dockerfile that references it (`git grep -n ackstorm-token`).

- [ ] `git mv clients/ackstorm-token clients/genai-token`.
- [ ] In the script: docstring/usage "the ACKstorm platform" → "the platform"; program name in help/usage/errors → `genai-token`; cache/state file or dir names containing `ackstorm` → `genai-token` (not distributed yet, no migration needed — say so in the CHANGELOG).
- [ ] README/TODO references → `genai-token` (`apiKeyHelper` / `auth.command` examples, `genai-token login --no-browser`).
- [ ] Smoke: `python3 clients/genai-token --help` exits 0 and prints no "ackstorm".

---

### Task 5: Chart defaults and docs

**Files:** `deploy/helm/alitellm-auth/values.yaml`, `deploy/README.md`, `README.md`, `PUBLISH.md`, `CLAUDE.md`, `TODO.md`, `docs/index.md`, `docs/dex-integration.md`, `docs/ui-review-backlog.md`, `docs/references/*.md`, `clients/opencode/README.md`, `scripts/pre-push-check.sh`, `Makefile` (non-OWNER lines only), `.github/workflows/release.yml` (comments only if they name the brand outside the "org named ACKstorm" normalisation note — that one is provenance, keep).

- [ ] `values.yaml`: `appBaseUrl: "https://platform.example.com"`, `oauthIssuerUrl: "https://dex.example.com/dex"`, `litellmUrl: "https://litellm.example.com"`, `apiPublicUrl: "https://api.example.com"`, `chatPublicUrl: "https://chat.example.com"`, `ingress.host: platform.example.com`, `istio.host: "api.example.com"`, broker examples → `api.example.com`; the `providerName` comment "the ACKstorm cluster sets \"ackstorm\" in gitops" → "the deployment sets it from its platform config (e.g. Terraform → Flux)". Image `repo:` lines stay (provenance). Verify `helm template deploy/helm/alitellm-auth` renders and gitops is unaffected (it sets every one of these values — check `apps/alitellm-auth/base/helm.yaml` in `/workspace/private/ackstorm/nglz-genai/gitops-genai-blueprint` sets appBaseUrl, oauthIssuerUrl, litellmUrl, apiPublicUrl, chatPublicUrl (if used), ingress/istio hosts; list any it does NOT set and STOP to ask before changing that default).
- [ ] Docs: example hosts → `example.com`, model names → `acme.*`, "ACKstorm" as the product/deployment → "the platform" / "your deployment". `CLAUDE.md`: remove the `OPENCODE_MODELS_URL` / `/public/opencode/api.json` guidance (Public Static Artifacts section: the mount stays generic, but nothing is served by default now; gitops no longer mounts the catalog), curl examples → `api.example.com`; keep `github.com/ackstorm` links.
- [ ] `docs/references/release-process.md`, `openwork-*.md`: neutralise examples; keep repo/registry links.
- [ ] `clients/opencode/README.md`: the one remaining match → neutral.

---

### Task 6: Gates, review, release

- [ ] Acceptance grep (top of this plan) — only provenance/schema lines remain.
- [ ] Full pytest `EXIT=0`, ruff 0.8.4 check + format, both `node --test`, `make test-ui`, `make build-ui`, `helm template`.
- [ ] CHANGELOG `[unreleased]` → `### Changed`:

```markdown
- **Brand-neutral product.** Nothing user-facing names a specific company:
  the How-To reads the platform name from `/api/config` (`provider_name`,
  `brand_short`) and uses a `<model>` placeholder; its OpenCode section now
  shows the SSO plugin install (`opencode plugin <api>/clients/opencode/plugin -g`
  + `opencode auth login -p <provider>`), and the OpenWork card explains how to
  join the organization. Chart defaults use `example.com` hosts (deployments
  that set these values, like any GitOps install, are unaffected).
  `clients/ackstorm-token` is renamed `clients/genai-token` (not distributed
  yet: no migration). Ownership/provenance (repository, registry, NOTICE)
  is unchanged.
```

- [ ] One review, commit(s) after user approval; release as `0.20.0` (the `/api/config` field is additive; `feat`-level How-To change).
