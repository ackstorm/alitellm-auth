# Release Process

**DO NOT hand-roll a release. A GitHub Actions pipeline owns it. In particular,
NEVER `git tag` / `git push --tags` by hand.**

## How the pipeline works

`.github/workflows/release.yml` runs on **every push to `main`** and executes the
release job **only** when the head commit message starts with `chore(release): v`
(the release marker).

In order, that job:

1. Builds + pushes the multi-arch Docker image to
   `ghcr.io/ackstorm/alitellm-auth:v<X.Y.Z>` (and `:latest`).
2. Packages + pushes the Helm chart as an OCI artifact to
   `oci://ghcr.io/ackstorm/charts` (chart version = bare SemVer, appVersion = `v<X.Y.Z>`).
3. **Pushes the `v<X.Y.Z>` git tag itself** (idempotent — skips if the tag already exists).
4. Creates the GitHub Release, using the version-specific `CHANGELOG.md` section as notes.

## The canonical flow

Let CI do everything — you only produce the bump + the marker commit:

```bash
# 1. Feature work is already merged to main (normal feat/fix PRs).

# 2. Bump EVERY version file + promote the CHANGELOG [unreleased] section.
#    release-bump edits files but does NOT commit.
make release-bump VERSION=0.5.33
git commit -am "chore(release): bump version to 0.5.33"

# 3. Marker commit that triggers CI (an empty commit is fine).
make release-cut VERSION=0.5.33      # git commit --allow-empty -m "chore(release): v0.5.33"

# 4. Push — CI fires and produces the image, chart, tag, and GitHub Release.
git push origin main
```

The two commits may also be folded into one `chore(release): v<X.Y.Z>` commit that
carries the bump — the marker prefix is all the pipeline checks. Prefer the make
targets over editing files by hand.

## Version files (keep in lockstep — `make release-bump` is the source of truth)

`make release-bump VERSION=X.Y.Z` (in the Makefile) is authoritative for **which
files carry the version**. Never edit these by hand:

| File | Field |
|------|-------|
| `src/api/pyproject.toml` | `version = "X.Y.Z"` |
| `src/api/app/main.py` | FastAPI `version="X.Y.Z"` — **the one most easily missed** |
| `deploy/helm/alitellm-auth/Chart.yaml` | `version: X.Y.Z` (bare SemVer) + `appVersion: vX.Y.Z` |
| `deploy/helm/alitellm-auth/values.yaml` | `tag: "vX.Y.Z"` |
| `CHANGELOG.md` | promotes `[unreleased]` → `## [X.Y.Z] - <today>`, leaves a fresh empty `[unreleased]` |

`scripts/release-check.sh X.Y.Z` verifies the first four (not CHANGELOG) and is run
by both `make release-cut` and `release.yml` — a cut without a bump fails instead of
publishing a chart that points at the previous image (see CLAUDE.md failure mode 8).

## Which bump (SemVer)

- **patch** → `fix` / `hotfix` commits
- **minor** → `feat` / `feature` commits
- **major** → a commit body containing `BREAKING CHANGE`

See the `git:ackstorm-git-guidelines` skill for the full commit/branch conventions.

## Failure mode: manual tag race (learned 2026-07-23, v0.5.33)

**Symptom:** the release run fails at the "git tag" step with
`! [rejected] v<X.Y.Z> -> v<X.Y.Z> (already exists)`; the Docker image and Helm
chart pushed fine, but **no GitHub Release** was created (the release-notes step
runs after the tag step, so it is skipped).

**Cause:** a `v<X.Y.Z>` tag was pushed by hand. The pipeline's idempotency guard is
a *local* `git rev-parse` in CI's fresh checkout, which may not yet have your
just-pushed tag, so CI still attempts `git push origin v<X.Y.Z>` and the remote
rejects it as already-existing.

**Recovery:** `gh run rerun <run-id> --failed`. On the re-run the tag already exists
on the remote, so CI's checkout fetches it, `git rev-parse` finds it, the push is
skipped, and the job proceeds to create the GitHub Release (image/chart re-push
idempotently). No need to delete the tag.

**Prevention:** never tag manually — the pipeline owns tagging.
