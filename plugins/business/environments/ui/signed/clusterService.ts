import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import type {
  ClusterCreate,
  ClusterResponse,
  ClusterUpdate,
  ClusterHealthResponse,
} from '../web/services/clusterService';

interface ClusterRow extends Omit<ClusterResponse, 'credentials_encrypted' | 'provider_config'> {
  provider_config?: Record<string, unknown>;
}
function item(row: ClusterRow): ClusterResponse {
  return { ...row, provider_config: row.provider_config ?? {}, credentials_encrypted: null };
}
async function edit(payload: object) {
  const result = (await window.memstack.invoke('write-cluster', { ...payload })) as {
    item: ClusterRow;
  };
  return item(result.item);
}
export const clusterService = {
  async list({ page = 1, page_size = 20 } = {}) {
    const result = (await window.memstack.invoke('environment-inventory', {
      kind: 'clusters',
      page,
      page_size,
    })) as { items: ClusterRow[]; total: number };
    return { page, page_size, total: result.total, clusters: result.items.map(item) };
  },
  create: (data: ClusterCreate) => edit({ action: 'create', data }),
  update: (id: string, data: ClusterUpdate) => edit({ action: 'update', id, data }),
  getEditable: (id: string) => edit({ action: 'edit', id }),
  delete: (id: string) => window.memstack.invoke('delete-cluster', { id }),
  async getById(id: string) {
    const result = (await window.memstack.invoke('environment-inventory', {
      kind: 'clusters',
      id,
    })) as { item: ClusterRow };
    return item(result.item);
  },
  async getHealth(id: string, signal?: AbortSignal) {
    const result = (await window.memstack.invoke(
      'environment-inventory',
      { kind: 'clusters', id, health: true },
      signal ? { signal } : undefined
    )) as { health: ClusterHealthResponse };
    return result.health;
  },
};
