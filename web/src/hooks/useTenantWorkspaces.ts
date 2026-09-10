import { useQuery } from '@tanstack/react-query';

import { projectService } from '@/services/projectService';
import { workspaceService } from '@/services/workspaceService';

import type { Workspace } from '@/types/workspace';

/**
 * Lists every workspace a tenant admin can see, across all of the tenant's
 * projects.
 *
 * Trust admin pages (trust policies / decision records) are tenant-scoped but
 * the backend binds trust records to real workspaces, so they need an actual
 * workspace id before querying — the legacy `'default'` placeholder 404s.
 * Workspaces only exist under projects, hence the two-step fan-out.
 */
export function useTenantWorkspaces(tenantId: string | null | undefined) {
  return useQuery<Workspace[]>({
    queryKey: ['tenant-workspaces', tenantId ?? 'none'],
    enabled: Boolean(tenantId),
    staleTime: 60_000,
    queryFn: async () => {
      const projects = await projectService.listProjects(tenantId as string);
      const lists = await Promise.all(
        projects.map(async (project) => {
          try {
            return await workspaceService.listByProject(tenantId as string, project.id);
          } catch {
            // A single failing project must not hide the other workspaces.
            return [];
          }
        })
      );
      return lists.flat().filter((workspace) => !workspace.is_archived);
    },
  });
}
