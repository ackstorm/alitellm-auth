// router.js — tiny client-side HASH router for the alitellm-auth SPA.
//
// Per 09-UI-SPEC §D ("SPA router" row) + 10-CONTEXT D-07: hash routing ONLY —
// NO History API, NO server catch-all (the 09-03 StaticFiles mount is
// untouched). Hash fragments are never sent in the HTTP request, so route
// changes never hit the server.
//
// Two routes (09-UI-SPEC §B "Hash router" table):
//   #/        -> "dashboard"  (Phase 10 fills the slot; Phase 9 reserves it)
//   #/stats   -> "stats"      (reserved Coming-soon placeholder; Phase 12, D-10)
//
// resolveRoute() is an ALLOW-LIST (threat T-09-13): it maps only the two known
// hashes and falls back to the default "dashboard" for ANY other / unknown /
// attacker-supplied hash. The hash never becomes a redirect target and is never
// used to drive a navigation.

import { useState, useEffect } from "preact/hooks";

// The known-hash -> route-name map. The only two routes this phase ships.
export const ROUTES = {
  "#/": "dashboard",
  "#/stats": "stats",
};

const DEFAULT_ROUTE = "dashboard";

// resolveRoute(hash) -> "dashboard" | "stats" (PURE).
//
// Touches no browser globals and no I/O — runs in the default vitest node env so
// the route-resolution logic is unit-tested independently of the DOM. Normalizes
// an empty hash / bare "#" / "#/" to the default, maps "#/stats" to "stats", and
// falls back to the default for any unknown hash.
export function resolveRoute(hash) {
  // Empty / bare "#" -> the default dashboard (first load has no hash).
  if (!hash || hash === "#" || hash === "#/") {
    return DEFAULT_ROUTE;
  }
  // Allow-list lookup; unknown hashes can never select an unknown view.
  return ROUTES[hash] || DEFAULT_ROUTE;
}

// useHashRoute() — Preact hook returning the current resolved route name.
//
// Initializes from window.location.hash, subscribes to the "hashchange" event
// on mount, and removes the listener on unmount. This hook is the ONLY part of
// the module that reaches into a browser global; resolveRoute above stays pure.
export function useHashRoute() {
  const [route, setRoute] = useState(() => resolveRoute(window.location.hash));

  useEffect(() => {
    const onHashChange = () => setRoute(resolveRoute(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    // Re-sync once on mount in case the hash changed before the listener bound.
    onHashChange();
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return route;
}
