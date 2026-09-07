import type {
  RuntimePoolInstancePage,
  RuntimePoolMetrics,
  RuntimePoolQuery,
  RuntimePoolScope,
  RuntimePoolStatus,
} from '../features/runtime-pool/runtimePoolClient';
import { createRuntimePoolHttpClient } from '../features/runtime-pool/runtimePoolClient';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';
import { DESKTOP_RUNTIME_POOL_CLOUD_ACTIONS_V2 } from './desktopRuntimePoolContractV2';

export type DesktopRuntimePoolHttpAuthorityV2 = Readonly<{
  getStatus: (signal?: AbortSignal) => Promise<RuntimePoolStatus>;
  listInstances: (
    query: Required<RuntimePoolQuery>,
    signal?: AbortSignal,
  ) => Promise<RuntimePoolInstancePage>;
  getMetrics: (signal?: AbortSignal) => Promise<RuntimePoolMetrics>;
  pauseInstance: (instanceKey: string, signal?: AbortSignal) => Promise<void>;
  resumeInstance: (instanceKey: string, signal?: AbortSignal) => Promise<void>;
  terminateInstance: (
    instanceKey: string,
    graceful: boolean,
    signal?: AbortSignal,
  ) => Promise<void>;
  probe: (signal?: AbortSignal) => Promise<DesktopCapabilityAvailability>;
}>;

export function createDesktopRuntimePoolHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: RuntimePoolScope,
): DesktopRuntimePoolHttpAuthorityV2 {
  const runtimeConfig = Object.freeze({ ...config });
  const operationScope = Object.freeze({ ...scope });
  const client = createRuntimePoolHttpClient(runtimeConfig);
  return Object.freeze({
    getStatus: (signal?: AbortSignal) => client.getStatus(operationScope, { signal }),
    listInstances: (query: Required<RuntimePoolQuery>, signal?: AbortSignal) =>
      client.listInstances(operationScope, query, { signal }),
    getMetrics: (signal?: AbortSignal) => client.getMetrics(operationScope, { signal }),
    pauseInstance: (instanceKey: string, signal?: AbortSignal) =>
      client.pauseInstance(operationScope, instanceKey, { signal }),
    resumeInstance: (instanceKey: string, signal?: AbortSignal) =>
      client.resumeInstance(operationScope, instanceKey, { signal }),
    terminateInstance: (instanceKey: string, graceful: boolean, signal?: AbortSignal) =>
      client.terminateInstance(operationScope, instanceKey, graceful, {
        signal,
      }),
    async probe(signal?: AbortSignal) {
      if (operationScope.authority === 'local') {
        return Object.freeze({
          availability: 'not_applicable',
          reason_code: 'cloud_runtime_pool_not_applicable',
          service_version: null,
          contract_version: null,
          allowed_actions: Object.freeze([]),
          scope: capabilityScopeV2(operationScope),
          authority_revision: null,
        });
      }
      await client.getStatus(operationScope, { signal });
      return Object.freeze({
        availability: 'degraded',
        reason_code: 'global_pool_capacity_not_available_in_tenant_scope',
        service_version: '0.1.0',
        contract_version: '3.0.0',
        allowed_actions: DESKTOP_RUNTIME_POOL_CLOUD_ACTIONS_V2,
        scope: capabilityScopeV2(operationScope),
        authority_revision: null,
      });
    },
  });
}

function capabilityScopeV2(scope: RuntimePoolScope) {
  return Object.freeze({
    tenant_id: scope.tenantId,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  });
}
