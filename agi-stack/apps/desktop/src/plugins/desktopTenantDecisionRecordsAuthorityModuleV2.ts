import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  TenantDecisionRecord,
  TenantDecisionRecordsClient,
  TenantDecisionRecordsSnapshot,
} from '../features/tenant-admin/tenantDecisionRecordsClient';
import type {
  TenantManagementRequestOptions,
  TenantManagementWorkspaceScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantDecisionRecordsHttpProjectionV2 } from './desktopTenantDecisionRecordsHttpProjectionV2';
import {
  freezeTenantDecisionRecordsConfigV2,
  prepareTenantDecisionRecordsLoadV2,
  prepareTenantDecisionRecordsResolveV2,
  requireTenantDecisionRecordV2,
  requireTenantDecisionRecordsSnapshotV2,
  type DesktopTenantDecisionRecordsLoadInputV2,
  type DesktopTenantDecisionRecordsResolveInputV2,
} from './desktopTenantDecisionRecordsOperationContractV2';

export const DESKTOP_TENANT_DECISION_RECORDS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-decision-records-authority';
export const DESKTOP_TENANT_DECISION_RECORDS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-decision-records-authority';
export const DESKTOP_TENANT_DECISION_RECORDS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantDecisionRecordsAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: TenantManagementWorkspaceScope
  ): TenantDecisionRecordsClient;
}
export interface DesktopTenantDecisionRecordsOperationsV2 {
  loadTenantDecisionRecords(
    input: DesktopTenantDecisionRecordsLoadInputV2
  ): Promise<TenantDecisionRecordsSnapshot>;
  resolveTenantDecisionApproval(
    input: DesktopTenantDecisionRecordsResolveInputV2
  ): Promise<TenantDecisionRecord>;
}
type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantDecisionRecordsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantDecisionRecordsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantDecisionRecordsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_decision_records_authority_config_invalid',
      'desktop tenant decision records authority requires desktop-api-fetch strategy'
    );
  }
  context.provide(
    DESKTOP_TENANT_DECISION_RECORDS_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopTenantDecisionRecordsHttpProjectionV2(configValue);
      },
    })
  );
}

export const desktopTenantDecisionRecordsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_DECISION_RECORDS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantDecisionRecordsAuthorityV2,
});

export function createDesktopTenantDecisionRecordsOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null
): DesktopTenantDecisionRecordsOperationsV2 {
  return Object.freeze({
    loadTenantDecisionRecords(input: DesktopTenantDecisionRecordsLoadInputV2) {
      const prepared = prepareTenantDecisionRecordsLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantDecisionRecordsSnapshotV2(
          await authority.load(prepared.scope, requestOptions(prepared.signal)),
          prepared.scope
        )
      );
    },
    resolveTenantDecisionApproval(input: DesktopTenantDecisionRecordsResolveInputV2) {
      const prepared = prepareTenantDecisionRecordsResolveV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantDecisionRecordV2(
          await authority.resolveApproval(
            prepared.scope,
            prepared.recordId,
            prepared.decision,
            requestOptions(prepared.signal)
          ),
          prepared.scope
        )
      );
    },
  });
}

export function createDesktopTenantDecisionRecordsClientV2(
  operations: DesktopTenantDecisionRecordsOperationsV2,
  config: DesktopRuntimeConfig
): TenantDecisionRecordsClient {
  const frozen = freezeTenantDecisionRecordsConfigV2(config);
  return Object.freeze({
    load: (scope, options) =>
      operations.loadTenantDecisionRecords({
        config: frozen,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    resolveApproval: (scope, recordId, decision, options) =>
      operations.resolveTenantDecisionApproval({
        config: frozen,
        scope,
        recordId,
        decision,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
  });
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantDecisionRecordsLoadInputV2,
  operation: (authority: TenantDecisionRecordsClient) => Promise<T>
): Promise<T> {
  const actions = resolve();
  if (!actions)
    throw new DesktopTenantDecisionRecordsAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantDecisionRecordsAuthorityServiceV2>({
      service: DESKTOP_TENANT_DECISION_RECORDS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_DECISION_RECORDS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected')
    throw new DesktopTenantDecisionRecordsAuthorityUnavailableErrorV2(admission);
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      if (
        !record(candidate) ||
        Object.keys(candidate).length !== 1 ||
        typeof candidate.bindOperation !== 'function'
      )
        throw invalidService();
      const raw = candidate.bindOperation(prepared.config, prepared.scope);
      if (
        !record(raw) ||
        Object.keys(raw).length !== 2 ||
        typeof raw.load !== 'function' ||
        typeof raw.resolveApproval !== 'function'
      )
        throw invalidService();
      const authority = Object.freeze({
        load: (...args: Parameters<TenantDecisionRecordsClient['load']>) => {
          assertActive(active);
          return raw.load(...args);
        },
        resolveApproval: (...args: Parameters<TenantDecisionRecordsClient['resolveApproval']>) => {
          assertActive(active);
          return raw.resolveApproval(...args);
        },
      });
      const result = await operation(authority);
      assertActive(active);
      return result;
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    active = false;
    try {
      await admission.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}
function requestOptions(signal?: AbortSignal): TenantManagementRequestOptions | undefined {
  return signal === undefined ? undefined : Object.freeze({ signal });
}
function assertActive(active: boolean): void {
  if (!active)
    throw new RuntimeV2Error(
      'desktop_tenant_decision_records_operation_released',
      'desktop tenant decision records operation released'
    );
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_decision_records_service_invalid',
    'desktop tenant decision records authority service invalid'
  );
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_DECISION_RECORDS_AUTHORITY_MODULE_REF_V2
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_tenant_decision_records_authority_catalog_missing',
      'desktop tenant decision records authority absent from catalog'
    );
  return entry.contract_digest;
}
