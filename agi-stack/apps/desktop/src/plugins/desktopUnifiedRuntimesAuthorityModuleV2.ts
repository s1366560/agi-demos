import { PLUGIN_MODULE_CATALOG_V2, RuntimeV2Error, type ContextV2, type PluginDefinitionV2 } from '@agistack/plugin-runtime';

import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { RuntimePoolClient } from '../features/runtime-pool/runtimePoolClient';
import { createUnifiedRuntimesClient } from '../features/unified-runtimes/unifiedRuntimesClient';
import type { UnifiedLocalSidecar, UnifiedRuntimesClient, UnifiedRuntimesRequestOptions, UnifiedRuntimesScope, UnifiedSandbox, UnifiedSandboxCapabilities, UnifiedSandboxStats } from '../features/unified-runtimes/unifiedRuntimesTypes';
import type { DesktopRuntimeConfig } from '../types';
import { DESKTOP_RUNTIME_POOL_AUTHORITY_SERVICE_V2, type DesktopRuntimePoolAuthorityServiceV2 } from './desktopRuntimePoolAuthorityModuleV2';
import { cloneDesktopUnifiedRuntimesConfigV2, prepareDesktopUnifiedRuntimesOperationV2, prepareDesktopUnifiedRuntimesProjectIdV2, type DesktopUnifiedRuntimesOperationInputV2, type PreparedDesktopUnifiedRuntimesOperationV2 } from './desktopUnifiedRuntimesOperationContractV2';
import type { DesktopRendererGenerationActionsV2, DesktopRendererServiceOperationLeaseAdmissionV2 } from './desktopRendererGenerationContextV2';

export const DESKTOP_UNIFIED_RUNTIMES_AUTHORITY_MODULE_REF_V2 = 'builtin://memstack/desktop/unified-runtimes-authority';
export const DESKTOP_UNIFIED_RUNTIMES_AUTHORITY_SERVICE_V2 = 'service:desktop-renderer.unified-runtimes-authority';
export const DESKTOP_UNIFIED_RUNTIMES_AUTHORITY_VERSION_V2 = '1.0.0';
const CLOUD_ACTIONS = Object.freeze(['view', 'refresh', 'inspect-pool', 'inspect-sandbox']);
const LOCAL_ACTIONS = Object.freeze(['view', 'refresh', 'inspect-sidecar', 'inspect-sandbox-capabilities']);

export interface DesktopUnifiedRuntimesAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig, scope: UnifiedRuntimesScope): UnifiedRuntimesClient;
  probe(config: DesktopRuntimeConfig): DesktopCapabilityAvailability;
}

export interface DesktopUnifiedRuntimesOperationsV2 {
  getPoolStatus(input: DesktopUnifiedRuntimesOperationInputV2): ReturnType<UnifiedRuntimesClient['getPoolStatus']>;
  listPoolInstances(input: DesktopUnifiedRuntimesOperationInputV2): ReturnType<UnifiedRuntimesClient['listPoolInstances']>;
  listSandboxes(input: DesktopUnifiedRuntimesOperationInputV2): Promise<readonly UnifiedSandbox[]>;
  getSandboxStats(input: DesktopUnifiedRuntimesOperationInputV2 & Readonly<{ projectId: string }>): Promise<UnifiedSandboxStats | null>;
  getLocalSidecar(input: DesktopUnifiedRuntimesOperationInputV2): Promise<UnifiedLocalSidecar>;
  getSandboxCapabilities(input: DesktopUnifiedRuntimesOperationInputV2): Promise<UnifiedSandboxCapabilities>;
  probe(input: DesktopUnifiedRuntimesOperationInputV2): Promise<DesktopCapabilityAvailability>;
}

type Rejection = Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }> |
  Readonly<{ reasonCode: 'desktop_renderer_generation_actions_unavailable'; runtimeCode?: undefined }>;
export class DesktopUnifiedRuntimesAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode']; readonly runtimeCode: string | undefined;
  constructor(value: Rejection) { super(value.reasonCode); this.name = 'DesktopUnifiedRuntimesAuthorityUnavailableErrorV2'; this.reasonCode = value.reasonCode; this.runtimeCode = value.runtimeCode; }
}

