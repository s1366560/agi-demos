/**
 * useProjectBasePath - Shared hook for computing tenant-relative project base paths.
 *
 * Returns the canonical base path for the current project within the tenant route tree.
 * All project page links/navigations should use this instead of hard-coding `/project/${id}`.
 *
 * @example
 * const { projectBasePath } = useProjectBasePath();
 * // -> "/tenant/abc123/project/proj456"
 * navigate(`${projectBasePath}/memories`);
 */

import { useParams } from 'react-router-dom';

interface ProjectBasePathResult {
  projectBasePath: string;
  tenantBasePath: string;
  projectId: string | undefined;
  tenantId: string | undefined;
}

export function useProjectBasePath(): ProjectBasePathResult {
  const { tenantId, projectId } = useParams();

  const tenantBasePath = tenantId ? `/tenant/${tenantId}` : '/tenant';
  const projectBasePath = projectId
    ? `${tenantBasePath}/project/${projectId}`
    : tenantBasePath;

  return {
    projectBasePath,
    tenantBasePath,
    projectId,
    tenantId,
  };
}
