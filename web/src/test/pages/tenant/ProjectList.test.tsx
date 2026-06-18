import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import { ProjectList } from '../../../pages/tenant/ProjectList';
import { projectAPI } from '../../../services/api';
import { useProjectStore } from '../../../stores/project';
import { useTenantStore } from '../../../stores/tenant';
import { screen, render, waitFor, fireEvent } from '../../utils';

import type { Project } from '../../../types/memory';

vi.mock('../../../stores/tenant');
vi.mock('../../../services/api');
vi.mock('../../../hooks/useDebounce', () => ({
  useDebounce: (value: unknown) => value,
}));

describe('ProjectList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectStore.setState({
      projects: [],
      currentProject: null,
      isLoading: false,
      error: null,
      total: 0,
      page: 1,
      pageSize: 20,
      ownerIds: [],
    });
  });

  it('renders list of projects', async () => {
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: { id: 't1', max_storage: 1024 },
    } as any);

    const mockProjects: Project[] = [
      {
        id: 'p1',
        tenant_id: 't1',
        name: 'Project A',
        description: 'Desc A',
        owner_id: 'user1',
        member_ids: [],
        memory_rules: {
          max_episodes: 1000,
          retention_days: 30,
          auto_refresh: true,
          refresh_interval: 300,
        },
        graph_config: {
          max_nodes: 500,
          max_edges: 1000,
          similarity_threshold: 0.8,
          community_detection: true,
        },
        is_public: true,
        created_at: '2024-01-01T00:00:00Z',
        stats: {
          memory_count: 0,
          storage_used: 0,
          node_count: 0,
          member_count: 0,
          last_active: null,
        },
      },
      {
        id: 'p2',
        tenant_id: 't1',
        name: 'Project B',
        description: 'Desc B',
        owner_id: 'user2',
        member_ids: [],
        memory_rules: {
          max_episodes: 1000,
          retention_days: 30,
          auto_refresh: true,
          refresh_interval: 300,
        },
        graph_config: {
          max_nodes: 500,
          max_edges: 1000,
          similarity_threshold: 0.8,
          community_detection: true,
        },
        is_public: false,
        created_at: '2024-01-01T00:00:00Z',
        stats: {
          memory_count: 0,
          storage_used: 512,
          node_count: 0,
          member_count: 3,
          last_active: null,
        },
      },
    ];

    vi.mocked(projectAPI.list).mockResolvedValue({
      projects: mockProjects,
      total: 2,
      page: 1,
      page_size: 10,
    });

    render(<ProjectList />);

    await waitFor(() => {
      expect(screen.getByText('Project A')).toBeInTheDocument();
      expect(screen.getByText('Project B')).toBeInTheDocument();
    });

    expect(screen.getByLabelText('tenant.projects.filters.ownerLabel')).toHaveValue('all');
    expect(screen.getByLabelText('tenant.projects.filters.visibilityLabel')).toHaveValue('all');
    expect(screen.queryByText('common.stats.owner')).not.toBeInTheDocument();
    expect(screen.getByText('0 Members')).toBeInTheDocument();
    expect(screen.getByText('3 Members')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Grid view' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'List view' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open actions for Project A' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open actions for Project B' })).toBeInTheDocument();
    expect(projectAPI.list).toHaveBeenCalledWith(
      't1',
      expect.objectContaining({
        page: 1,
        page_size: 20,
        visibility: 'all',
      })
    );
  });

  it('uses the route tenant id when the tenant store is still stale', async () => {
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: { id: 'tenant-store-old', max_storage: 1024 },
    } as any);

    const mockProjects: Project[] = [
      {
        id: 'project-route',
        tenant_id: 'tenant-route-new',
        name: 'Route Tenant Project',
        description: 'Route scoped project',
        owner_id: 'user1',
        member_ids: [],
        memory_rules: {
          max_episodes: 1000,
          retention_days: 30,
          auto_refresh: true,
          refresh_interval: 300,
        },
        graph_config: {
          max_nodes: 500,
          max_edges: 1000,
          similarity_threshold: 0.8,
          community_detection: true,
        },
        is_public: true,
        created_at: '2024-01-01T00:00:00Z',
        stats: {
          memory_count: 0,
          storage_used: 0,
          node_count: 0,
          member_count: 0,
          last_active: null,
        },
      },
    ];

    vi.mocked(projectAPI.list).mockResolvedValue({
      projects: mockProjects,
      total: 1,
      page: 1,
      page_size: 20,
    });

    render(
      <Routes>
        <Route path="/tenant/:tenantId/projects" element={<ProjectList />} />
      </Routes>,
      { route: '/tenant/tenant-route-new/projects' }
    );

    const projectLink = await screen.findByRole('link', { name: 'Route Tenant Project' });

    expect(projectAPI.list).toHaveBeenCalledWith(
      'tenant-route-new',
      expect.objectContaining({
        page: 1,
        page_size: 20,
      })
    );
    expect(projectLink).toHaveAttribute(
      'href',
      '/tenant/tenant-route-new/project/project-route'
    );
    expect(screen.getAllByRole('link', { name: 'Create New Project' })[0]).toHaveAttribute(
      'href',
      '/tenant/tenant-route-new/projects/new'
    );
  });

  it('filters projects by visibility and owner', async () => {
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: { id: 't1', max_storage: 1024 },
    } as any);

    const mockProjects: Project[] = [
      {
        id: 'p1',
        tenant_id: 't1',
        name: 'Public Project',
        description: 'Public',
        owner_id: 'user1',
        member_ids: [],
        memory_rules: {
          max_episodes: 1000,
          retention_days: 30,
          auto_refresh: true,
          refresh_interval: 300,
        },
        graph_config: {
          max_nodes: 500,
          max_edges: 1000,
          similarity_threshold: 0.8,
          community_detection: true,
        },
        is_public: true,
        created_at: '2024-01-01T00:00:00Z',
      },
      {
        id: 'p2',
        tenant_id: 't1',
        name: 'Private Project',
        description: 'Private',
        owner_id: 'user2',
        member_ids: [],
        memory_rules: {
          max_episodes: 1000,
          retention_days: 30,
          auto_refresh: true,
          refresh_interval: 300,
        },
        graph_config: {
          max_nodes: 500,
          max_edges: 1000,
          similarity_threshold: 0.8,
          community_detection: true,
        },
        is_public: false,
        created_at: '2024-01-01T00:00:00Z',
      },
    ];

    vi.mocked(projectAPI.list).mockResolvedValue({
      projects: mockProjects,
      total: 2,
      page: 1,
      page_size: 10,
    });

    render(<ProjectList />);

    await waitFor(() => {
      expect(screen.getByText('Public Project')).toBeInTheDocument();
      expect(screen.getByText('Private Project')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('tenant.projects.filters.visibilityLabel'), {
      target: { value: 'private' },
    });

    await waitFor(() => {
      expect(screen.queryByText('Public Project')).not.toBeInTheDocument();
      expect(screen.getByText('Private Project')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('tenant.projects.filters.ownerLabel'), {
      target: { value: 'user1' },
    });

    await waitFor(() => {
      expect(screen.queryByText('Public Project')).not.toBeInTheDocument();
      expect(screen.queryByText('Private Project')).not.toBeInTheDocument();
    });
  });

  it('renders empty state', async () => {
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: { id: 't1', max_storage: 1024 },
    } as any);

    vi.mocked(projectAPI.list).mockResolvedValue({
      projects: [],
      total: 0,
      page: 1,
      page_size: 10,
    });

    render(<ProjectList />);

    await waitFor(() => {
      expect(screen.getByText('Create New Project')).toBeInTheDocument();
    });
  });

  it('requests server-side search and filters', async () => {
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: { id: 't1', max_storage: 1024 },
    } as any);

    vi.mocked(projectAPI.list).mockResolvedValue({
      projects: [],
      total: 0,
      page: 1,
      page_size: 20,
      owner_ids: ['user1', 'user2'],
    });

    render(<ProjectList />);

    await waitFor(() => {
      expect(projectAPI.list).toHaveBeenCalled();
    });

    fireEvent.change(screen.getByPlaceholderText('Search by project name, ID, or owner...'), {
      target: { value: 'alpha' },
    });
    fireEvent.change(screen.getByLabelText('tenant.projects.filters.visibilityLabel'), {
      target: { value: 'private' },
    });
    fireEvent.change(screen.getByLabelText('tenant.projects.filters.ownerLabel'), {
      target: { value: 'user2' },
    });

    await waitFor(() => {
      expect(projectAPI.list).toHaveBeenCalledWith(
        't1',
        expect.objectContaining({
          page: 1,
          page_size: 20,
          search: 'alpha',
          visibility: 'private',
          owner_id: 'user2',
        })
      );
    });
  });

  it('requests the next server page from the pagination footer', async () => {
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: { id: 't1', max_storage: 1024 },
    } as any);

    vi.mocked(projectAPI.list).mockResolvedValue({
      projects: [
        {
          id: 'p1',
          tenant_id: 't1',
          name: 'Project A',
          description: 'Desc A',
          owner_id: 'user1',
          member_ids: [],
          memory_rules: {
            max_episodes: 1000,
            retention_days: 30,
            auto_refresh: true,
            refresh_interval: 300,
          },
          graph_config: {
            max_nodes: 500,
            max_edges: 1000,
            similarity_threshold: 0.8,
            community_detection: true,
          },
          is_public: true,
          created_at: '2024-01-01T00:00:00Z',
        },
      ],
      total: 45,
      page: 1,
      page_size: 20,
      owner_ids: ['user1'],
    });

    render(<ProjectList />);

    await waitFor(() => {
      expect(screen.getByText('Project A')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));

    await waitFor(() => {
      expect(projectAPI.list).toHaveBeenCalledWith(
        't1',
        expect.objectContaining({
          page: 2,
          page_size: 20,
          visibility: 'all',
        })
      );
    });
  });
});
