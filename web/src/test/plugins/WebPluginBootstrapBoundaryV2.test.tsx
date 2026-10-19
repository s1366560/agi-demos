import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WebPluginBootstrapBoundaryV2 } from '../../plugins/WebPluginBootstrapBoundaryV2';

const state = vi.hoisted(() => ({ status: 'error', retry: vi.fn() }));
vi.mock('../../plugins/WebPluginGenerationHostV2', () => ({
  useCurrentWebPluginGenerationStateV2: () => ({ status: state.status }),
}));
vi.mock('../../plugins/webPluginGenerationV2', () => ({
  refreshWebPluginGenerationV2: state.retry,
}));
vi.mock('../../stores/auth', () => ({
  useAuthStore: (selector: (value: unknown) => unknown) => selector({ user: { id: 'u1' } }),
}));
vi.mock('../../stores/tenant', () => ({
  useTenantStore: (selector: (value: unknown) => unknown) =>
    selector({ currentTenant: { id: 't1' } }),
}));
vi.mock('../../stores/project', () => ({
  useProjectStore: (selector: (value: unknown) => unknown) =>
    selector({ currentProject: { id: 'p1', tenant_id: 't1' } }),
}));
vi.mock('../../components/plugins/PluginInstancesV2', () => ({
  PluginInstancesV2: ({ tenantId, projectId }: { tenantId: string; projectId: string }) => (
    <div data-testid="recovery-instances">
      {tenantId}:{projectId}
    </div>
  ),
}));

describe('WebPluginBootstrapBoundaryV2', () => {
  beforeEach(() => {
    state.status = 'error';
    state.retry.mockReset().mockResolvedValue(undefined);
  });

  it('shows an explicit failure and a retry without requiring a generation', async () => {
    render(<WebPluginBootstrapBoundaryV2 />);
    expect(screen.getByRole('alert')).toHaveTextContent('plugins.bootstrapFailed');
    state.retry.mockRejectedValue(new Error('candidate unavailable'));
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(state.retry).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled());
    expect(screen.getByRole('alert')).toBeVisible();
  });

  it('opens the authorized kernel management surface for the current scope', () => {
    render(<WebPluginBootstrapBoundaryV2 />);
    expect(screen.queryByTestId('recovery-instances')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'plugins.openConfiguration' }));
    expect(screen.getByTestId('recovery-instances')).toHaveTextContent('t1:p1');
  });

  it('keeps the initial loading state separate from an empty or rejected view', () => {
    state.status = 'loading';
    const view = render(<WebPluginBootstrapBoundaryV2 />);
    expect(screen.getByRole('status')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    state.status = 'empty';
    view.rerender(<WebPluginBootstrapBoundaryV2 />);
    expect(screen.getByRole('alert')).toBeVisible();
  });
});
