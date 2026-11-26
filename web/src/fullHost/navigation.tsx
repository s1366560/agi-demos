import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
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
import {
  deriveTopNavigationItems,
  type DerivedNavigationItem,
  type TopNavigationContext,
} from '../config/navigation';

export interface LinkItem {
  id: string;
  label: string;
  path: string;
  /** Every scoped address through which the page can open. */
  paths?: readonly string[];
  plugin?: string;
  digest?: string;
  projectId?: string;
  commands?: readonly string[];
  sidebar?: NonNullable<PackagePage['sidebar']>;
  routes?: readonly string[];
}

/**
 * Section order of the original workbench header. That workbench applies navigation
 * features in identity order, which puts integrations before operations.
 * `headerOrder.test` keeps both lists equal to its header.
 */
const ORIGINAL_HEADER_ORDER: Record<'tenant' | 'project', readonly string[]> = {
  tenant: [
    'acp',
    'agent-bindings',
    'agent-definitions',
    'agent-workspace',
    'agent-configuration',
    'analytics',
    'audit-logs',
    'billing',
    'clusters',
    'dead-letter-queue',
    'decision-records',
    'deploy',
    'events',
    'evolution',
    'genes',
    'instance-templates',
    'instances',
    'mcp-servers',
    'org-settings',
    'overview',
    'patterns',
    'plugins',
    'pool',
    'projects',
    'providers',
    'runtimes',
    'settings',
    'skills',
    'tasks',
    'templates',
    'trust-policies',
    'users',
    'webhooks',
    'workspaces',
  ],
  project: [
    'blackboard',
    'channels',
    'communities',
    'cron-jobs',
    'entities',
    'graph',
    'maintenance',
    'memories',
    'overview',
    'schema',
    'search',
    'settings',
    'team',
    'workspaces',
  ],
};
const Navigation = createContext<{
  tenant: string;
  project: string | null;
  items: LinkItem[];
  invalidate: () => void;
}>({
  tenant: '',
  project: null,
  items: [],
  invalidate: () => {},
});
export const useFullNavigation = () => useContext(Navigation);

const withoutSearch = (path: string) => path.split('?')[0] ?? path;

/** Destinations the host itself serves. Each keeps the path of its original section. */
export function hostLinks(
  tenant: string,
  project: string | null,
  t: (key: string, fallback: string) => string
): LinkItem[] {
  const base = '/tenant/' + encodeURIComponent(tenant);
  return [
    { id: 'projects', label: t('nav.projects', 'Projects'), path: `${base}/projects` },
    {
      id: 'plugins',
      label: t('nav.plugins', 'Plugins'),
      path: `${base}/plugins${project ? '?projectId=' + encodeURIComponent(project) : ''}`,
    },
    { id: 'users', label: t('nav.users', 'Users'), path: `${base}/users` },
    { id: 'audit-logs', label: t('nav.auditLogs', 'Audit logs'), path: `${base}/audit-logs` },
    {
      id: 'org-settings',
      label: t('nav.orgSettings', 'Organization settings'),
      path: `${base}/org-settings/info`,
    },
    { id: 'settings', label: t('nav.settings', 'Settings'), path: `${base}/settings` },
  ];
}

/** Address that owns a section and the pages nested below it. */
function sectionRoot(slot: DerivedNavigationItem): string | null {
  const path = withoutSearch(slot.path);
  const segment = slot.relativePath.split('/').filter(Boolean)[0];
  // The index section owns the whole scope, so it cannot adopt sibling pages.
  if (!segment) return null;
  const scope = path.slice(0, Math.max(0, path.length - slot.relativePath.length));
  return `${scope.replace(/\/$/, '')}/${segment}`;
}

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
  const [generation, setGeneration] = useState(0);
  const invalidate = useCallback(() => {
    setResult(null);
    setGeneration((previous) => previous + 1);
  }, []);
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
              const paths = page.routes.flatMap((pattern) => {
                const route = menuPath(pattern, { tenantId: tenant, projectId });
                if (!route) return [];
                return [
                  createPath(
                    scopedPageLocation(route, {
                      tenant,
                      ...(projectId ? { project: projectId } : { packageScope: 'tenant' }),
                      businessPackage: release.plugin_id,
                    })
                  ),
                ];
              });
              const [first] = paths;
              if (!first) return [];
              return [
                {
                  id: [projectId || tenant, release.plugin_id, page.id].join('/'),
                  label: page.title,
                  path: first,
                  paths,
                  plugin: release.plugin_id,
                  digest: release.actual_digest!,
                  ...(projectId ? { projectId } : {}),
                  commands: release.commands ?? [],
                  ...(page.sidebar && release.status === 'enabled'
                    ? { sidebar: page.sidebar, routes: page.routes }
                    : {}),
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
      if (!controller.signal.aborted) {
        const next = {
          tenant,
          project,
          token: identity,
          items: results.flatMap((result) => (result.status === 'fulfilled' ? result.value : [])),
        };
        setResult((previous) =>
          previous &&
          previous.tenant === tenant &&
          previous.project === project &&
          previous.token === identity &&
          JSON.stringify(previous.items) === JSON.stringify(next.items)
            ? previous
            : next
        );
      }
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
  }, [tenant, project, token, session.transport, generation]);
  const links = useMemo(
    () =>
      tenant
        ? hostLinks(tenant, project, t).flatMap((link) =>
            link.id === 'plugins' ? [link, ...items] : [link]
          )
        : [],
    [tenant, project, items, t]
  );
  return (
    <Navigation.Provider value={{ tenant, project, items: links, invalidate }}>
      {children}
    </Navigation.Provider>
  );
}

