import { afterEach, describe, expect, test, vi } from 'vitest';
import { apiFetch } from './api';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('apiFetch never-throw contract', () => {
  test('a thrown fetch (network failure) maps to { status: 0, data: null }', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    );

    const result = await apiFetch('/api/session/me');

    expect(result).toEqual({ status: 0, data: null });
  });

  test('a 401 with a non-JSON body maps to { status: 401, data: null }', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        status: 401,
        // resp.json() rejects on a non-JSON body — apiFetch must swallow it.
        json: () => Promise.reject(new SyntaxError('Unexpected end of JSON input')),
      } as unknown as Response),
    );

    const result = await apiFetch('/api/session/me');

    expect(result).toEqual({ status: 401, data: null });
  });
});
