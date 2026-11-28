import { useCallback, useEffect, useState } from 'react';
import {
  type Installation,
  packageBase,
  packageScope,
} from '../../../../packages/plugin-marketplace-ui/src/pluginMarketTypes';
import {
  menuPath,
  type PackagePage,
} from '../../../../packages/plugin-slots/src/richPage';
import { transport } from '../packageHost/transport';
import { selectInstalledPage } from './workbenchModel';

export type InstalledPage = {
  enabled: boolean;
  digest: string;
  commands: readonly string[];
  projectId: string | null;
  pluginId: string;
  page: PackagePage;
  path: string | null;
};
export function matchPage(entries: readonly InstalledPage[], tenantId: string, address: string) {
  return selectInstalledPage(entries, tenantId, address);
}
export function useInstalledPages(tenantId: string, projectId: string | null) {
  const key = JSON.stringify([tenantId, projectId]);
  const [snapshot, setSnapshot] = useState<{
    key: string;
    entries: InstalledPage[];
    error: string | null;
  } | null>(null);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((i) => i + 1), []);
  useEffect(() => {
    if (!tenantId) return;
    const controller = new AbortController();
    const scopes = projectId ? [projectId, null] : [null];
    let refreshing = false;
    async function load() {
      if (refreshing || controller.signal.aborted) return;
      refreshing = true;
      try {
        const results = await Promise.allSettled(
          scopes.map(async (id) => {
            const query = new URLSearchParams(packageScope(tenantId, id));
            const result = await transport<{
              items: (Installation & { status: string })[];
            }>(packageBase(id) + '/?' + query, { signal: controller.signal });
            return result.items.flatMap((release) => {
              if (!release.actual_digest || !['enabled', 'failed'].includes(release.status))
                return [];
              return (release.pages ?? [])
                .filter((page) => page.targets.includes('desktop-renderer') && page.routes.length > 0)
                .map((page) => {
                  const paths = page.routes.map((route) =>
                    menuPath(route, { tenantId, projectId: id }),
                  );
                  return {
                    enabled: release.status === 'enabled',
                    pluginId: release.plugin_id,
                    commands: release.commands ?? [],
                    digest: release.actual_digest!,
                    projectId: id,
                    page,
                    path:
                      paths.find((path) => path?.startsWith('/tenant/')) ||
                      paths.find(Boolean) ||
                      null,
                  };
                });
            });
          }),
        );
        if (controller.signal.aborted) return;
        setSnapshot({
          key,
          entries: results.flatMap((result) => (result.status === 'fulfilled' ? result.value : [])),
          error:
            results
              .flatMap((result) => (result.status === 'rejected' ? [String(result.reason)] : []))
              .join('\n') || null,
        });
      } finally {
        refreshing = false;
      }
    }
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 5000);
    const onFocus = () => {
      if (!document.hidden) void load();
    };
    window.addEventListener('focus', onFocus);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, [key, tenantId, projectId, revision]);
  return {
    entries: snapshot?.key === key ? snapshot.entries : [],
    loading: !!tenantId && snapshot?.key !== key,
    error: snapshot?.key === key ? snapshot.error : null,
    refresh,
  };
}
