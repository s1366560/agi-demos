import { useEffect, useState, useSyncExternalStore } from 'react';

import {
  packageBase,
  packageScope,
  type Installation,
} from '../../../../packages/plugin-marketplace-ui/src/pluginMarketTypes';
import { splitPageLocation } from '../../../../packages/plugin-slots/src/pageLocation';
import { routeRank } from '../../../../packages/plugin-slots/src/richPage';
import { transport } from './transport';

const locationHash = () => window.location.hash;
function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  return () => window.removeEventListener('hashchange', listener);
}

type SignedRoute = { projectId: string | null; pluginId: string; rank: string };
export type SignedWorkbench =
  | { kind: 'market' }
  | { kind: 'page'; route: SignedRoute; address: string };

async function matchInstalledPage(
  tenantId: string,
  projectId: string | null,
  pathname: string,
  signal: AbortSignal
) {
  const query = new URLSearchParams(packageScope(tenantId, projectId));
  const result = await transport<{ items: (Installation & { status: string })[] }>(
    packageBase(projectId) + '/?' + query,
    { signal }
  );
  let match: SignedRoute | null = null;
  for (const release of result.items) {
    if (!release.actual_digest || !['enabled', 'failed'].includes(release.status)) continue;
    for (const page of release.pages ?? []) {
      if (!page.workbench || !page.targets.includes('desktop-renderer')) continue;
      for (const path of page.routes) {
        const rank = routeRank(path, pathname, { tenantId, projectId });
        if (rank !== null && (!match || rank > match.rank))
          match = { projectId, pluginId: release.plugin_id, rank };
      }
    }
  }
  return match;
}

/** Legacy deep links and marketplace launches resolve against the same installed page declarations. */
export function useSignedWorkbench(
  tenant: string,
  project: string | null,
  principal: string | undefined
): SignedWorkbench | null {
  const address = useSyncExternalStore(subscribe, locationHash).slice(1);
  const { pathname } = splitPageLocation(address);
  const tenantBase = '/tenant/' + encodeURIComponent(tenant);
  const market = Boolean(tenant) && pathname === tenantBase + '/plugins';
  const tenantPath = pathname.startsWith(tenantBase + '/');
  const projectPath = Boolean(
    project &&
    (pathname.startsWith('/project/' + encodeURIComponent(project) + '/') ||
      pathname.startsWith(tenantBase + '/project/' + encodeURIComponent(project) + '/'))
  );
  const candidate = Boolean(tenant && principal && !market && (projectPath || tenantPath));
  const key = JSON.stringify([principal, tenant, project, pathname]);
  const [result, setResult] = useState<{ key: string; route: SignedRoute | null } | null>(null);
  useEffect(() => {
    if (!candidate) return;
    const controller = new AbortController();
    const scopes = projectPath ? [project] : project ? [null, project] : [null];
    let latestRequest = 0;
    async function refresh() {
      const request = ++latestRequest;
      const matches = await Promise.allSettled(
        scopes.map((id) => matchInstalledPage(tenant, id, pathname, controller.signal))
      );
      if (controller.signal.aborted || request !== latestRequest) return;
      let route: SignedRoute | null = null;
      for (const match of matches) {
        if (
          match.status === 'fulfilled' &&
          match.value &&
          (!route || match.value.rank > route.rank)
        )
          route = match.value;
      }
      setResult({ key, route });
    }
    void refresh();
    window.addEventListener('focus', refresh);
    return () => {
      controller.abort();
      window.removeEventListener('focus', refresh);
    };
  }, [candidate, key, projectPath, tenant, project, pathname]);
  if (market) return { kind: 'market' };
  return candidate && result?.key === key && result.route
    ? { kind: 'page', route: result.route, address }
    : null;
}
