import { scopedPageLocation } from '../../../agi-stack/packages/plugin-slots/src/pageLocation';

export function businessLocation(
  pathname: string,
  tenant: string,
  project: string | null,
  plugin: string
) {
  return scopedPageLocation(pathname, {
    tenant,
    ...(project ? { project } : { packageScope: 'tenant' }),
    businessPackage: plugin,
  });
}

type Project = { id: string; tenant_id: string };

export function businessRouteScope(path: string, query: URLSearchParams, current?: Project | null) {
  if (path === '/tenant/workspaces/new') return null;
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
  if (['tenant', 'project', 'projectId', 'businessPackage'].some((name) => query.getAll(name).length > 1))
    return null;
  const requestedProject = query.get('project') ?? query.get('projectId');
  if (query.has('project') && query.has('projectId') && query.get('project') !== query.get('projectId'))
    return null;
  const scopedTenant = root === 'tenant' ? owner : null;
  const pathProject =
    root === 'project' ? owner : root === 'tenant' && section === 'project' ? scopedProject : null;
  if (
    (scopedTenant && query.has('tenant') && query.get('tenant') !== scopedTenant) ||
    (pathProject && requestedProject !== null && requestedProject !== pathProject)
  )
    return null;
  const project =
    pathProject ||
    requestedProject ||
    (scopedTenant && current?.tenant_id === scopedTenant ? current.id : null);
  const tenant =
    scopedTenant || query.get('tenant') || (current?.id === project ? current?.tenant_id : null);
  return tenant && project && (plugin || pathProject || scopedTenant)
    ? { tenant, project, plugin }
    : null;
}

/** A bookmark may select a tenant release before the user selects any project. */
export function tenantPageScope(path: string, query: URLSearchParams) {
  if (path === '/tenant/workspaces/new') return null;
  const [, root, owner, section] = path.split('/');
  if (root !== 'tenant' || !owner || !section || section === 'project') return null;
  if (
    !(section === 'org-settings' && path.split('/').slice(4).join('/') === 'clusters') &&
    ['projects', 'users', 'plugins', 'org-settings', 'settings', 'profile', 'audit-logs'].includes(
      section
    )
  )
    return null;
  if (['tenant', 'businessPackage', 'packageScope'].some((key) => query.getAll(key).length > 1))
    return null;
  if (query.has('project') || (query.has('tenant') && query.get('tenant') !== owner)) return null;
  return owner;
}
