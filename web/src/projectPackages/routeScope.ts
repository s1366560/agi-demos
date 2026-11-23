/** Resolve identity-bearing legacy links against projects returned for the signed-in user. */
export function matchingPageProjects<T extends { tenant_id: string; project_id: string }>(
  projects: readonly T[],
  pathname: string,
  query: URLSearchParams
): T[] {
  if (query.getAll('tenant').length > 1 || query.getAll('project').length > 1) return [];
  let tenantId = query.get('tenant');
  let projectId = query.get('project');
  const parts = pathname.split('/');
  const tenant = parts[1] === 'tenant' ? parts[2] : undefined;
  const project =
    parts[1] === 'project'
      ? parts[2]
      : parts[1] === 'tenant' && parts[3] === 'project'
        ? parts[4]
        : undefined;
  try {
    if (tenant !== undefined) {
      const identity = decodeURIComponent(tenant);
      if (!identity || (tenantId !== null && tenantId !== identity)) return [];
      tenantId = identity;
    }
    if (project !== undefined) {
      const identity = decodeURIComponent(project);
      if (!identity || (projectId !== null && projectId !== identity)) return [];
      projectId = identity;
    }
  } catch {
    return [];
  }
  return projects.filter(
    (item) =>
      (tenantId === null || item.tenant_id === tenantId) &&
      (projectId === null || item.project_id === projectId)
  );
}
