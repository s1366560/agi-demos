import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MarketplaceView } from '@/components/marketplace/v3/MarketplaceView';
import {
  createMarketplaceClient,
  filterPlugins,
  type PluginDescriptor,
  type MarketplaceTransport,
} from '../../../../agi-stack/packages/plugin-marketplace-ui/src/client';
import { marketplaceEn } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/messages';

const plugin: PluginDescriptor = {
  id: 'example',
  name: 'Example skill',
  description: 'Summarize documents',
  version: '1.0',
  publisher: 'MemStack',
  source_id: 'curated',
  format: 'codex',
  category: 'productivity',
  capabilities: ['skills'],
  targets: ['local'],
  permissions: ['files.read'],
  compatible: true,
  reasons: [],
};
const preflight = {
  id: 'preflight-1',
  plugin,
  permissions: plugin.permissions,
  compatible: true,
  reasons: [],
  digest: 'sha256:abc',
};
function setup(fixtureOptions: { failInstall?: boolean; catalogErrors?: boolean } = {}) {
  let installed = false;
  const requests: Array<{ path: string; body: unknown }> = [];
  const transport: MarketplaceTransport = async <T,>(
    path: string,
    options: { method?: string; body?: unknown }
  ) => {
    requests.push({ path, body: options.body });
    if (path.includes('/catalog?'))
      return {
        items: [plugin],
        errors: fixtureOptions.catalogErrors
          ? [{ source_id: 'curated', error: 'Source unavailable' }]
          : [],
      } as T;
    if (path.includes('/sources?'))
      return {
        items: [
          {
            id: 'curated',
            name: 'Curated',
            kind: 'https',
            trusted: true,
            location: 'https://example.com/catalog.json',
          },
        ],
      } as T;
    if (path.endsWith('/preflight')) return preflight as T;
    if (path.endsWith('/installations') && options.method === 'POST') {
      if (fixtureOptions.failInstall)
        throw new Error('Installation failed; previous version retained');
      installed = true;
      return { id: 'install-1', status: 'needs_configuration' } as T;
    }
    if (path.includes('/installations?'))
      return {
        items: installed
          ? [
              {
                id: 'install-1',
                plugin_id: plugin.id,
                source_id: plugin.source_id,
                name: plugin.name,
                version: plugin.version,
                capabilities: plugin.capabilities,
                status: 'needs_configuration',
              },
            ]
          : [],
      } as T;
    return {} as T;
  };
  const client = createMarketplaceClient(transport, { tenant_id: 'tenant', project_id: 'project' });
  render(
    <MarketplaceView
      client={client}
      t={(key) => marketplaceEn[key]}
      scope="tenant / project"
      canManage
      local
    />
  );
  return { requests };
}
describe('plugin marketplace V3', () => {
  it('requires explicit approval after server preflight and displays authoritative installation state', async () => {
    const { requests } = setup();
    fireEvent.click(await screen.findByRole('button', { name: 'Review installation' }));
    const install = await screen.findByRole('button', { name: 'Approve and install' });
    expect(install).toBeDisabled();
    fireEvent.click(screen.getByLabelText(marketplaceEn.approve));
    fireEvent.click(install);
    await screen.findByText('Needs configuration');
    const mutation = requests.find((request) => request.path.endsWith('/installations'));
    expect(mutation?.body).toMatchObject({
      tenant_id: 'tenant',
      project_id: 'project',
      preflight_id: 'preflight-1',
      approved_permissions: ['files.read'],
    });
    expect(screen.queryByText('Enabled')).toBeNull();
  });
  it('filters declared metadata without interpreting descriptions', () => {
    expect(
      filterPlugins([plugin], {
        query: 'SUMMARIZE',
        category: 'productivity',
        capability: 'skills',
        target: 'local',
        source: 'curated',
      })
    ).toEqual([plugin]);
    expect(
      filterPlugins([plugin], {
        query: '',
        category: 'documents',
        capability: '',
        target: '',
        source: '',
      })
    ).toEqual([]);
  });
  it('requires trust confirmation before adding a source', async () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'Sources' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add source' })).toBeDisabled());
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Private' } });
    fireEvent.change(screen.getByLabelText('Location'), {
      target: { value: 'https://example.com/private.json' },
    });
    fireEvent.click(screen.getByLabelText(marketplaceEn.trust));
    expect(screen.getByRole('button', { name: 'Add source' })).toBeEnabled();
  });
  it('keeps scope and caller idempotency key in update requests', async () => {
    const transport = vi.fn().mockResolvedValue({});
    const client = createMarketplaceClient(transport, {
      tenant_id: 'tenant',
      project_id: 'project',
    });
    await client.action(
      {
        id: 'a/b',
        plugin_id: 'example',
        source_id: 'curated',
        name: 'Example',
        version: '1',
        capabilities: [],
        status: 'enabled',
      },
      'update',
      { preflight_id: 'next', approved_permissions: [] },
      'retry-key'
    );
    expect(transport).toHaveBeenCalledWith(
      '/api/v1/plugin-marketplace/v3/installations/a%2Fb/update',
      expect.objectContaining({
        body: {
          tenant_id: 'tenant',
          project_id: 'project',
          preflight_id: 'next',
          approved_permissions: [],
          idempotency_key: 'retry-key',
        },
      })
    );
  });
  it('cancels permission review without a mutation and resets approval on reopening', async () => {
    const { requests } = setup();
    fireEvent.click(await screen.findByRole('button', { name: 'Review installation' }));
    fireEvent.click(await screen.findByLabelText(marketplaceEn.approve));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('button', { name: 'Approve and install' })).toBeNull();
    expect(requests.some((item) => item.path.endsWith('/installations'))).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Review installation' }));
    expect(await screen.findByRole('button', { name: 'Approve and install' })).toBeDisabled();
  });
  it('shows installation failures without claiming a successful installation', async () => {
    setup({ failInstall: true });
    fireEvent.click(await screen.findByRole('button', { name: 'Review installation' }));
    fireEvent.click(await screen.findByLabelText(marketplaceEn.approve));
    fireEvent.click(screen.getByRole('button', { name: 'Approve and install' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Installation failed');
    expect(screen.queryByText(marketplaceEn.actionConfirmed)).toBeNull();
    expect(screen.getByRole('button', { name: 'Approve and install' })).toBeEnabled();
  });
  it('renders source-specific catalog failures alongside available plugins', async () => {
    setup({ catalogErrors: true });
    expect(await screen.findByRole('alert')).toHaveTextContent('Curated: Source unavailable');
    expect(screen.getByText('Example skill')).toBeVisible();
  });
  it('discards pending preflight results after scope changes', async () => {
    let complete!: (value: typeof preflight) => void;
    const makeClient = (pending = false) =>
      createMarketplaceClient(
        async <T,>(path: string) => {
          if (path.includes('/catalog?')) return { items: [plugin] } as T;
          if (path.endsWith('/preflight') && pending)
            return (await new Promise<typeof preflight>((resolve) => {
              complete = resolve;
            })) as T;
          return { items: [] } as T;
        },
        { tenant_id: 'tenant', project_id: pending ? 'old' : 'new' }
      );
    const first = makeClient(true);
    const second = makeClient();
    const { rerender } = render(
      <MarketplaceView client={first} t={(key) => marketplaceEn[key]} scope="old" canManage local />
    );
    fireEvent.click(await screen.findByRole('button', { name: 'Review installation' }));
    rerender(
      <MarketplaceView
        client={second}
        t={(key) => marketplaceEn[key]}
        scope="new"
        canManage
        local
      />
    );
    complete(preflight);
    await waitFor(() => expect(screen.queryByText('Working…')).toBeNull());
    expect(screen.queryByRole('button', { name: 'Approve and install' })).toBeNull();
    expect(screen.queryByText('sha256:abc')).toBeNull();
  });
});

describe('declared credential configuration', () => {
  it('submits every required credential together without rendering stored values', async () => {
    const { MarketplaceCredentials } =
      await import('@/components/marketplace/v3/MarketplaceCredentials');
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <MarketplaceCredentials
        installation={{
          id: 'config',
          name: 'Credential plugin',
          plugin_id: 'credential',
          source_id: 'curated',
          version: '1',
          status: 'needs_configuration',
          capabilities: ['mcp'],
          required_credentials: ['CLIENT_ID', 'CLIENT_SECRET'],
        }}
        t={(key) => marketplaceEn[key]}
        busy={false}
        canManage
        onSave={onSave}
        onCancel={() => {}}
      />
    );
    fireEvent.change(screen.getByLabelText('CLIENT_ID'), { target: { value: 'fixture-client' } });
    fireEvent.change(screen.getByLabelText('CLIENT_SECRET'), {
      target: { value: 'fixture-secret' },
    });
    expect(screen.getByLabelText('CLIENT_SECRET')).toHaveAttribute('type', 'password');
    fireEvent.click(screen.getByRole('button', { name: 'Save credential' }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        CLIENT_ID: 'fixture-client',
        CLIENT_SECRET: 'fixture-secret',
      })
    );
    await waitFor(() => expect(screen.getByLabelText('CLIENT_SECRET')).toHaveValue(''));
  });
});

