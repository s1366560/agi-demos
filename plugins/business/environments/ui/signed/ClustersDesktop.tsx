import { createRoot } from 'react-dom/client';
import { RuntimeClustersPage } from '../desktop/runtime-clusters/RuntimeClustersPage';
import { createRuntimeClustersController } from '../desktop/runtime-clusters/runtimeClustersController';
import { useRuntimeClustersController } from '../desktop/runtime-clusters/useRuntimeClustersController';
import type { RuntimeClustersClient } from '../desktop/runtime-clusters/runtimeClustersTypes';
import type { ClusterResponse } from '../web/services/clusterService';
import { DesktopLocale } from './desktopI18n';
import { clusterService } from './clusterService';

async function mount() {
  const { locale, tenantId, pathname } = await window.memstack.getContext();
  const scope = { authority: 'cloud' as const, tenantId };
  const client: RuntimeClustersClient = {
    async list(_scope, query, options) {
      const page = query?.page ?? 1,
        pageSize = query?.pageSize ?? 20;
      const result = (await window.memstack.invoke(
        'environment-inventory',
        { kind: 'clusters', page, page_size: pageSize },
        options
      )) as { items: ClusterResponse[]; total: number };
      return {
        page,
        pageSize,
        total: result.total,
        clusters: result.items.map((row) => ({
          id: row.id,
          name: row.name,
          status: row.status,
          computeProvider: row.compute_provider,
          proxyEndpoint: row.proxy_endpoint ?? null,
          healthStatus: row.health_status ?? null,
          lastHealthCheck: row.last_health_check ?? null,
          createdAt: row.created_at,
          updatedAt: row.updated_at ?? null,
        })),
      };
    },
    async getHealth(_scope, id, options) {
      const row = await clusterService.getHealth(id, options?.signal);
      return {
        status: row.status,
        nodeCount: row.node_count,
        cpuUsage: row.cpu_usage,
        memoryUsage: row.memory_usage,
        checkedAt: row.checked_at,
      };
    },
  };
  const controller = createRuntimeClustersController({
    authority: 'cloud',
    client,
    initialScope: scope,
  });
  function Clusters() {
    const { model, retry, setQuery, setFilters, inspectHealth, closeHealth } =
      useRuntimeClustersController(controller, scope);
    return (
      <RuntimeClustersPage
        model={model}
        onRetry={retry}
        onQueryChange={setQuery}
        onFiltersChange={setFilters}
        onInspectHealth={inspectHealth}
        onCloseHealth={closeHealth}
        onOpenDetails={(id) =>
          void window.memstack.navigate(pathname + '/' + encodeURIComponent(id))
        }
      />
    );
  }
  createRoot(document.getElementById('root')!).render(
    <DesktopLocale.Provider value={locale}>
      <Clusters />
    </DesktopLocale.Provider>
  );
}
void mount();
