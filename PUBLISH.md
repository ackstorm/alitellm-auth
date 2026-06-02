# PUBLISH — making this repo public

Authoritative checklist for pushing **alitellm-auth** to its public
GitHub home at `git@github.com:ackstorm/alitellm-auth.git`.

Public-repo publication is **irreversible**: once a commit is pushed,
assume it is permanently indexed by mirrors, search engines, and training
corpora — even if the repo is later deleted or made private. The
procedure below exists so we catch leaks, large binaries, and internal
references *before* that happens.

---

## TL;DR

```bash
# from repo root
make hooks                                                # install git pre-push hook (once)
./scripts/pre-push-check.sh                               # must exit 0 (gates 1-8)

# MANUAL USER ACTION (D-05) — run only when ready to publish:
git remote set-url origin git@github.com:ackstorm/alitellm-auth.git
git push -u origin main
```

---

## Prerequisites

Before running the pre-push check or pushing, confirm:

- **Docker** running and reachable by the current user (gates 1 and 2 use sandboxed secret scanners).
- **SSH key** on this machine with push access to the `ackstorm` GitHub org.
- **Working tree** committed — uncommitted changes are not pushed; the script warns about them.
- **PREREQUISITE: Create GitHub team `@ackstorm/alitellm-auth-maintainers` in the `ackstorm` org**
  before pushing, or `.github/CODEOWNERS` will silently no-op (CODEOWNERS rules only take effect
  when the referenced team exists on the org).
  - Path: **Org Settings → Teams → New team → slug: `alitellm-auth-maintainers`**
  - This is a D-03 executor note (from the Phase 7 context). Add Juan Carlos Moreno as a member.

---

## The 8 gates

`scripts/pre-push-check.sh` runs 8 checks. Any failure blocks the push.

| # | Check | Block reason |
|---|-------|-------------|
| 1 | **gitleaks** (full repo, `.gitleaks.toml` allowlist) | API keys, tokens, high-entropy strings. |
| 2 | **trufflehog `--only-verified`** | Confirms suspected secrets are actually live/valid. |
| 3 | **Large tracked files (>2 MB)** | Public repos amplify accidental binary commits. |
| 4 | **Sensitive filename patterns** | `.env`, `*.pem`, `*.key`, `id_rsa`, `kubeconfig`, `credentials.json`. |
| 5 | **LICENSE + README.md present** | Required for any public OSS repo. |
| 6 | **`origin` remote matches `git@github.com:ackstorm/alitellm-auth.git`** | **Warn-only** until the manual remote switch (D-05). Will print a `WARN:` message but not block. |
| 7 | **SPDX headers on `src/api/**/*.py`** | Every tracked Python source must carry `# SPDX-License-Identifier: Apache-2.0` as its first line. |
| 8 | **ruff lint + pytest** (inside devtools container via `dev.sh`) | All code-quality gates must pass. |

Gate 6 is intentionally warn-only until the user executes the manual remote switch below
(Phase 6 decision D-02). All other gates are hard failures.

If a hard check fails:
- **Leak detected**: rotate the credential first, then remove from history with `git filter-repo` — `git rm` alone is not enough.
- **Large file**: `git rm` + `git filter-repo --strip-blobs-bigger-than 2M`.
- **Sensitive filename**: `git rm --cached <file>`, add to `.gitignore`, commit, rewrite history if it existed in earlier commits.
- **Wrong `origin`**: `git remote set-url origin git@github.com:ackstorm/alitellm-auth.git`.

After any history rewrite, re-run the script from scratch.

---

## MANUAL USER ACTION — remote switch and first push (D-05)

**Phase 7 stops here.** The automation has verified the repo is ready. The following
commands are your manual action — they are intentionally NOT executed by the automation:

```bash
# Switch the remote from internal GitLab to public GitHub:
git remote set-url origin git@github.com:ackstorm/alitellm-auth.git

# Push (gate 6 will now pass cleanly):
git push -u origin main
```

After the push, sanity-check on GitHub: README renders, LICENSE detected, no large blobs
flagged, no Dependabot or secret-scanning alerts waiting in the Security tab.

---

## First publication — flatten history into one Initial commit

**This section applies once, before the very first push.** Skip it on every subsequent push.

