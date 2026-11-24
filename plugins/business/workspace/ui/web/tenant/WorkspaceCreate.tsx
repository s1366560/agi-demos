import { useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { FolderKanban } from 'lucide-react';
import { useCurrentProject, useProjectStore } from '@/stores/project';
import { useCurrentTenant } from '@/stores/tenant';
import { ApiError } from '@/services/client/ApiError';
import { useUnsavedChangesWarning } from '@/hooks/useUnsavedChangesWarning';
import { confirmAction } from '@/utils/confirmAction';
import { EmptyStateSimple } from '@/components/shared/ui/EmptyStateVariant';
import { useWorkspaceActions } from '../stores/workspace';
import { WorkspaceCreateView } from './WorkspaceCreateView';

const PROJECT_CONTEXT_PAGE_SIZE = 25;

export function WorkspaceCreate() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const params = useParams<{ tenantId?: string; projectId?: string }>();
  const currentTenant = useCurrentTenant();
  const currentProject = useCurrentProject();
  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);
  const { createWorkspace } = useWorkspaceActions();

  const tenantId = params.tenantId ?? currentTenant?.id ?? null;
  const tenantCurrentProject =
    tenantId && currentProject?.tenant_id === tenantId ? currentProject : null;
  const tenantProjects = useMemo(
    () => (tenantId ? projects.filter((project) => project.tenant_id === tenantId) : []),
    [projects, tenantId]
  );
  const projectId = params.projectId ?? tenantCurrentProject?.id ?? tenantProjects[0]?.id ?? null;
  const listPath =
    tenantId && projectId
      ? `/tenant/${tenantId}/project/${projectId}/workspaces`
      : tenantId
        ? `/tenant/${tenantId}/workspaces`
        : '/tenant/workspaces';

  useEffect(() => {
    if (!tenantId || params.projectId || tenantCurrentProject || tenantProjects.length > 0) return;
    void listProjects(tenantId, { page: 1, page_size: PROJECT_CONTEXT_PAGE_SIZE }).catch(() => {
      // Keep the empty-state guidance visible when project loading fails.
    });
  }, [tenantId, params.projectId, tenantCurrentProject, tenantProjects.length, listProjects]);

  if (!tenantId || !projectId) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <EmptyStateSimple
          icon={FolderKanban}
          title={t('tenant.workspaceList.noContextTitle', 'Pick a tenant and project')}
          description={t(
            'tenant.workspaceList.noContextDescription',
            'Workspaces are scoped to a project. Select a tenant and project to continue.'
          )}
        />
      </div>
    );
  }

  return <WorkspaceCreateView
    createWorkspace={data => createWorkspace(tenantId, projectId, data)}
    onCreated={id => { void navigate(`/tenant/${tenantId}/project/${projectId}/blackboard?workspaceId=${id}`); }}
    onBack={() => { void navigate(listPath); }}
    confirmDiscard={title => confirmAction({ title, danger: true })}
    isDuplicateName={error => error instanceof ApiError && error.statusCode === 409 && error.code === 'CONFLICT'}
    useUnsavedChangesWarning={useUnsavedChangesWarning}
  />;
}
