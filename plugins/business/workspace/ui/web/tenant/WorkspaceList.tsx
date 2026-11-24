import { useEffect, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { useCurrentProject, useProjectStore } from '@/stores/project';
import { useCurrentTenant } from '@/stores/tenant';
import {
  useWorkspaceActions,
  useWorkspaceError,
  useWorkspaceLoading,
  useWorkspaces,
} from '../stores/workspace';
import {
  workspaceObjectiveService,
  workspacePlanService,
  workspaceTaskService,
} from '../services/workspaceService';
import { resolveWorkspaceSummary } from './resolveWorkspaceSummary';
import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import { formatDistanceToNow } from '@/utils/date';
import { WorkspaceListView, type ObjectiveSummary } from './WorkspaceListView';
const PROJECT_CONTEXT_PAGE_SIZE = 25;

async function loadWorkspaceSummary(
  tenantId: string,
  projectId: string,
  workspaceId: string
): Promise<ObjectiveSummary> {
  const [objectivesResult, planResult] = await Promise.allSettled([
    workspaceObjectiveService.list(tenantId, projectId, workspaceId),
    workspacePlanService.getSnapshot(workspaceId, {
      outboxLimit: 0,
      eventLimit: 0,
      includeDetails: false,
      recoverStaleAttempts: false,
    }),
  ]);
  return resolveWorkspaceSummary(
    objectivesResult.status === 'fulfilled' ? objectivesResult.value : null,
    planResult.status === 'fulfilled' ? planResult.value : null,
    () => workspaceTaskService.list(workspaceId)
  );
}

export function WorkspaceList() {
  const params = useParams<{ tenantId?: string; projectId?: string }>();
  const currentTenant = useCurrentTenant();
  const currentProject = useCurrentProject();
  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);
  const workspaces = useWorkspaces();
  const isLoading = useWorkspaceLoading();
  const workspaceError = useWorkspaceError();
  const { loadWorkspaces } = useWorkspaceActions();

  const tenantId = params.tenantId ?? currentTenant?.id ?? null;
  const tenantCurrentProject =
    tenantId && currentProject?.tenant_id === tenantId ? currentProject : null;
  const tenantProjects = useMemo(
    () => (tenantId ? projects.filter((project) => project.tenant_id === tenantId) : []),
    [projects, tenantId]
  );
  const projectId = params.projectId ?? tenantCurrentProject?.id ?? tenantProjects[0]?.id ?? null;
  useEffect(() => {
    if (!tenantId || params.projectId || tenantCurrentProject || tenantProjects.length > 0) return;
    void listProjects(tenantId, { page: 1, page_size: PROJECT_CONTEXT_PAGE_SIZE }).catch(() => {
      // ignore and keep empty-state guidance visible
    });
  }, [tenantId, params.projectId, tenantCurrentProject, tenantProjects.length, listProjects]);

  return (
    <WorkspaceListView
      tenantId={tenantId}
      projectId={projectId}
      tenantName={currentTenant?.name}
      projectName={tenantCurrentProject?.name}
      workspaces={workspaces}
      isLoading={isLoading}
      workspaceError={workspaceError}
      loadWorkspaces={loadWorkspaces}
      loadWorkspaceSummary={loadWorkspaceSummary}
      loadingView={<SkeletonLoader type="card" count={6} />}
      formatDistanceToNow={formatDistanceToNow}
      workspacePath={(id) =>
        `/tenant/${tenantId}/project/${projectId}/blackboard?workspaceId=${id}`
      }
    />
  );
}
