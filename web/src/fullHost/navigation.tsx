import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { createPath, useLocation } from 'react-router-dom';
import { menuPath, type PackagePage } from '../../../agi-stack/packages/plugin-slots/src/richPage';
import { scopedPageLocation } from '../../../agi-stack/packages/plugin-slots/src/pageLocation';
import {
  packageBase,
  packageScope,
} from '../../../agi-stack/packages/plugin-marketplace-ui/src/pluginMarketTypes';
import { useWebPackageSession } from '../projectPackages/useWebPackageSession';
import { useAuthStore } from '../stores/auth';
import { useProjectStore } from '../stores/project';
import { useTenantStore } from '../stores/tenant';
import type { DerivedNavigationItem } from '../config/navigation';

export interface LinkItem {
  id: string;
  label: string;
  path: string;
  plugin?: string;
  digest?: string;
  projectId?: string;
  commands?: readonly string[];
}
const Navigation = createContext<{ tenant: string; project: string | null; items: LinkItem[] }>({
  tenant: '',
  project: null,
  items: [],
});
export const useFullNavigation = () => useContext(Navigation);

interface Release {
  plugin_id: string;
  actual_digest: string | null;
  status: string;
  commands?: string[];
  pages?: PackagePage[];
}

export function FullNavigation({ children }: { children: ReactNode }) {
  const location = useLocation();
  const { t } = useTranslation();
  const token = useAuthStore((s) => s.token);
  const session = useWebPackageSession(token);
  const currentTenant = useTenantStore((s) => s.currentTenant);
  const currentProject = useProjectStore((s) => s.currentProject);
  const query = new URLSearchParams(location.search);
  const [, root, owner, section, pathProject] = location.pathname.split('/');
  const tenant =
    (root === 'tenant' && section ? owner : null) || query.get('tenant') || currentTenant?.id || '';
  const explicitProject =
    (root === 'tenant' && section === 'project'
      ? pathProject
      : root === 'project'
        ? owner
        : null) ||
    query.get('projectId') ||
    query.get('project');
  const project =
    explicitProject || (currentProject?.tenant_id === tenant ? currentProject.id : null);
  const [result, setResult] = useState<{
    tenant: string;
    project: string | null;
    token: string;
    items: LinkItem[];
  } | null>(null);
  const items =
    result?.tenant === tenant && result.project === project && result.token === token
      ? result.items
      : [];
  useEffect(() => {
    if (!tenant || !token) return;
    const controller = new AbortController();
    const load = async (projectId: string | null) => {
      const params = new URLSearchParams(packageScope(tenant, projectId));
      const releases = await session.transport<{ items: Release[] }>(
        packageBase(projectId) + '/?' + params,
        { signal: controller.signal }
      );
      return releases.items.flatMap((release) =>
        release.actual_digest && ['enabled', 'failed'].includes(release.status)
          ? (release.pages ?? []).flatMap((page) => {
              if (!page.targets.includes('web') || page.contributes_to) return [];
              const route = page.routes
                .map((pattern) => menuPath(pattern, { tenantId: tenant, projectId }))
                .find(Boolean);
              if (!route) return [];
              const path = scopedPageLocation(route, {
                tenant,
                ...(projectId ? { project: projectId } : { packageScope: 'tenant' }),
                businessPackage: release.plugin_id,
              });
              return [
                {
                  id: [projectId || tenant, release.plugin_id, page.id].join('/'),
                  label: page.title,
                  path: createPath(path),
                  plugin: release.plugin_id,
                  digest: release.actual_digest!,
                  ...(projectId ? { projectId } : {}),
                  commands: release.commands ?? [],
                },
              ];
            })
          : []
      );
    };
    let refreshing = false;
    const identity = token;
    async function refresh() {
      if (refreshing) return;
      refreshing = true;
      const results = await Promise.allSettled([load(null), ...(project ? [load(project)] : [])]);
      if (!controller.signal.aborted)
        setResult({
          tenant,
          project,
          token: identity,
          items: results.flatMap((result) => (result.status === 'fulfilled' ? result.value : [])),
        });
      refreshing = false;
    }
    void refresh();
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 5000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [tenant, project, token, session.transport]);
  const base = '/tenant/' + encodeURIComponent(tenant);
  const links = useMemo(
    () =>
      tenant
        ? [
            { id: 'projects', label: t('nav.projects', 'Projects'), path: base + '/projects' },
            {
              id: 'plugins',
              label: t('nav.plugins', 'Plugins'),
              path:
                base + '/plugins' + (project ? '?projectId=' + encodeURIComponent(project) : ''),
            },
            ...items,
            { id: 'users', label: t('nav.users', 'Users'), path: base + '/users' },
            {
              id: 'audit-logs',
              label: t('nav.auditLogs', 'Audit logs'),
              path: base + '/audit-logs',
            },
            {
              id: 'org-settings',
              label: t('nav.orgSettings', 'Organization settings'),
              path: base + '/org-settings',
            },
            { id: 'settings', label: t('nav.settings', 'Settings'), path: base + '/settings' },
          ]
        : [],
    [base, tenant, project, items, t]
  );
  return (
    <Navigation.Provider value={{ tenant, project, items: links }}>{children}</Navigation.Provider>
  );
}

export function useHeaderItems(): readonly DerivedNavigationItem[] {
  const { items } = useFullNavigation();
  return items.map((i) => ({
    ...i,
    context: 'tenant',
    displayRole: 'top-nav',
    relativePath: i.path,
    routeFamily: 'tenant',
    groupId: 'tenant-core-operations',
    groupLabel: 'nav.navigation',
  }));
}
