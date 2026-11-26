import { scopedPageLocation, splitPageLocation } from '../../../../packages/plugin-slots/src/pageLocation';
import { menuPath, type PackagePage } from '../../../../packages/plugin-slots/src/richPage';
import {
  groupWorkbenchHeader,
  layoutWorkbenchHeader,
  type WorkbenchHeaderLink,
  type WorkbenchHeaderSlot,
} from '../../../../packages/plugin-slots/src/workbenchHeader';
import { buildWorkbenchSlots, tenantBase } from './workbenchCatalog';

export type WorkbenchPageSource = {
  readonly projectId: string | null;
  readonly pluginId: string;
  readonly page: PackagePage;
};

export type WorkbenchSurface = 'market' | 'host' | 'page' | 'empty';

export type HostSection =
  | 'projects'
  | 'plugins'
  | 'users'
  | 'audit-logs'
  | 'settings'
  | 'org-settings';

export function shellLanding(tenant: string): string {
  return tenantBase(tenant) + '/projects';
}

export function isShellRoot(pathname: string, tenant: string): boolean {
  return pathname === '' || pathname === '/' || pathname === tenantBase(tenant);
}

export function workbenchContext(pathname: string): 'tenant' | 'project' {
  return pathname.includes('/project/') ? 'project' : 'tenant';
}

/** Destinations the desktop host serves itself, on the same paths as the cloud host. */
export function desktopHostLinks(tenant: string, project: string | null): WorkbenchHeaderLink[] {
  const base = tenantBase(tenant);
  return [
    { id: 'projects', label: 'nav.projects', path: `${base}/projects` },
    {
      id: 'plugins',
      label: 'nav.plugins',
      path: `${base}/plugins${project ? '?projectId=' + encodeURIComponent(project) : ''}`,
    },
    { id: 'users', label: 'nav.users', path: `${base}/users` },
    { id: 'audit-logs', label: 'nav.auditLogs', path: `${base}/audit-logs` },
    { id: 'org-settings', label: 'nav.orgSettings', path: `${base}/org-settings/info` },
    { id: 'settings', label: 'nav.settings', path: `${base}/settings` },
  ];
}

function scopedPaths(page: PackagePage, tenant: string, projectId: string | null, pluginId: string) {
  return page.routes.flatMap((pattern) => {
    const route = menuPath(pattern, { tenantId: tenant, projectId });
    if (!route) return [];
    const location = scopedPageLocation(route, {
      tenant,
      ...(projectId ? { project: projectId } : { packageScope: 'tenant' }),
      businessPackage: pluginId,
    });
    return [location.pathname + (location.search ? '?' + location.search : '')];
  });
}

/** Signed pages the header can open. Slot contributions stay inside their host page. */
export function installedWorkbenchLinks(
  entries: readonly WorkbenchPageSource[],
  tenant: string,
): WorkbenchHeaderLink[] {
  return entries.flatMap((entry) => {
    if (entry.page.contributes_to || !entry.page.targets.includes('desktop-renderer')) return [];
    const paths = scopedPaths(entry.page, tenant, entry.projectId, entry.pluginId);
    const [first] = paths;
    if (!first) return [];
    return [
      {
        id: [entry.projectId || tenant, entry.pluginId, entry.page.id].join('/'),
        label: entry.page.title,
        path: first,
        paths,
        ...(entry.projectId ? { projectId: entry.projectId } : {}),
      },
    ];
  });
}

export function combineWorkbenchLinks(
  entries: readonly WorkbenchPageSource[],
  tenant: string,
  project: string | null,
): WorkbenchHeaderLink[] {
  const installed = installedWorkbenchLinks(entries, tenant);
  return desktopHostLinks(tenant, project).flatMap((link) =>
    link.id === 'plugins' ? [link, ...installed] : [link],
  );
}

export function assembleWorkbenchHeader(
  entries: readonly WorkbenchPageSource[],
  tenant: string,
  project: string | null,
  pathname: string,
): WorkbenchHeaderSlot[] {
  const context = workbenchContext(pathname);
  return layoutWorkbenchHeader(
    combineWorkbenchLinks(entries, tenant, project),
    buildWorkbenchSlots(tenant, project, context),
    context,
  );
}

export function workbenchHeaderGroups(items: readonly WorkbenchHeaderSlot[]) {
  return groupWorkbenchHeader(items);
}

export function headerItemActive(item: WorkbenchHeaderSlot, pathname: string): boolean {
  const section = item.path.split('?')[0] ?? item.path;
  if (pathname === section) return true;
  // Extras keep their full address as relativePath. Only catalog sections adopt nested routes.
  const relative = item.relativePath;
  if (
    !relative ||
    relative.includes('?') ||
    relative.startsWith('/tenant') ||
    relative.startsWith('/project') ||
    relative.startsWith('/agent')
  )
    return false;
  const segment = relative.split('/').filter(Boolean)[0];
  if (!segment) return false;
  const comparable = relative.startsWith('/') ? relative : '/' + relative;
  if (!section.endsWith(comparable)) return false;
  const scope = section.slice(0, section.length - comparable.length);
  const root = `${scope.replace(/\/$/, '')}/${segment}`;
  return pathname === root || pathname.startsWith(root + '/');
}

export function hostSection(pathname: string, tenant: string): HostSection | null {
  const base = tenantBase(tenant);
  if (pathname !== base && !pathname.startsWith(base + '/')) return null;
  const rest = pathname.slice(base.length);
  if (rest === '/projects' || rest.startsWith('/projects/')) return 'projects';
  if (rest === '/plugins' || rest.startsWith('/plugins/')) return 'plugins';
  if (rest === '/users' || rest.startsWith('/users/')) return 'users';
  if (rest === '/audit-logs' || rest.startsWith('/audit-logs/')) return 'audit-logs';
  if (rest === '/settings' || rest.startsWith('/settings/')) return 'settings';
  if (rest === '/org-settings' || rest.startsWith('/org-settings/')) return 'org-settings';
  return null;
}

/**
 * Host administration wins on its own paths. A signed page nested under organization
 * settings, such as clusters, keeps the package page.
 */
export function selectWorkbenchSurface(
  pathname: string,
  tenant: string,
  signed: boolean,
): WorkbenchSurface {
  const section = hostSection(pathname, tenant);
  if (section === 'plugins') return 'market';
  if (section && section !== 'org-settings') return 'host';
  if (section === 'org-settings' && !signed) return 'host';
  if (signed) return 'page';
  return 'empty';
}

export function pathnameOf(address: string): string {
  return splitPageLocation(address).pathname;
}