export function applyDesktopUnifiedRuntimesAuthorityV2(context: ContextV2, config: Readonly<Record<string, unknown>>): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error('desktop_unified_runtimes_authority_config_invalid', 'desktop unified runtimes authority requires desktop-api-fetch strategy');
  const pool = requirePoolService(context.require<unknown>('runtime_pool', '1.0.0'));
  context.provide(DESKTOP_UNIFIED_RUNTIMES_AUTHORITY_SERVICE_V2, Object.freeze({
    bindOperation(configValue: DesktopRuntimeConfig, scope: UnifiedRuntimesScope) {
      const poolClient: Pick<RuntimePoolClient, 'getStatus' | 'listInstances'> = Object.freeze({
        getStatus: (_scope, options) => pool.bindOperation(configValue, { authority: 'cloud', tenantId: scope.tenantId }).getStatus(options?.signal),
        listInstances: (_scope, query, options) => pool.bindOperation(configValue, { authority: 'cloud', tenantId: scope.tenantId }).listInstances({ tier: query?.tier ?? 'all', status: query?.status ?? 'all', page: query?.page ?? 1, pageSize: query?.pageSize ?? 100 }, options?.signal),
      });
      return createUnifiedRuntimesClient(configValue, { poolClient });
    },
    probe: capability,
  }));
}

export const desktopUnifiedRuntimesAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({ moduleRef: DESKTOP_UNIFIED_RUNTIMES_AUTHORITY_MODULE_REF_V2, contractDigest: generatedDigest(), apply: applyDesktopUnifiedRuntimesAuthorityV2 });

export function createDesktopUnifiedRuntimesOperationsV2(resolve: () => DesktopRendererGenerationActionsV2 | null): DesktopUnifiedRuntimesOperationsV2 {
  const execute = <T>(input: DesktopUnifiedRuntimesOperationInputV2, callback: (service: DesktopUnifiedRuntimesAuthorityServiceV2, prepared: PreparedDesktopUnifiedRuntimesOperationV2) => Promise<T>) => run(requireActions(resolve()), prepareDesktopUnifiedRuntimesOperationV2(input), callback);
  return Object.freeze({
    getPoolStatus: (input: DesktopUnifiedRuntimesOperationInputV2) => execute(input, (service, value) => service.bindOperation(value.config, value.scope).getPoolStatus(value.scope, options(value.signal))),
    listPoolInstances: (input: DesktopUnifiedRuntimesOperationInputV2) => execute(input, (service, value) => service.bindOperation(value.config, value.scope).listPoolInstances(value.scope, options(value.signal))),
    listSandboxes: (input: DesktopUnifiedRuntimesOperationInputV2) => execute(input, (service, value) => service.bindOperation(value.config, value.scope).listSandboxes(value.scope, options(value.signal))),
    getSandboxStats: (input: DesktopUnifiedRuntimesOperationInputV2 & Readonly<{ projectId: string }>) => { const projectId = prepareDesktopUnifiedRuntimesProjectIdV2(input.projectId); return execute(input, (service, value) => service.bindOperation(value.config, value.scope).getSandboxStats(value.scope, projectId, options(value.signal))); },
    getLocalSidecar: (input: DesktopUnifiedRuntimesOperationInputV2) => execute(input, (service, value) => service.bindOperation(value.config, value.scope).getLocalSidecar(value.scope, options(value.signal))),
    getSandboxCapabilities: (input: DesktopUnifiedRuntimesOperationInputV2) => execute(input, (service, value) => service.bindOperation(value.config, value.scope).getSandboxCapabilities(value.scope, options(value.signal))),
    probe: (input: DesktopUnifiedRuntimesOperationInputV2) => execute(input, async (service, value) => service.probe(value.config)),
  });
}

export function createDesktopUnifiedRuntimesClientV2(operations: DesktopUnifiedRuntimesOperationsV2, config: DesktopRuntimeConfig): UnifiedRuntimesClient {
  const frozen = cloneDesktopUnifiedRuntimesConfigV2(config);
  const base = (scope: UnifiedRuntimesScope, request?: UnifiedRuntimesRequestOptions) => ({ config: frozen, scope, ...(request?.signal === undefined ? {} : { signal: request.signal }) });
  return Object.freeze({
    getPoolStatus: (scope, request) => operations.getPoolStatus(base(scope, request)),
    listPoolInstances: (scope, request) => operations.listPoolInstances(base(scope, request)),
    listSandboxes: (scope, request) => operations.listSandboxes(base(scope, request)),
    getSandboxStats: (scope, projectId, request) => operations.getSandboxStats({ ...base(scope, request), projectId }),
    getLocalSidecar: (scope, request) => operations.getLocalSidecar(base(scope, request)),
    getSandboxCapabilities: (scope, request) => operations.getSandboxCapabilities(base(scope, request)),
  });
}