it('hands signed V2 packages to the existing installer without V3 preflight', async () => {
  const signedPlugin: PluginDescriptor = {
    ...plugin,
    format: 'v2',
    source_id: 'signed-v2',
    install_strategy: 'signed-v2',
  };
  const requests: string[] = [];
  const transport: MarketplaceTransport = async <T,>(path: string) => {
    requests.push(path);
    return { items: path.includes('/catalog') ? [signedPlugin] : [] } as T;
  };
  const openSignedInstaller = vi.fn();
  render(
    <MarketplaceView
      client={createMarketplaceClient(transport, { tenant_id: 'tenant' })}
      t={(key) => marketplaceEn[key]}
      scope="tenant"
      canManage
      local={false}
      onInstallSignedV2={openSignedInstaller}
    />
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Open signed package installer' }));
  expect(openSignedInstaller).toHaveBeenCalledOnce();
  expect(
    requests.some((path) => path.includes('/preflight') || path.endsWith('/installations'))
  ).toBe(false);
});

it('hands installed signed V2 records to signed management without generic mutations', async () => {
  const requests: Array<{ path: string; method?: string }> = [];
  const transport: MarketplaceTransport = async <T,>(path: string, options) => {
    requests.push({ path, method: options.method ?? 'GET' });
    return {
      items: path.includes('/installations')
        ? [
            {
              id: 'signed-install',
              plugin_id: 'signed-example',
              source_id: 'signed-v2',
              name: 'Signed example',
              version: '1.0',
              status: 'enabled',
              capabilities: ['skills'],
              install_strategy: 'signed-v2',
            },
          ]
        : [],
    } as T;
  };
  const handoff = vi.fn();
  render(
    <MarketplaceView
      client={createMarketplaceClient(transport, { tenant_id: 'tenant' })}
      t={(key) => marketplaceEn[key]}
      scope="tenant"
      canManage
      local={false}
      onInstallSignedV2={handoff}
    />
  );
  fireEvent.click(screen.getByRole('button', { name: 'Installed' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Open signed package installer' }));
  expect(handoff).toHaveBeenCalledOnce();
  for (const name of ['Disable', 'Configure', 'Verify', 'Review update', 'Uninstall']) {
    expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
  }
  expect(requests.every((request) => request.method === 'GET')).toBe(true);
});
