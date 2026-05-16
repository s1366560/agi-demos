/**
 * Example React Query hook: list projects for a tenant.
 *
 * This is the canonical pattern for new server-state hooks. Legacy code
 * still uses Zustand's useProjectStore; those call sites will migrate
 * gradually. See web/src/ARCHITECTURE.md.
 */
import { useQuery } from '@tanstack/react-query';

import { projectAPI } from '@/services/api';

import type { ProjectListResponse } from '@/types/memory';

export const projectKeys = {
  all: ['projects'] as const,
  list: (tenantId: string) => [...projectKeys.all, 'list', tenantId] as const,
  detail: (tenantId: string, projectId: string) =>
    [...projectKeys.all, 'detail', tenantId, projectId] as const,
};

export function useProjects(tenantId: string | undefined) {
  return useQuery<ProjectListResponse>({
    queryKey: tenantId ? projectKeys.list(tenantId) : projectKeys.all,
    queryFn: () => {
      if (!tenantId) {
        throw new Error('tenantId is required');
      }
      return projectAPI.list(tenantId);
    },
    enabled: !!tenantId,
  });
}
