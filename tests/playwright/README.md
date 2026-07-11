# tests/playwright

Ad-hoc browser scripts for eyeballing the `/ui` console against the **local dev
stack** end-to-end (login → route → screenshot). Not part of CI — a fast manual
loop for verifying UI changes render with real API data.

## Prerequisites

1. Dev stack up:
   ```bash
   docker-compose -f docker-compose.dev.yml up
   ```
   → UI at http://localhost:5173/ui/ (mock OIDC + mock LiteLLM behind it).

2. Playwright + Chromium. These live in the `playwright-skill` (not a repo
   dependency); the skill's `run.js` resolves `playwright` and launches Chromium.

## Login flow (why these scripts are short)

`docker/mock-oidc` runs with `interactiveLogin: false`, so it auto-authenticates
as `alice@example.com`. Hitting `GET /api/oauth/login` completes the whole OIDC
round-trip server-side and redirects back to `/ui` with a valid session cookie —
no username/password form to automate. `screenshot.js` just drives that and then
navigates to a hash route.

## Usage

`run.js` requires an ABSOLUTE script path (relative paths break its module
resolution):

```bash
REPO=$(git rev-parse --show-toplevel)
cd "$REPO/.claude/skills/playwright-skill"
node run.js "$REPO/tests/playwright/screenshot.js"                              # → /tmp/ui-shot.png (#/stats)
PW_ROUTE='#/keys' PW_OUT=/tmp/keys.png node run.js "$REPO/tests/playwright/screenshot.js"
```

Env vars: `PW_BASE` (default `http://localhost:5173`), `PW_ROUTE` (default
`#/stats`), `PW_OUT` (default `/tmp/ui-shot.png`), `PW_W`/`PW_H` (viewport).

## Note on `network_mode: service:auth`

The `ui` container shares the `auth` container's network namespace, so if you
`docker restart` the `auth` container you must also restart `ui` (its `:5173`
publish is torn down with auth's netns):

```bash
docker restart alitellm-auth-auth-1 alitellm-auth-ui-1
```
