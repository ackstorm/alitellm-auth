// state.js — pure shell state machine for the alitellm-auth SPA.
//
// `resolveState(status, hasLoaded)` maps an HTTP status (or `null` while the
// first /api/session/me call is in flight, or `0` for a network failure) plus
// the module-level `hasLoaded` flag to exactly one of the five shell states
// defined in 09-UI-SPEC §"Loading Sequence" / §"Interaction Contracts":
//
//   loading | signin | authed | error | expired
//
// This function is PURE — it touches no browser globals and no I/O. It runs in
// the default vitest node environment with no jsdom, so the shell's branching
// logic is unit-testable independently of a live backend (D-02).
//
// Mapping (UI-SPEC §Loading Sequence steps 1-6):
//   null            -> loading  (in flight, before the first response resolves)
//   200             -> authed   (render the authenticated shell; caller sets hasLoaded)
//   401 & !hasLoaded -> signin  (cold load: render the sign-in landing, NO redirect)
//   401 &  hasLoaded -> expired (mid-session: silent redirect to /api/oauth/login)
//   anything else    -> error   (4xx/5xx and 0 = network failure -> error card)
export function resolveState(status, hasLoaded) {
  if (status === null || status === undefined) {
    return "loading";
  }
  if (status === 200) {
    return "authed";
  }
  if (status === 401) {
    return hasLoaded ? "expired" : "signin";
  }
  // 0 (network failure), 4xx, 5xx, and any other status -> error card.
  return "error";
}
