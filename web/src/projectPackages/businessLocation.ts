export function businessLocation(
  pathname: string,
  tenant: string,
  project: string,
  plugin: string
) {
  return {
    pathname,
    search: new URLSearchParams({ tenant, project, businessPackage: plugin }).toString(),
  };
}

type Project = { id: string; tenant_id: string };

export function businessRouteScope(path: string, query: URLSearchParams, current?: Project | null) {
  const [, root, owner, section, scopedProject] = path.split('/');
  const plugin = query.get('businessPackage');
  if (
    [
      'login',
      'logout',
      'auth',
      'device',
      'invite',
      'force-change-password',
      'plugins',
      'settings',
      'recovery',
    ].includes(root ?? '')
  )
    return null;
  if (
    root === 'tenant' &&
    ['plugins', 'users', 'profile', 'org-settings', 'settings', 'audit-logs', 'projects'].includes(
      section ?? ''
    )
  )
    return null;
  if (['tenant', 'project', 'businessPackage'].some((name) => query.getAll(name).length > 1))
    return null;
  const scopedTenant = root === 'tenant' ? owner : null;
  const pathProject =
    root === 'project' ? owner : root === 'tenant' && section === 'project' ? scopedProject : null;
  if (
    (scopedTenant && query.has('tenant') && query.get('tenant') !== scopedTenant) ||
    (pathProject && query.has('project') && query.get('project') !== pathProject)
  )
    return null;
  const project =
    pathProject ||
    query.get('project') ||
    (scopedTenant && current?.tenant_id === scopedTenant ? current.id : null);
  const tenant =
    scopedTenant || query.get('tenant') || (current?.id === project ? current?.tenant_id : null);
  return tenant && project && (plugin || pathProject || scopedTenant)
    ? { tenant, project, plugin }
    : null;
}
