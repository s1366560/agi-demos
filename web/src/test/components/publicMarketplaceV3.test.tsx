import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { httpClient } from '@/services/client/httpClient';
import { PluginMarketplaceV3 } from '@/components/marketplace/v3/PluginMarketplaceV3';
import i18n from '@/i18n/config';

vi.unmock('@/i18n/config');
vi.unmock('react-i18next');

vi.mock('@/services/client/httpClient', () => ({
  httpClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

describe('public marketplace browsing', () => {
  it('loads the public catalog without private requests when management would return 403', async () => {
    await i18n.changeLanguage('en-US');
    vi.mocked(httpClient.get).mockImplementation(async (path: string) => {
      if (path.startsWith('/plugin-marketplace/v3/catalog?'))
        return {
          items: [
            {
              id: 'public-example',
              name: 'Public example',
              description: 'Browse without management access',
              version: '1',
              publisher: 'MemStack',
              source_id: 'curated',
              format: 'codex',
              category: 'Development',
              capabilities: ['skills'],
              targets: ['cloud'],
              permissions: [],
              compatible: true,
              reasons: [],
            },
          ],
        };
      throw Object.assign(new Error('Forbidden'), { status: 403 });
    });
    render(<PluginMarketplaceV3 tenantId="tenant" projectId="project" canManage={false} />);
    expect(await screen.findByRole('heading', { name: 'Public example' })).toBeVisible();
    expect(
      screen.getByText(
        'Public catalog. A tenant and project administrator can manage sources and installations.'
      )
    ).toBeVisible();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText('No plugins installed in this scope.')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Installed', exact: true })).toBeNull();
    expect(httpClient.get).toHaveBeenCalledTimes(1);
    expect(httpClient.get).toHaveBeenCalledWith(
      '/plugin-marketplace/v3/catalog?tenant_id=tenant&project_id=project',
      expect.any(Object)
    );
    expect(httpClient.post).not.toHaveBeenCalled();
  });
});
