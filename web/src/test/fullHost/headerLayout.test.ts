import { describe, expect, it } from 'vitest';
import { deriveTopNavigationItems } from '@/config/navigation';
import { layoutHeaderItems } from '@/fullHost/navigation';

describe('installed workbench header', () => {
  it('keeps original groups and order while accepting a new package destination', () => {
    const original = deriveTopNavigationItems('tenant', { tenantId: 't' });
    const slots = original.filter((item) => ['plugins', 'users', 'billing'].includes(item.id));
    const installed = slots.map((item) => ({
      id: 'release/' + item.id,
      label: 'From package',
      path: item.path + '?tenant=t',
    }));
    const extra = { id: 'other/page', label: 'Inventory', path: '/inventory' };
    const header = layoutHeaderItems([extra, ...installed.reverse()], original, 'tenant');
    expect(header.slice(0, -1).map((item) => [item.id, item.groupId])).toEqual(
      slots.map((item) => [item.id, item.groupId])
    );
    expect(header.at(-1)).toMatchObject({ ...extra, groupId: 'tenant-extensions-integrations' });
  });
});
