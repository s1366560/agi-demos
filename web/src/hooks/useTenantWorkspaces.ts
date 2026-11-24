import { useQuery } from '@tanstack/react-query';

import { optionalBusinessService } from '@/services/optionalBusinessService';
import { projectService } from '@/services/projectService';

interface WorkspaceReference {
  id: string;
  tenant_id: string;
  project_id: string;
  is_archived: boolean;
}

const workspacePackage = 'memstack-workspace';

function scopedWorkspace(row: unknown, tenant: string, project: string): row is WorkspaceReference {
  return (
    typeof row === 'object' &&
    row !== null &&
    'id' in row &&
    typeof row.id === 'string' &&
    'tenant_id' in row &&
    row.tenant_id === tenant &&
    'project_id' in row &&
    row.project_id === project &&
    'is_archived' in row &&
    typeof row.is_archived === 'boolean'
  );
}

async function projectWorkspaces(tenantId: string, projectId: string) {
  const scope = { tenantId, projectId };
  const release = await optionalBusinessService.projection(workspacePackage, scope);
  if (!release.actual_digest || !release.commands.includes('list-directory')) return [];
  const items: WorkspaceReference[] = [];
  const limit = 100;
  for (let offset = 0; ; offset += limit) {
    const { rows } = await optionalBusinessService.command(
      workspacePackage,
      scope,
      'list-directory',
      release.actual_digest,
      { offset, limit, cards: true }
    );
    if (!Array.isArray(rows)) throw new Error('Invalid workspace directory');
    for (const row of rows) {
      if (scopedWorkspace(row, tenantId, projectId) && !row.is_archived) items.push(row);
    }
    if (rows.length < limit) return items;
  }
}

/** Resolve workspace IDs for tenant trust policies through each project's running release. */
export function useTenantWorkspaces(tenantId: string | null | undefined) {
  return useQuery({
    queryKey: ['tenant-workspaces', tenantId ?? 'none'],
    enabled: Boolean(tenantId),
    staleTime: 60_000,
    queryFn: async () => {
      if (!tenantId) return [];
      const projects = await projectService.listProjects(tenantId);
      const results = await Promise.allSettled(
        projects.map(({ id }) => projectWorkspaces(tenantId, id))
      );
      return results.flatMap((result) => (result.status === 'fulfilled' ? result.value : []));
    },
  });
}
