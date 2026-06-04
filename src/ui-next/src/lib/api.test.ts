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

  test('an AbortError is re-thrown (cancellation, not a fake network error)', async () => {
    // A TanStack-Query cancellation aborts the fetch; apiFetch must surface that
    // as a rejection so Query treats it as a cancellation, NOT flip the
    // never-throw contract into a fake { status: 0 } network error.
    const abortErr =
      typeof DOMException !== 'undefined'
        ? new DOMException('The operation was aborted.', 'AbortError')
        : Object.assign(new Error('aborted'), { name: 'AbortError' });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abortErr));

    await expect(apiFetch('/api/session/keys')).rejects.toThrow();
  });
});
