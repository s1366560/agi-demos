import { useEffect, useState } from 'react';
import { invokeSlot } from '../../../../packages/plugin-marketplace-ui/src/invokeSidebarSlot';
import { routeRank } from '../../../../packages/plugin-slots/src/richPage';
import { transport } from '../packageHost/transport';
import type { InstalledPage } from './pages';

export interface NavigationRow {
  group: string | null;
  groupLabel: string | null;
  id: string;
  label: string;
  path: string;
}

export function useNavigationRows(
  tenant: string,
  project: string | null,
  page: InstalledPage | undefined,
  address: string,
) {
  const [snapshot, setSnapshot] = useState<{
    key: string;
    rows: NavigationRow[];
    error: string;
  } | null>(null);
  const key = JSON.stringify([tenant, project, page?.digest, page?.pluginId, page?.page.id]);
  useEffect(() => {
    const binding = page?.page.sidebar?.rows;
    if (
      !project ||
      !page?.enabled ||
      page.projectId !== project ||
      !binding?.row_param ||
      !binding.row_route ||
      !page.page.routes.includes(binding.row_route)
    )
      return;
    const route = binding.row_route;
    const param = binding.row_param;
    const owner = {
      plugin: page.pluginId,
      digest: page.digest,
      projectId: project,
      commands: page.commands,
      sidebar: page.page.sidebar,
    };
    const controller = new AbortController();
    let loading = false;
    const load = async () => {
      if (loading) return;
      loading = true;
      try {
        const result = await invokeSlot(
          transport,
          tenant,
          project,
          owner,
          'rows',
          {},
          controller.signal,
        );
        const rows = result.rows.flatMap((row) => {
          if (typeof row.id !== 'string' || typeof row.label !== 'string' || row.hidden === true)
            return [];
          const fields: Record<string, string> = {
            tenantId: tenant,
            projectId: project,
            [param]: row.id,
          };
          const path = route
            .split('/')
            .map((part) =>
              part.startsWith(':') ? encodeURIComponent(fields[part.slice(1)] ?? '') : part,
            )
            .join('/');
          if (routeRank(route, path, { tenantId: tenant, projectId: project }) === null) return [];
          const query = new URLSearchParams();
          if (binding.group_query && typeof row.group === 'string')
            query.set(binding.group_query, row.group);
          return [
            {
              id: row.id,
              label: row.label,
              path: path + (query.size ? '?' + query : ''),
              group: typeof row.group === 'string' ? row.group : null,
              groupLabel: typeof row.groupLabel === 'string' ? row.groupLabel : null,
            },
          ];
        });
        setSnapshot({ key, rows, error: '' });
      } catch (error) {
        if (!controller.signal.aborted) setSnapshot({ key, rows: [], error: String(error) });
      } finally {
        loading = false;
      }
    };
    void load();
    window.addEventListener('focus', load);
    return () => {
      controller.abort();
      window.removeEventListener('focus', load);
    };
  }, [tenant, project, page, address, key]);
  return snapshot?.key === key ? snapshot : { rows: [], error: '' };
}
