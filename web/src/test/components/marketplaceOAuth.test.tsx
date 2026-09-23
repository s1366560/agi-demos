import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MarketplaceOAuth } from '@/components/marketplace/v3/MarketplaceOAuth';
import { MarketplaceCache } from '@/components/marketplace/v3/MarketplaceCache';
import {
  createMarketplaceClient,
  type MarketplaceTransport,
} from '../../../../agi-stack/packages/plugin-marketplace-ui/src/client';
import { marketplaceEn } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/messages';
const t = (key: keyof typeof marketplaceEn) => marketplaceEn[key];
afterEach(() => vi.restoreAllMocks());

it('opens authorization, cancels it, and rejects unsafe authorization addresses', async () => {
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  const requests: Array<{ path: string; body: unknown }> = [];
  let unsafe = false;
  const transport: MarketplaceTransport = async <T,>(path: string, options) => {
    requests.push({ path, body: options.body });
    return (
      path.endsWith('/start')
        ? {
            status: 'authorizing',
            authorization_url: unsafe
              ? 'javascript:alert(1)'
              : 'https://issuer.example/authorize?state=opaque',
          }
        : { status: 'not_connected' }
    ) as T;
  };
  render(
    <MarketplaceOAuth
      client={createMarketplaceClient(transport, { tenant_id: 'tenant', project_id: 'project' })}
      installationId="install"
      service={{ name: 'mcp', status: 'not_connected' }}
      canManage
      t={t}
    />
  );
  await waitFor(() => expect(requests).toHaveLength(1));
  fireEvent.click(screen.getByRole('button', { name: 'Connect service' }));
  await screen.findByText('Waiting for authorization');
  expect(open).toHaveBeenCalledWith(
    'https://issuer.example/authorize?state=opaque',
    '_blank',
    'noopener,noreferrer'
  );
  expect(requests[1]?.body).toMatchObject({
    tenant_id: 'tenant',
    project_id: 'project',
    idempotency_key: expect.any(String),
  });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel authorization' }));
  await screen.findByRole('button', { name: 'Connect service' });
  expect(requests[2]?.path).toMatch(/\/cancel$/);
  unsafe = true;
  fireEvent.click(screen.getByRole('button', { name: 'Connect service' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('not a permitted web address');
  expect(open).toHaveBeenCalledTimes(1);
});

it('retries missing client configuration and disconnects confirmed connections', async () => {
  const transport: MarketplaceTransport = vi.fn(
    async (path, options) =>
      (path.endsWith('/start')
        ? { status: 'connected' }
        : path.endsWith('/disconnect')
          ? { status: 'not_connected' }
          : { status: 'needs_configuration', reason: 'client_registration_required' }) as never
  );
  render(
    <MarketplaceOAuth
      client={createMarketplaceClient(transport, { tenant_id: 'tenant' })}
      installationId="install"
      service={{ name: 'mcp', status: 'needs_configuration' }}
      canManage
      t={t}
    />
  );
  await screen.findByText('client_registration_required');
  fireEvent.change(screen.getByLabelText('Client ID (optional)'), {
    target: { value: 'registered-client' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Connect service' }));
  await screen.findByText('Connected');
  expect(transport).toHaveBeenCalledWith(
    expect.stringMatching(/\/start$/),
    expect.objectContaining({ body: expect.objectContaining({ client_id: 'registered-client' }) })
  );
  fireEvent.click(screen.getByRole('button', { name: 'Disconnect service' }));
  await screen.findByText('Not connected');
});

it('cleans only server-reported reclaimable cache and shows authoritative results', async () => {
  const transport: MarketplaceTransport = vi.fn(
    async (path) =>
      (path.includes('/cleanup')
        ? {
            total_bytes: 40,
            reclaimable_bytes: 0,
            entries: 1,
            removed_bytes: 60,
            removed_entries: 2,
          }
        : { total_bytes: 100, reclaimable_bytes: 60, entries: 3 }) as never
  );
  render(
    <MarketplaceCache
      client={createMarketplaceClient(transport, { tenant_id: 'tenant', project_id: 'project' })}
      canManage
      t={t}
    />
  );
  await screen.findByText('100');
  fireEvent.click(screen.getByRole('button', { name: 'Clean unused cache' }));
  await screen.findByText('Removed bytes: 60');
  expect(screen.getByRole('button', { name: 'Clean unused cache' })).toBeDisabled();
  expect(transport).toHaveBeenCalledWith(
    expect.stringMatching(/\/cache\/cleanup$/),
    expect.objectContaining({
      body: expect.objectContaining({
        tenant_id: 'tenant',
        project_id: 'project',
        idempotency_key: expect.any(String),
      }),
    })
  );
});

it('polls pending authorization and ignores stale status after cancellation', async () => {
  let resolveStatus: ((value: unknown) => void) | undefined;
  let requests = 0;
  const transport: MarketplaceTransport = async <T,>(path: string) => {
    if (path.includes('/status')) {
      requests++;
      if (requests === 1) return { status: 'authorizing' } as T;
      return await new Promise<T>((resolve) => {
        resolveStatus = resolve as (value: unknown) => void;
      });
    }
    return { status: 'not_connected' } as T;
  };
  render(
    <MarketplaceOAuth
      client={createMarketplaceClient(transport, { tenant_id: 'tenant' })}
      installationId="install"
      service={{ name: 'mcp', status: 'authorizing' }}
      canManage
      t={t}
    />
  );
  await waitFor(() => expect(resolveStatus).toBeDefined(), { timeout: 3500 });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel authorization' }));
  await screen.findByText('Not connected');
  resolveStatus?.({ status: 'connected' });
  await waitFor(() => expect(screen.queryByText('Connected')).not.toBeInTheDocument());
});
