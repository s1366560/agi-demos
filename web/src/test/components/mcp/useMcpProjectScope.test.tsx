import { renderHook } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { useMcpProjectScope } from '@/components/mcp/useMcpProjectScope';
import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import type { Project, Tenant } from '@/types/memory';

const makeProject = (id: string, tenantId: string, name: string): Project =>
  ({
    id,
    tenant_id: tenantId,
    name,
    owner_id: 'user-1',
    member_ids: [],
    memory_rules: {},
    graph_config: {},
    is_public: false,
    created_at: '2026-01-01T00:00:00Z',
  }) as Project;

const makeTenant = (id: string): Tenant =>
  ({
    id,
    name: id,
    owner_id: 'user-1',
    plan: 'free',
    max_projects: 10,
    max_users: 10,
    max_storage: 1024,
    created_at: '2026-01-01T00:00:00Z',
  }) as Tenant;

const renderScopedHook = (path: string = '/tenant/tenant-1/mcp-servers') =>
  renderHook(() => useMcpProjectScope(), {
    wrapper: ({ children }) => (
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/tenant/:tenantId/mcp-servers" element={children} />
          <Route path="/mcp-servers" element={children} />
        </Routes>
      </MemoryRouter>
    ),
  });

describe('useMcpProjectScope', () => {
  beforeEach(() => {
    useProjectStore.setState({
      projects: [],
      currentProject: null,
    });
    useTenantStore.setState({
      currentTenant: null,
    });
  });

  it('ignores a current project from another tenant route', () => {
    const tenantProject = makeProject('project-tenant-1', 'tenant-1', 'Tenant 1 Project');
    const staleProject = makeProject('project-tenant-2', 'tenant-2', 'Tenant 2 Project');
    useProjectStore.setState({
      projects: [tenantProject, staleProject],
      currentProject: staleProject,
    });

    const { result } = renderScopedHook();

    expect(result.current.tenantId).toBe('tenant-1');
    expect(result.current.projectId).toBeUndefined();
    expect(result.current.currentProject).toBeNull();
    expect(result.current.projects).toEqual([tenantProject]);
  });

  it('uses the current project when it belongs to the route tenant', () => {
    const tenantProject = makeProject('project-tenant-1', 'tenant-1', 'Tenant 1 Project');
    useProjectStore.setState({
      projects: [tenantProject],
      currentProject: tenantProject,
    });

    const { result } = renderScopedHook();

    expect(result.current.projectId).toBe('project-tenant-1');
    expect(result.current.currentProject).toBe(tenantProject);
    expect(result.current.projects).toEqual([tenantProject]);
  });

  it('falls back to current tenant outside tenant routes', () => {
    const tenantProject = makeProject('project-tenant-1', 'tenant-1', 'Tenant 1 Project');
    const otherProject = makeProject('project-tenant-2', 'tenant-2', 'Tenant 2 Project');
    useTenantStore.setState({ currentTenant: makeTenant('tenant-1') });
    useProjectStore.setState({
      projects: [tenantProject, otherProject],
      currentProject: tenantProject,
    });

    const { result } = renderScopedHook('/mcp-servers');

    expect(result.current.tenantId).toBe('tenant-1');
    expect(result.current.projectId).toBe('project-tenant-1');
    expect(result.current.projects).toEqual([tenantProject]);
  });
});
