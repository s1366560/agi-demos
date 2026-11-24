import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PluginMarket } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/PluginMarket';
import { menuPath, routeRank } from '../../../../agi-stack/packages/plugin-slots/src/richPage';

describe('tenant package market', () => {
  it('requests the tenant catalog and detail without a current project', async () => {
    const catalog = { items: [], total: 0, can_manage: false, source: null };
    const request = vi.fn().mockResolvedValue(catalog);
    render(
      <PluginMarket
        tenantId="north"
        projectId={null}
        target="web"
        locale="en"
        transport={request}
        pluginId={null}
        onOpen={vi.fn()}
        onSelect={vi.fn()}
      />
    );
    await waitFor(() => expect(request).toHaveBeenCalled());
    const url = new URL(request.mock.calls[0]![0], 'http://localhost');
    expect(url.pathname).toBe('/api/v1/tenant-packages/npm/catalog');
    expect(url.searchParams.get('tenant_id')).toBe('north');
    expect(url.searchParams.has('project_id')).toBe(false);
    expect(screen.getByTestId('plugin-market')).toBeTruthy();
  });

  it('binds tenant routes to their owner and excludes project placeholders', () => {
    const scope = { tenantId: 'north', projectId: null };
    expect(menuPath('/tenant/:tenantId/billing', scope)).toBe('/tenant/north/billing');
    expect(routeRank('/tenant/:tenantId/billing', '/tenant/south/billing', scope)).toBeNull();
    expect(routeRank('/project/:projectId/billing', '/project/p/billing', scope)).toBeNull();
  });
});
