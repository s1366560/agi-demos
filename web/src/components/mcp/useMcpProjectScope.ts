import { useMemo } from 'react';

import { useParams } from 'react-router-dom';

import { useShallow } from 'zustand/react/shallow';

import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

export function useMcpProjectScope() {
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string | undefined }>();
  const currentTenantId = useTenantStore((s) => s.currentTenant?.id ?? null);
  const tenantId = routeTenantId || currentTenantId || null;
  const { projects, currentProject } = useProjectStore(
    useShallow((s) => ({
      projects: s.projects,
      currentProject: s.currentProject,
    }))
  );

  const scopedProjects = useMemo(
    () => (tenantId ? projects.filter((project) => project.tenant_id === tenantId) : projects),
    [projects, tenantId]
  );
  const scopedCurrentProject =
    currentProject && (!tenantId || currentProject.tenant_id === tenantId) ? currentProject : null;

  return {
    tenantId,
    projects: scopedProjects,
    currentProject: scopedCurrentProject,
    projectId: scopedCurrentProject?.id,
  };
}
