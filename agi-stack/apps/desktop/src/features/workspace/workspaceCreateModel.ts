import type { WorkspaceSummary } from '../../types';
export * from '@business/workspace/ui/desktop/workspace/workspaceCreateModel';

export function mergeWorkspaceIntoProjectCatalog(
  catalog: Record<string, WorkspaceSummary[]>,
  workspace: WorkspaceSummary,
): Record<string, WorkspaceSummary[]> {
  const projectId = workspace.project_id?.trim();
  if (!projectId) return catalog;
  const current = catalog[projectId] ?? [];
  return {
    ...catalog,
    [projectId]: [workspace, ...current.filter((candidate) => candidate.id !== workspace.id)],
  };
}
