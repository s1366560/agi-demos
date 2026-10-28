import { describe, expect, it, vi } from 'vitest';
import type { ChromeApi } from './chrome-api';
import { createManagementHandler } from './facade-management';

function fixture(shared = false) {
  const stored: Record<string, unknown> = {};
  const update = vi.fn(async () => ({ id: 7, pinned: true }));
  const api = {
    tabs: { query: async () => [{ id: 7, windowId: 1, groupId: 3, pinned: false }], update },
    tabGroups: { query: async () => [{ id: 3, windowId: 1, shared }] },
    storage: { local: { get: async (key: string) => ({ [key]: stored[key] }), set: async (items: Record<string, unknown>) => Object.assign(stored, items) } },
  };
  return { call: createManagementHandler(api as unknown as ChromeApi), update, stored };
}
describe('restricted browser management', () => {
  it('changes a tab through the actual API and records its prior state', async () => {
    const { call, update } = fixture();
    await call({ namespace: 'tabs', method: 'update', args: [7, { pinned: true }] });
    expect(update).toHaveBeenCalledWith(7, { pinned: true });
    const audit = await call({ namespace: 'management', method: 'getAuditTrail' }) as { changes: Array<Record<string, unknown>> };
    expect(audit.changes[0]).toMatchObject({ namespace: 'tabs', method: 'update', args: [7, { pinned: true }], before: { tabLayout: { tabs: [{ id: 7, pinned: false }] } } });
  });
  it('rejects navigation and privileged methods before dispatch', async () => {
    const { call, update } = fixture();
    await expect(call({ namespace: 'tabs', method: 'update', args: [7, { url: 'https://example.com' }] })).rejects.toThrow('unsupported management field');
    await expect(call({ namespace: 'windows', method: 'remove', args: [1] })).rejects.toThrow('not permitted');
    expect(update).not.toHaveBeenCalled();
  });
  it('preserves shared tab groups', async () => {
    const { call, update } = fixture(true);
    await expect(call({ namespace: 'tabs', method: 'update', args: [7, { pinned: true }] })).rejects.toThrow('shared groups');
    expect(update).not.toHaveBeenCalled();
  });
});
