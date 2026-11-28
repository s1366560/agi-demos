import { invoke } from './reviewAuthority';
import type {
  TenantAgentConfig,
  UpdateTenantAgentConfigRequest,
  HookCatalogEntry,
} from '../../../../../web/src/types/agent';
import type {
  TraceChainDTO,
  TenantSubAgentRunListDTO,
  TenantActiveRunCountDTO,
} from '../../../../../web/src/types/multiAgent';
import type { SystemInfoResponse } from '../../../../../web/src/services/systemService';

export const read = <T>(view: string, signal?: AbortSignal) =>
  invoke<T>('dashboard-read', { view }, { signal });
export const traceAPI = {
  listTenantRuns: () => read<TenantSubAgentRunListDTO>('runs'),
  getTenantActiveRunCount: () => read<TenantActiveRunCountDTO>('active'),
  getTraceChain: (conversation_id: string, trace_id: string, signal?: AbortSignal) =>
    invoke<TraceChainDTO>('dashboard-trace', { conversation_id, trace_id }, { signal }),
};
export const systemService = { getInfo: () => read<SystemInfoResponse>('system') };
export class TenantAgentConfigError extends Error {
  constructor(
    message: string,
    public statusCode?: number
  ) {
    super(message);
  }
}
export async function updateConfig(
  config: Record<string, unknown>,
  expected_revision: number,
  signal?: AbortSignal
) {
  const saved = await invoke<
    { status: 200; config: TenantAgentConfig & { authority_revision: number } } | { status: 409 }
  >('dashboard-configure', { config, expected_revision }, { signal });
  if (saved.status === 409)
    throw new TenantAgentConfigError('Tenant configuration revision changed', 409);
  return saved.config;
}
export const agentConfigService = {
  getConfig: () => read<TenantAgentConfig>('config'),
  getAuthorityRevision: async () =>
    (await read<{ authority_revision: number }>('revision')).authority_revision,
  canModifyConfig: async () => (await read<{ can_modify: boolean }>('permission')).can_modify,
  getHookCatalog: async () => (await read<{ hooks: HookCatalogEntry[] }>('catalog')).hooks,
  async updateConfigWithRevision(
    _tenant: string,
    config: UpdateTenantAgentConfigRequest,
    revision: number
  ) {
    const saved = await updateConfig({ ...config }, revision);
    return { config: saved, authorityRevision: saved.authority_revision };
  },
};
