// api.ts — typed, never-throw same-origin fetch wrapper.
//
// Ported from src/ui/api.js. `apiFetch<T>` performs a single fetch and resolves
// to `{ status, data }`:
//   - a thrown network error (offline, DNS failure, reset) maps to
//     `{ status: 0, data: null }` so callers render an error state instead of
//     producing an uncaught rejection (threat T-09-05);
//   - a body that is not valid JSON (e.g. a 401 with an empty body) maps `data`
//     to `null` while preserving the real HTTP `status`.
//
// getJson/postJson/del all REUSE apiFetch (they never bypass the single path).
// Writes ALWAYS carry `content-type: application/json` because the backend
// write-guard (session.py::assert_same_origin) returns 415 otherwise.

export interface ApiResult<T> {
  status: number;
  data: T | null;
}

export async function apiFetch<T>(
  url: string,
  options?: RequestInit,
): Promise<ApiResult<T>> {
  try {
    const resp = await fetch(url, options);
    let data: T | null = null;
    try {
      // Body may be empty (e.g. a 401 with no JSON); tolerate that.
      data = (await resp.json()) as T;
    } catch {
      data = null;
    }
    return { status: resp.status, data };
  } catch {
    // Network/fetch failure -> status 0 -> caller renders the error state.
    return { status: 0, data: null };
  }
}

export const getJson = <T>(url: string): Promise<ApiResult<T>> => apiFetch<T>(url);

export const postJson = <T>(url: string, body: unknown): Promise<ApiResult<T>> =>
  apiFetch<T>(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });

export const del = <T>(url: string): Promise<ApiResult<T>> =>
  apiFetch<T>(url, {
    method: 'DELETE',
    headers: { 'content-type': 'application/json' },
  });
