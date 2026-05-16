import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ProjectList } from '../../../pages/tenant/ProjectList';
import { projectAPI } from '../../../services/api';
import { useTenantStore } from '../../../stores/tenant';
import { screen, render, waitFor, fireEvent } from '../../utils';

import type { Project } from '../../../types/memory';

vi.mock('../../../stores/tenant');
vi.mock('../../../services/api');

describe('ProjectList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

    expect(screen.queryByText('Public Project')).not.toBeInTheDocument();
    expect(screen.getByText('Private Project')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('tenant.projects.filters.ownerLabel'), {
      target: { value: 'user1' },
    });

    expect(screen.queryByText('Public Project')).not.toBeInTheDocument();
    expect(screen.queryByText('Private Project')).not.toBeInTheDocument();
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
});
