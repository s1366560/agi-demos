import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import type {
  ClusterCreate,
  ClusterResponse,
  ClusterUpdate,
  ClusterHealthResponse,
} from '../web/services/clusterService';

import type {
  ACPRunnerPool,
  ACPRunnerTokenResponse,
  UpsertACPRunnerPoolRequest,
} from '../../../../../web/src/types/acp';

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
  async listAcpRunnerPools(id: string) {
    const result = (await window.memstack.invoke('list-runner-pools', { id })) as {
      items: ACPRunnerPool[];
    };
    return result.items;
  },
  async createAcpRunnerPool(id: string, data: UpsertACPRunnerPoolRequest & { poolKey: string }) {
    const result = (await window.memstack.invoke('create-runner-pool', { id, data })) as {
      item: ACPRunnerPool;
    };
    return result.item;
  },
  createAcpRunnerToken(
    id: string,
    poolKey: string,
    data: { name?: string; expiresInHours?: number }
  ) {
    return window.memstack.invoke('register-runner', {
      id,
      pool_key: poolKey,
      data,
    }) as Promise<ACPRunnerTokenResponse>;
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
