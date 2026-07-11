// screenshot.js — log into the local dev stack and screenshot any /ui route.
//
// The dev stack's mock OIDC (docker/mock-oidc, interactiveLogin:false) auto-
// authenticates as alice@example.com, so hitting /api/oauth/login round-trips
// straight back to /ui with a valid session cookie — no form to fill. This script
// drives that flow, navigates to a hash route, and writes a full-page screenshot.
// It's the fixture we use to eyeball Stats/Dashboard/etc. changes end-to-end.
//
// Run it through the playwright skill's executor (which resolves `playwright` and
// launches Chromium):
//
//   cd .claude/skills/playwright-skill && node run.js ../../tests/playwright/screenshot.js
//
// Parameters (env vars):
//   PW_BASE   base URL              (default http://localhost:5173)
//   PW_ROUTE  hash route under /ui  (default #/stats)
//   PW_OUT    output PNG path       (default /tmp/ui-shot.png)
//   PW_W/PW_H viewport w/h          (default 1440 x 2400)
//
// Prereq: the dev stack is up — `docker-compose -f docker-compose.dev.yml up`.

const { chromium } = require('playwright');

const BASE = process.env.PW_BASE || 'http://localhost:5173';
const ROUTE = process.env.PW_ROUTE || '#/stats';
const OUT = process.env.PW_OUT || '/tmp/ui-shot.png';
const W = Number(process.env.PW_W) || 1440;
const H = Number(process.env.PW_H) || 2400;

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: W, height: H } });

  // 1. OIDC login round-trip (mock is non-interactive → redirects back to /ui).
  //    The landing URL is /ui (no trailing slash) → Vite serves a 404 helper; that
  //    is expected and harmless, the session cookie is set regardless.
  await page.goto(`${BASE}/api/oauth/login`, {
    waitUntil: 'networkidle',
    timeout: 25000,
  });

  // 2. Navigate to the target hash route and let charts settle.
  await page.goto(`${BASE}/ui/${ROUTE}`, {
    waitUntil: 'networkidle',
    timeout: 25000,
  });
  await page.waitForTimeout(2500);

  await page.screenshot({ path: OUT, fullPage: true });
  console.log(`Screenshot: ${OUT} (route ${ROUTE})`);

  await browser.close();
})();
