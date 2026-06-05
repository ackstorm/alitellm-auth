// use-models.ts — TanStack Query hook for the public model-group catalog.
//
// Mirrors use-stats.ts: the queryFn threads `{ signal }` into the never-throw api
// wrapper (lib/api::getJson) and THROWS on a non-200 / malformed response so the
// query lands in `isError` (the Models page renders its error+retry branch); a
// 200 resolves to the ModelsResponse contract (an empty catalog is models: []).
//
//   useModels()  GET /api/session/models -> ModelsResponse

import { useQuery } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';

import { getJson } from '@/lib/api';
import type { ModelsResponse } from '@/lib/api-types';

export function useModels(): UseQueryResult<ModelsResponse> {
  return useQuery({
    queryKey: ['session', 'models'],
    queryFn: async ({ signal }): Promise<ModelsResponse> => {
      const { status, data } = await getJson<ModelsResponse>(
        '/api/session/models',
        { signal },
      );
      if (status === 200 && data) return data;
      throw new Error('models-load-failed');
    },
  });
}
