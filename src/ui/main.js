// Placeholder shell entry — REPLACED by Plan 09-02.
//
// Plan 09-01 scaffolds a buildable Vite project, but `index.html` references
// `./main.js` as the module entry. Vite's build fails if this file is absent, and
// later plans (09-04 Dockerfile `ui-builder` / CI `build-ui`) require `npm run build`
// to succeed against this scaffold. This minimal stub keeps the scaffold buildable.
//
// Plan 09-02 overwrites this file with the real shell state machine (loading /
// sign-in landing / authenticated / error states) consuming GET /api/session/me
// via an apiFetch wrapper. Do NOT add shell logic here — it belongs to Plan 02.
const root = document.getElementById("app");
if (root) {
  root.textContent = "alitellm-auth — scaffold (shell pending Plan 02)";
}
