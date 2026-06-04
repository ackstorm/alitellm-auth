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
} from '@/lib/api-types';
import { useFreshKeysStore } from '@/stores/fresh-keys';

/** Query key for the session keys list. Shared by the query + invalidations. */
export const KEYS_QUERY_KEY = ['session', 'keys'] as const;

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
      if (status !== 200 || !data) throw new Error('create-key-failed');
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
      if (status !== 200 || !data) throw new Error('delete-key-failed');
      return data;
    },
    onSuccess: (_data, id) => {
      dropFresh(id);
      queryClient.invalidateQueries({ queryKey: KEYS_QUERY_KEY });
    },
  });
}
