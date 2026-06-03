// api.js — same-origin fetch wrapper + the module-level `hasLoaded` flag.
//
// `apiFetch(url, options)` performs a fetch and resolves to `{ status, data }`.
// A thrown network error (offline, DNS failure, connection reset) is mapped to
// `status: 0` so the shell renders the error card instead of producing an
// uncaught promise rejection (UI-SPEC §Interaction Contracts; threat T-09-05).
//
// `hasLoaded` distinguishes a cold-load 401 (-> sign-in landing) from a
// mid-session 401 (-> silent redirect). The shell flips it to `true` only after
// a 200 render, so any later 401 is classified "expired" by resolveState().
//
// The flag is module-level mutable state owned here and read/written through
// getHasLoaded() / setHasLoaded() so the shell never reaches into module
// internals directly.

let _hasLoaded = false;

export function getHasLoaded() {
  return _hasLoaded;
}

export function setHasLoaded(value) {
  _hasLoaded = Boolean(value);
}

// For tests: reset the flag to its initial cold-load value.
export function resetHasLoaded() {
  _hasLoaded = false;
}

export async function apiFetch(url, options) {
  try {
    const resp = await fetch(url, options);
    let data = null;
    try {
      // Body may be empty (e.g. a 401 with no JSON); tolerate that.
      data = await resp.json();
    } catch {
      data = null;
    }
    return { status: resp.status, data };
  } catch {
    // Network/fetch failure -> status 0 -> resolveState maps to the error card.
    return { status: 0, data: null };
  }
}

// Thin convenience wrappers over apiFetch (they REUSE it, never bypass it) so
// the dashboard read/write paths share the single never-throw { status, data }
// contract. Writes always carry `content-type: application/json` because the
// backend write-guard (session.py assert_same_origin) returns 415 otherwise.

export function getJson(url) {
  return apiFetch(url);
}

export function postJson(url, body) {
  return apiFetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function del(url) {
  return apiFetch(url, {
    method: "DELETE",
    headers: { "content-type": "application/json" },
  });
}
