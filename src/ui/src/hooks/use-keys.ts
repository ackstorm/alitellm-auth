// use-keys.ts — TanStack Query hooks for the session keys lifecycle.
//
// Wraps the never-throw api wrapper (lib/api) so the query/mutation surface the
// TanStack-idiomatic isError/onSuccess states:
//
//   useKeys()       GET    /api/session/keys   -> KeyRow[] (throws on non-200 so
//                                                  the table renders its error
//                                                  branch; a 200 + empty array
//                                                  resolves to [] = empty state)
//   useCreateKey()  POST   /api/session/keys   -> CreateKeyResponse (stashes the
//                                                  one-time sk- in the in-memory
//                                                  fresh-keys store, then
//                                                  invalidates the list)
//   useDeleteKey()  DELETE /api/session/keys/{id} -> DeleteKeyResponse (drops the
//                                                  fresh key, invalidates list)
//
// Cancellation: useKeys threads TanStack Query's `{ signal }` into getJson so an
// unmount / superseding refetch aborts the in-flight fetch; apiFetch re-throws
// that AbortError (Phase-1 carry-forward), letting Query treat it as a
// cancellation instead of a fake network error. Mutations are NOT cancelled.
//
// Invalidation uses the provider's client via useQueryClient() (idiomatic), NOT
// the singleton import — so tests can inject their own client. Fresh-key actions
// are read via the store selector.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { del, getJson, postJson } from '@/lib/api';
import type {
  CreateKeyBody,
  CreateKeyResponse,
  DeleteKeyResponse,
  KeyRow,
  KeysResponse,
  MakeDefaultResponse,
} from '@/lib/api-types';
import { useFreshKeysStore } from '@/stores/fresh-keys';

/** Query key for the session keys list. Shared by the query + invalidations. */
export const KEYS_QUERY_KEY = ['session', 'keys'] as const;

/**
 * An Error carrying the backend HTTP `status` + parsed `detail`. The create-key
 * modal needs both to route a 422 field-rejection (`{ detail }`) to the matching
 * field; a 502 has no body so `detail` is null and the modal falls back to its
 * generic copy.
 */
export interface ApiCallError extends Error {
  status: number;
  detail: string | null;
}

/**
 * Build an ApiCallError from a parsed (never-throw api wrapper) response. Reads
 * `data.detail` defensively — only a string `detail` is carried, anything else
 * (or a null body, e.g. a 502) yields `detail: null`. The localized `data as ...`
 * narrowing is confined here so the response types stay un-weakened at the
 * call sites.
 */
function apiCallError(message: string, status: number, data: unknown): ApiCallError {
  const detail =
    data &&
    typeof data === 'object' &&
    'detail' in data &&
    typeof (data as { detail: unknown }).detail === 'string'
      ? (data as { detail: string }).detail
      : null;
  return Object.assign(new Error(message), { status, detail });
}

/**
 * GET /api/session/keys. Throws on a non-200 / malformed response so the query
 * lands in `isError`; a 200 with a `keys` array resolves to `KeyRow[]` (an empty
 * array is the empty state, not an error). The `{ signal }` makes cancellation
 * work end-to-end with apiFetch's AbortError re-throw.
 */
export function useKeys() {
  return useQuery({
    queryKey: KEYS_QUERY_KEY,
    queryFn: async ({ signal }): Promise<KeyRow[]> => {
      const { status, data } = await getJson<KeysResponse>('/api/session/keys', {
        signal,
      });
      if (status === 200 && data && Array.isArray(data.keys)) return data.keys;
      throw new Error('keys-load-failed');
    },
  });
}

/**
 * Derived: does the user have an explicit default key? Reads the keys query (no
 * extra fetch) and returns true iff some key carries is_default. Safe before the
 * query settles / on error — returns false (never throws). Shared by the AppShell
 * CHAT/Models/MCPs nav gating and the Models/MCP route gates (per-user catalog
 * reads are scoped to the default key via the gateway's custom auth).
 */
export function useHasDefaultKey(): boolean {
  const { data } = useKeys();
  return (data ?? []).some((k) => k.is_default);
}

/**
 * POST /api/session/keys. Backend returns HTTP 200 with { key, id, team_id }
 * (session.py::session_create_key). On success the one-time full `sk-` is stashed
 * in the in-memory fresh-keys store (never persisted; T-10-15) and the list is
 * invalidated. Guard at the hook via the `status !== 200` check — the response
 * type's `key`/`id` stay non-null (plan carry-forward).
 */
export function useCreateKey() {
  const queryClient = useQueryClient();
  const setFresh = useFreshKeysStore((s) => s.setFresh);

  return useMutation({
    mutationFn: async (body: CreateKeyBody) => {
      const { status, data } = await postJson<CreateKeyResponse>(
        '/api/session/keys',
        body,
      );
      // On a 422 the parsed body is `{ detail }` (truthy) so the `status !== 200`
      // branch throws and carries the detail; on a 502 `data` is null so detail
      // is null. The create-key modal reads `.status` + `.detail` to route a
      // field-rejection to the matching field.
      if (status !== 200 || !data) throw apiCallError('create-key-failed', status, data);
      return data;
    },
    onSuccess: (data) => {
      if (data.id) setFresh(data.id, data.key);
      queryClient.invalidateQueries({ queryKey: KEYS_QUERY_KEY });
    },
  });
}

/**
 * DELETE /api/session/keys/{id}. Backend returns HTTP 200 { status: "deleted",
 * id } (session.py::session_delete_key). On success the fresh key is dropped from
 * the in-memory store and the list is invalidated.
 */
export function useDeleteKey() {
  const queryClient = useQueryClient();
  const dropFresh = useFreshKeysStore((s) => s.dropFresh);

  return useMutation({
    mutationFn: async (id: string) => {
      const { status, data } = await del<DeleteKeyResponse>(
        `/api/session/keys/${encodeURIComponent(id)}`,
      );
      if (status !== 200 || !data) throw apiCallError('delete-key-failed', status, data);
      return data;
    },
    onSuccess: (_data, id) => {
      dropFresh(id);
      queryClient.invalidateQueries({ queryKey: KEYS_QUERY_KEY });
    },
  });
}

/**
 * POST /api/session/keys/{id}/default. Backend returns HTTP 200 { status:
 * "default", id } (session.py::session_make_default), promoting the key to the
 * user's explicit default and clearing any prior default. On success the list is
 * invalidated so the DEFAULT badge + revoke-guard re-render.
 */
export function useMakeDefault() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string) => {
      const { status, data } = await postJson<MakeDefaultResponse>(
        `/api/session/keys/${encodeURIComponent(id)}/default`,
        {},
      );
      if (status !== 200 || !data) throw apiCallError('make-default-failed', status, data);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS_QUERY_KEY });
    },
  });
}