async function run<T>(actions: DesktopRendererGenerationActionsV2, prepared: PreparedDesktopUnifiedRuntimesOperationV2, callback: (service: DesktopUnifiedRuntimesAuthorityServiceV2, prepared: PreparedDesktopUnifiedRuntimesOperationV2) => Promise<T>): Promise<T> {
  const admission = await actions.acquireServiceOperationLease<DesktopUnifiedRuntimesAuthorityServiceV2>({ service: DESKTOP_UNIFIED_RUNTIMES_AUTHORITY_SERVICE_V2, version: DESKTOP_UNIFIED_RUNTIMES_AUTHORITY_VERSION_V2, scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }) });
  if (admission.status === 'rejected') throw new DesktopUnifiedRuntimesAuthorityUnavailableErrorV2(admission);
  let failed = false; let active = true;
  try { return await admission.useService(async (candidate) => { assertActive(active); const result = await callback(requireService(candidate), prepared); assertActive(active); return result; }); }
  catch (error) { failed = true; throw error; }
  finally { active = false; try { await admission.release(); } catch (error) { if (!failed) throw error; } }
}

function capability(config: DesktopRuntimeConfig): DesktopCapabilityAvailability {
  const tenant = validIdentifier(config.tenantId); const project = validIdentifier(config.projectId);
  const scope = Object.freeze({ tenant_id: tenant, project_id: config.mode === 'local' ? project : null, workspace_id: null, instance_id: null });
  if (!tenant) return unavailable('unified_runtimes_tenant_scope_unavailable', scope);
  if (config.mode === 'local' && !project) return unavailable('unified_runtimes_project_scope_unavailable', scope);
  return Object.freeze({ availability: 'degraded', reason_code: config.mode === 'local' ? 'local_pool_not_applicable_sidecar_projection' : 'global_pool_capacity_not_available_in_tenant_scope', service_version: '0.1.0', contract_version: '3.0.0', allowed_actions: config.mode === 'local' ? LOCAL_ACTIONS : CLOUD_ACTIONS, scope, authority_revision: null });
}
function unavailable(reason_code: string, scope: DesktopCapabilityAvailability['scope']): DesktopCapabilityAvailability { return Object.freeze({ availability: 'unavailable', reason_code, service_version: null, contract_version: null, allowed_actions: [], scope, authority_revision: null }); }
function validIdentifier(value: string): string | null { return value.length > 0 && value === value.trim() ? value : null; }
function requirePoolService(value: unknown): DesktopRuntimePoolAuthorityServiceV2 { if (!record(value) || typeof value.bindOperation !== 'function') throw invalidService(); return value as unknown as DesktopRuntimePoolAuthorityServiceV2; }
function requireService(value: unknown): DesktopUnifiedRuntimesAuthorityServiceV2 { if (!record(value) || typeof value.bindOperation !== 'function' || typeof value.probe !== 'function') throw invalidService(); return value as unknown as DesktopUnifiedRuntimesAuthorityServiceV2; }
function requireActions(value: DesktopRendererGenerationActionsV2 | null): DesktopRendererGenerationActionsV2 { if (value) return value; throw new DesktopUnifiedRuntimesAuthorityUnavailableErrorV2({ reasonCode: 'desktop_renderer_generation_actions_unavailable' }); }
function options(signal: AbortSignal | undefined): UnifiedRuntimesRequestOptions | undefined { return signal === undefined ? undefined : Object.freeze({ signal }); }
function assertActive(active: boolean): void { if (!active) throw new RuntimeV2Error('desktop_unified_runtimes_operation_released', 'desktop unified runtimes operation released'); }
function record(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function invalidService(): RuntimeV2Error { return new RuntimeV2Error('desktop_unified_runtimes_service_invalid', 'desktop unified runtimes authority service invalid'); }
function generatedDigest(): string { const entry = PLUGIN_MODULE_CATALOG_V2.modules.find((candidate) => candidate.module_ref === DESKTOP_UNIFIED_RUNTIMES_AUTHORITY_MODULE_REF_V2); if (!entry) throw new RuntimeV2Error('desktop_unified_runtimes_authority_catalog_missing', 'desktop unified runtimes authority absent from catalog'); return entry.contract_digest; }
