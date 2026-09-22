import { useQuery } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';

import { getJson } from '@/lib/api';
import type { A2aResponse } from '@/lib/api-types';

export function useA2a(): UseQueryResult<A2aResponse> {
  return useQuery({
    queryKey: ['session', 'a2a'],
    queryFn: async ({ signal }): Promise<A2aResponse> => {
      const { status, data } = await getJson<A2aResponse>('/api/session/a2a', {
        signal,
      });
      if (status === 200 && data) return data;
      throw new Error('a2a-load-failed');
    },
  });
}
