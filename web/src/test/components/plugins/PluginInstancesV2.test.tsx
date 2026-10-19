import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PluginInstancesV2 } from '@/components/plugins/PluginInstancesV2';
import {
  pluginInstanceServiceV2,
  type PluginInstancesResponseV2,
} from '@/services/pluginInstanceServiceV2';
import { refreshWebPluginGenerationV2 } from '@/plugins/webPluginGenerationV2';
import { useCurrentWebPluginGenerationStateV2 } from '@/plugins/WebPluginGenerationHostV2';

vi.mock('@/services/pluginInstanceServiceV2', () => ({
  pluginInstanceServiceV2: { list: vi.fn(), apply: vi.fn() },
}));
vi.mock('@/plugins/webPluginGenerationV2', () => ({
  refreshWebPluginGenerationV2: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('@/plugins/WebPluginGenerationHostV2', () => ({
  useCurrentWebPluginGenerationStateV2: vi.fn(),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name?: string }) =>
      options?.name ? `${key} ${options.name}` : key,
  }),
}));

function snapshot(tenant = 'tenant-a', enabled = true, revision = 4): PluginInstancesResponseV2 {
  return {
    scope: { kind: 'tenant', tenant_id: tenant, project_id: null, session_id: null },
    revision,
    publication: { status: 'ready', publication_id: 'pub', generation: revision },
    instances: [
      {
        entry_id: 'graph',
        plugin_id: 'graph',
        display_name: `Graph ${tenant}`,
        module_ref: 'builtin:graph',
        enabled,
        config: { title: 'Initial' },
        config_schema: {
          type: 'object',
          properties: { title: { type: 'string', title: 'Graph title' } },
        },
        editable: true,
        config_editable: true,
        reason_code: null,
        inherited_from: null,
        replacement_candidates: [],
        state: { status: enabled ? 'active' : 'disabled', reason_code: null },
      },
    ],
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('PluginInstancesV2', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(pluginInstanceServiceV2.list).mockResolvedValue(snapshot());
    vi.mocked(useCurrentWebPluginGenerationStateV2).mockReturnValue(undefined);
  });
  it('distinguishes backend readiness from this browser retaining a failed candidate', async () => {
    vi.mocked(useCurrentWebPluginGenerationStateV2).mockReturnValue({
      status: 'degraded',
      error: new Error('candidate failed'),
      generation: { snapshot: { generation: 3 } },
    } as ReturnType<typeof useCurrentWebPluginGenerationStateV2>);
    render(<PluginInstancesV2 tenantId="tenant-a" canManage />);
    expect(await screen.findByText(/plugins.backendPublication/)).toHaveTextContent(
      'plugins.publicationStates.ready'
    );
    expect(screen.getByText(/plugins.browserRenderer/)).toHaveTextContent(
      'plugins.rendererStates.failed'
    );
    expect(screen.queryByText('plugins.rendererStates.applied')).not.toBeInTheDocument();
  });
  it('does not claim or refresh a different configuration scope in this browser', async () => {
    vi.mocked(pluginInstanceServiceV2.apply).mockResolvedValue(snapshot('tenant-a', false, 5));
    render(
      <PluginInstancesV2
        tenantId="tenant-a"
        projectId="another-project"
        canManage
        rendererScopeMatches={false}
      />
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'plugins.disableNamed Graph tenant-a' })
    );
    expect(
      await screen.findByRole('button', { name: 'plugins.enableNamed Graph tenant-a' })
    ).toBeEnabled();
    expect(screen.getByText(/plugins.browserRenderer/)).toHaveTextContent(
      'plugins.rendererStates.differentScope'
    );
    expect(refreshWebPluginGenerationV2).not.toHaveBeenCalled();
  });
  it('applies with the explicit scope/revision and refreshes the generation after publication', async () => {
    vi.mocked(pluginInstanceServiceV2.apply).mockResolvedValue(snapshot('tenant-a', false, 5));
    render(<PluginInstancesV2 tenantId="tenant-a" projectId="project-a" canManage />);
    fireEvent.click(
      await screen.findByRole('button', { name: 'plugins.disableNamed Graph tenant-a' })
    );
    await waitFor(() =>
      expect(pluginInstanceServiceV2.apply).toHaveBeenCalledWith(
        { tenant_id: 'tenant-a', project_id: 'project-a' },
        4,
        [{ entry_id: 'graph', enabled: false }]
      )
    );
    expect(
      await screen.findByRole('button', { name: 'plugins.enableNamed Graph tenant-a' })
    ).toBeEnabled();
    expect(refreshWebPluginGenerationV2).toHaveBeenCalledTimes(1);
  });
  it('keeps a typed configuration draft after revision/configuration failure', async () => {
    vi.mocked(pluginInstanceServiceV2.apply).mockRejectedValue(new Error('revision_conflict'));
    render(<PluginInstancesV2 tenantId="tenant-a" canManage />);
    fireEvent.click(
      await screen.findByRole('button', { name: 'plugins.configureNamed Graph tenant-a' })
    );
    fireEvent.change(screen.getByLabelText('Graph title'), { target: { value: 'Edited title' } });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('revision_conflict');
    expect(screen.getByLabelText('Graph title')).toHaveValue('Edited title');
    expect(pluginInstanceServiceV2.apply).toHaveBeenCalledWith(expect.anything(), 4, [
      { entry_id: 'graph', config: { title: 'Edited title' } },
    ]);
    expect(refreshWebPluginGenerationV2).not.toHaveBeenCalled();
  });
  it('does not send private configuration when changing implementation', async () => {
    const source = snapshot();
    const response = {
      ...source,
      instances: [
        {
          ...source.instances[0]!,
          config: {},
          config_editable: false,
          replacement_candidates: [{ plugin_id: 'replacement', module_ref: 'builtin:replacement' }],
        },
      ],
    };
    vi.mocked(pluginInstanceServiceV2.list).mockResolvedValue(response);
    vi.mocked(pluginInstanceServiceV2.apply).mockResolvedValue(response);
    render(<PluginInstancesV2 tenantId="tenant-a" canManage />);
    fireEvent.click(
      await screen.findByRole('button', { name: 'plugins.configureNamed Graph tenant-a' })
    );
    expect(screen.queryByLabelText('Graph title')).toBeNull();
    fireEvent.change(screen.getByLabelText('plugins.replacement'), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));
    await waitFor(() =>
      expect(pluginInstanceServiceV2.apply).toHaveBeenCalledWith(expect.anything(), 4, [
        {
          entry_id: 'graph',
          replacement: { plugin_id: 'replacement', module_ref: 'builtin:replacement' },
        },
      ])
    );
  });
  it('ignores an old scope apply response after switching tenants', async () => {
    const pending = deferred<PluginInstancesResponseV2>();
    vi.mocked(pluginInstanceServiceV2.apply).mockReturnValue(pending.promise);
    const { rerender } = render(<PluginInstancesV2 tenantId="tenant-a" canManage />);
    fireEvent.click(
      await screen.findByRole('button', { name: 'plugins.disableNamed Graph tenant-a' })
    );
    vi.mocked(pluginInstanceServiceV2.list).mockResolvedValue(snapshot('tenant-b'));
    rerender(<PluginInstancesV2 tenantId="tenant-b" canManage />);
    await screen.findByText('Graph tenant-b');
    await act(async () => pending.resolve(snapshot('tenant-a', false, 5)));
    expect(screen.queryByText('Graph tenant-a')).toBeNull();
    expect(
      screen.getByRole('button', { name: 'plugins.disableNamed Graph tenant-b' })
    ).toBeEnabled();
    expect(refreshWebPluginGenerationV2).not.toHaveBeenCalled();
  });
  it('shows read-only desired/actual state without permitting edits', async () => {
    render(<PluginInstancesV2 tenantId="tenant-a" canManage={false} />);
    expect(
      await screen.findByRole('button', { name: 'plugins.disableNamed Graph tenant-a' })
    ).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'plugins.configureNamed Graph tenant-a' })
    ).toBeDisabled();
    expect(screen.getByText(/plugins.runtimeStates.active/)).toBeTruthy();
  });
});