/** Original menu positions apply only to entries the active installation exposes. */
export function layoutHeaderItems(
  items: readonly LinkItem[],
  original: readonly DerivedNavigationItem[],
  context: TopNavigationContext
): DerivedNavigationItem[] {
  const projectHeader = context === 'project';
  const order = context === 'agent' ? [] : ORIGINAL_HEADER_ORDER[context];
  const rank = new Map(order.map((id, index) => [id, index]));
  const unranked = original.length;
  const position = (id: string) => rank.get(id) ?? unranked;
  const ranked = [...original].sort((a, b) => position(a.id) - position(b.id));
  // Groups keep the order of their first section in the original workbench, whichever
  // sections the active installation exposes.
  const groupRank = new Map<string, number>();
  for (const slot of ranked) {
    const group = slot.groupId ?? 'ungrouped';
    if (!groupRank.has(group)) groupRank.set(group, groupRank.size);
  }
  const groupPosition = (item: DerivedNavigationItem) =>
    groupRank.get(item.groupId ?? 'ungrouped') ?? groupRank.size;
  // A project header lists project pages. A tenant header lists tenant pages and the
  // project pages its own sections open.
  const candidates = projectHeader ? items.filter((item) => item.projectId) : items;
  const addresses = (item: LinkItem) => (item.paths ?? [item.path]).map(withoutSearch);
  const byAddress = new Map<string, LinkItem>();
  for (const item of candidates)
    for (const address of addresses(item))
      if (!byAddress.has(address)) byAddress.set(address, item);
  const placed = new Set<string>();
  const sections: string[] = [];
  const result: DerivedNavigationItem[] = [];
  for (const slot of ranked) {
    const section = withoutSearch(slot.path);
    const item = byAddress.get(section);
    if (!item || placed.has(item.id)) continue;
    placed.add(item.id);
    const root = sectionRoot(slot);
    if (root) sections.push(root);
    result.push({
      ...slot,
      path: addresses(item).includes(section)
        ? ((item.paths ?? [item.path]).find((path) => withoutSearch(path) === section) ?? item.path)
        : item.path,
    });
  }
  for (const item of candidates) {
    if (placed.has(item.id)) continue;
    // A page below an installed section belongs to that section, like creating an instance.
    if (
      addresses(item).some((address) =>
        sections.some((section) => address.startsWith(section + '/'))
      )
    )
      continue;
    if (!projectHeader && item.projectId) continue;
    placed.add(item.id);
    result.push({
      ...item,
      context,
      displayRole: 'top-nav',
      relativePath: item.path,
      routeFamily: 'tenant',
      groupId: 'tenant-extensions-integrations',
      groupLabel: 'nav.extensionsIntegrations',
    });
  }
  return result.sort(
    (a, b) => groupPosition(a) - groupPosition(b) || position(a.id) - position(b.id)
  );
}

export function useHeaderItems(requested?: TopNavigationContext): readonly DerivedNavigationItem[] {
  const { items, tenant, project } = useFullNavigation();
  const context = requested ?? (project ? 'project' : 'tenant');
  return layoutHeaderItems(
    items,
    deriveTopNavigationItems(context, {
      tenantId: tenant,
      projectId: project ?? undefined,
    }),
    context
  );
}