The private development history of this repo contains commit messages with detailed internal
commentary — planning IDs, audit paths, internal product names, and other context written for
the team, not the public. Once pushed, those messages are permanent. The recommended first
publication is therefore a **single fresh "Initial commit"** built from the current tree,
with internal paths excluded.

### Paths to exclude from the public repo

The orphan flatten removes the following from the working tree before the initial commit.
Re-add to `.gitignore` so they stay out:

| Path | Why exclude |
|------|------------|
| `.planning/` | GSD planning artifacts — ROADMAP, STATE, audits, phases, notes, intel, graphs |
| `docs/plans/` | Dated phase implementation plans (internal) |
| `.claude/` | Claude Code worktree state (already gitignored) |

### Procedure

```bash
# 0. Be on main, working tree clean.
git checkout main
git status   # must show "nothing to commit"

# 1. Safety net — full private history kept locally.
git branch backup-pre-public-flatten

# 2. Remove internal paths from the tree and ignore them going forward.
git rm -r .planning docs/plans
printf '\n.planning/\ndocs/plans/\n' >> .gitignore
git add .gitignore
# (note: .claude/ is already gitignored — no need to add it)

# 3. Create the single Initial commit on an orphan branch.
git checkout --orphan tmp-public
git add -A
git commit -m "Initial commit"

# 4. Replace main with the flattened branch.
git branch -D main
git branch -m tmp-public main

# 5. Re-run the pre-push validation against the new single-commit history.
./scripts/pre-push-check.sh

# 6. Switch remote and push. The remote has no main yet, so this is a normal push, not a force.
git remote set-url origin git@github.com:ackstorm/alitellm-auth.git
git push -u origin main
```

### After the flatten

- Old commits live in local `.git` until garbage collection reaches them
  (kept alive by `backup-pre-public-flatten` for as long as that branch exists). To purge:
  `git branch -D backup-pre-public-flatten && git gc --aggressive --prune=now`.
- From this point on, every push follows the standard procedure using `./scripts/pre-push-check.sh`.

---

## Branch protection — required CI checks

Once published, the `main` branch protection rule should require these CI checks before
merge. Apply via the GitHub web UI:

    Repo Settings → Branches → Branch protection rule → "main" → Require status checks

| Job name | Workflow file | Purpose |
|----------|---------------|---------|
| `lint` | `ci.yml` | ruff check + format |
| `test` | `ci.yml` | pytest + coverage |
| `secrets` | `ci.yml` | gitleaks scan |
| `build-test` | `docs.yml` | mkdocs build --strict on PRs |

Optional but recommended:
- Require pull-request reviews before merge.
- Dismiss stale pull-request approvals when new commits are pushed.
- Restrict who can dismiss pull-request reviews.
- Require signed commits.

Branch-protection rules require admin scope beyond what `GITHUB_TOKEN` carries; they are
applied by a human via the web UI, not via the API.

---

## Release flow

For every release after the initial push:

1. **Prepend a CHANGELOG entry** under a new `## [X.Y.Z]` section.
2. **Bump version everywhere:**
   ```bash
   make release-bump VERSION=X.Y.Z
   ```
   This rewrites: `src/api/pyproject.toml` version field, `src/api/app/main.py` version,
   the Helm chart (`deploy/helm/alitellm-auth/Chart.yaml` version + appVersion and
   `values.yaml` image tag), the Kustomize example overlay image tag
   (`deploy/kustomize/overlays/example/kustomization.yaml`), and promotes the CHANGELOG
   `[unreleased]` section to `[X.Y.Z]`.
3. **Commit the bumped files:** `git add src/api/pyproject.toml src/api/app/main.py deploy/ CHANGELOG.md && git commit -m "chore: bump to vX.Y.Z"`
4. **Trigger the release pipeline:**
   ```bash
   make release-cut VERSION=X.Y.Z
   ```
   This creates an empty marker commit `chore(release): vX.Y.Z`, runs `pre-push-check.sh`,
   and pushes to `origin main`. The push fires `release.yml` which:
   - Builds the multi-arch image (`linux/amd64` + `linux/arm64`) with `docker buildx`.
   - Pushes to `ghcr.io/ackstorm/alitellm-auth:vX.Y.Z` and `:latest`.
   - Packages + pushes the Helm chart to `oci://ghcr.io/ackstorm/charts/alitellm-auth:X.Y.Z`.
   - Creates a GitHub Release with notes extracted from `CHANGELOG.md`.
