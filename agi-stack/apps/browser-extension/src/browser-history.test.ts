import { describe, expect, it, vi } from 'vitest';
import type { ChromeApi } from './chrome-api';
import { createHistoryHandler } from './browser-history';

describe('browser visit history', () => {
  it('deduplicates queried URLs, preserves visits, filters dates and orders newest first', async () => {
    const history = {
      search: vi.fn(async () => [{ url: 'https://example.test/a', title: 'Example' }]),
      getVisits: vi.fn(async () => [{ visitId: '1', visitTime: 1000 }, { visitId: '2', visitTime: 2500 }, { visitId: '3', visitTime: 4000 }]),
    };
    const call = createHistoryHandler({ history } as unknown as ChromeApi);
    expect(await call({ from: new Date(1500).toISOString(), to: new Date(5000).toISOString(), queries: ['first', 'second'], limit: 2 })).toEqual([
      { dateVisited: new Date(4000).toISOString(), title: 'Example', url: 'https://example.test/a' },
      { dateVisited: new Date(2500).toISOString(), title: 'Example', url: 'https://example.test/a' },
    ]);
    expect(history.getVisits).toHaveBeenCalledTimes(1);
    expect(history.search).toHaveBeenCalledWith({ text: 'first', startTime: 1500, endTime: 5000, maxResults: 2 });
  });
  it('rejects malformed ranges and does not call the browser API', async () => {
    const search = vi.fn();
    const call = createHistoryHandler({ history: { search } } as unknown as ChromeApi);
    for (const options of [{ from: 'invalid' }, { limit: 0 }, { limit: 1001 }, { queries: [7] }, { from: new Date(5000).toISOString(), to: new Date(1000).toISOString() }]) {
      await expect(call(options)).rejects.toThrow();
    }
    expect(search).not.toHaveBeenCalled();
  });
});
