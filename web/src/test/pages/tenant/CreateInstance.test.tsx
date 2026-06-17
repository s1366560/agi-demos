import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Route, Routes } from 'react-router-dom';

import { CreateInstance } from '../../../pages/tenant/CreateInstance';
import { act, fireEvent, render, screen, waitFor } from '../../utils';

const mocks = vi.hoisted(() => ({
  currentTenant: { id: 'tenant-1' } as { id: string } | null,
  currentProject: { id: 'project-1', tenant_id: 'tenant-1' } as {
    id: string;
    tenant_id: string;
  } | null,
  workspaces: [] as Array<{ id: string; name: string; tenant_id: string; project_id: string }>,
  clusters: [] as Array<{ id: string; name: string }>,
  createInstance: vi.fn(),
  listClusters: vi.fn(),
  loadWorkspaces: vi.fn(),
  navigate: vi.fn(),
  message: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyButton: ({
    children,
    disabled,
    onClick,
  }: {
    children?: React.ReactNode;
    disabled?: boolean;
    onClick?: () => void;
  }) => (
    <button type="button" disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
  LazySelect: ({
    options = [],
    placeholder,
  }: {
    options?: Array<{ label: React.ReactNode; value: string }>;
    placeholder?: string;
  }) => (
    <select aria-label={placeholder}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
  useLazyMessage: () => mocks.message,
}));

vi.mock('../../../services/instanceTemplateService', () => ({
  instanceTemplateService: {
    getById: vi.fn(),
  },
}));

vi.mock('../../../stores/cluster', () => ({
  useClusters: () => mocks.clusters,
  useClusterActions: () => ({ listClusters: mocks.listClusters }),
}));

vi.mock('../../../stores/instance', () => ({
  useInstanceActions: () => ({ createInstance: mocks.createInstance }),
}));

vi.mock('../../../stores/project', () => ({
  useProjectStore: (selector: (state: { currentProject: unknown }) => unknown) =>
    selector({ currentProject: mocks.currentProject }),
}));

vi.mock('../../../stores/tenant', () => ({
  useTenantStore: (selector: (state: { currentTenant: unknown }) => unknown) =>
    selector({ currentTenant: mocks.currentTenant }),
}));

vi.mock('../../../stores/workspace', () => ({
  useWorkspaces: () => mocks.workspaces,
  useWorkspaceStore: (
    selector: (state: { loadWorkspaces: typeof mocks.loadWorkspaces }) => unknown
  ) => selector({ loadWorkspaces: mocks.loadWorkspaces }),
}));

const renderCreateInstance = (route: string, path: string) =>
  render(
    <Routes>
      <Route path={path} element={<CreateInstance />} />
    </Routes>,
    { route }
  );

describe('CreateInstance', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.currentTenant = { id: 'tenant-1' };
    mocks.currentProject = { id: 'project-1', tenant_id: 'tenant-1' };
    mocks.workspaces = [
      {
        id: 'workspace-1',
        name: 'Workspace One',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
      },
    ];
    mocks.clusters = [];
    mocks.createInstance.mockResolvedValue({ id: 'instance-1' });
    mocks.listClusters.mockResolvedValue(undefined);
    mocks.loadWorkspaces.mockResolvedValue(undefined);
  });

  it('ignores stale current project and workspaces from another tenant', async () => {
    mocks.currentTenant = { id: 'tenant-2' };
    mocks.currentProject = { id: 'project-2', tenant_id: 'tenant-2' };
    mocks.workspaces = [
      {
        id: 'workspace-stale',
        name: 'Stale Workspace',
        tenant_id: 'tenant-2',
        project_id: 'project-2',
      },
    ];

    renderCreateInstance('/tenant/tenant-1/instances/create', '/tenant/:tenantId/instances/create');

    await waitFor(() => {
      expect(mocks.listClusters).toHaveBeenCalled();
    });

    expect(mocks.loadWorkspaces).not.toHaveBeenCalled();
    expect(screen.queryByText('Stale Workspace')).not.toBeInTheDocument();
  });

  it('does not create an instance with a synthetic default tenant', async () => {
    mocks.currentTenant = null;
    mocks.currentProject = null;
    mocks.workspaces = [];

    renderCreateInstance('/instances/create', '/instances/create');

    fireEvent.change(screen.getByPlaceholderText('e.g. My Instance'), {
      target: { value: 'No Tenant Instance' },
    });
    fireEvent.change(screen.getByPlaceholderText('e.g. my-instance'), {
      target: { value: 'no-tenant-instance' },
    });

    for (let step = 0; step < 5; step += 1) {
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Next' }));
        await Promise.resolve();
      });
    }

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Create' })).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Create' }));
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(mocks.message.error).toHaveBeenCalledWith('Tenant context is required');
    });
    expect(mocks.createInstance).not.toHaveBeenCalled();
  });
});
