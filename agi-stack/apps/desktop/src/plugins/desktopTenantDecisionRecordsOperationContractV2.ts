import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  TenantApprovalDecision,
  TenantDecisionFilters,
  TenantDecisionRecord,
  TenantDecisionRecordsSnapshot,
} from '../features/tenant-admin/tenantDecisionRecordsClient';
import type { TenantManagementWorkspaceScope } from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantDecisionRecordsLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantManagementWorkspaceScope;
  filters?: TenantDecisionFilters;
  signal?: AbortSignal;
}>;
export type DesktopTenantDecisionRecordsResolveInputV2 = DesktopTenantDecisionRecordsLoadInputV2 &
  Readonly<{ recordId: string; decision: TenantApprovalDecision }>;

const CONFIG_KEYS = Object.freeze([
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
]);

export function prepareTenantDecisionRecordsLoadV2(
  input: DesktopTenantDecisionRecordsLoadInputV2
): DesktopTenantDecisionRecordsLoadInputV2 {
  return Object.freeze(prepareCommon(input));
}

export function prepareTenantDecisionRecordsResolveV2(
  input: DesktopTenantDecisionRecordsResolveInputV2
): DesktopTenantDecisionRecordsResolveInputV2 {
  const common = prepareCommon(input);
  if (
    input.decision !== 'allow_once' &&
    input.decision !== 'allow_always' &&
    input.decision !== 'deny'
  ) {
    throw invalidInput();
  }
  return Object.freeze({
    ...common,
    recordId: identifier(input.recordId),
    decision: input.decision,
  });
}

export function freezeTenantDecisionRecordsConfigV2(
  config: DesktopRuntimeConfig
): DesktopRuntimeConfig {
  if (
    !record(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  )
    throw invalidInput();
  for (const key of CONFIG_KEYS) {
    if (key !== 'mode' && typeof config[key as keyof DesktopRuntimeConfig] !== 'string')
      throw invalidInput();
  }
  identifier(config.tenantId);
  return Object.freeze({ ...config });
}

export function requireTenantDecisionRecordsSnapshotV2(
  value: unknown,
  scope: TenantManagementWorkspaceScope
): TenantDecisionRecordsSnapshot {
  if (!record(value) || !record(value.scope) || !record(value.data)) throw invalidResponse();
  const data = value.data;
  if (
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    value.scope.workspaceId !== scope.workspaceId ||
    value.authority !== scope.authority ||
    !nonnegative(value.scopeRevision) ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    value.contractVersion !== '4.0.0' ||
    !Array.isArray(value.allowedActions) ||
    !value.allowedActions.every((action) => typeof action === 'string') ||
    typeof data.membershipRole !== 'string' ||
    !Array.isArray(data.records) ||
    value.membershipRole !== data.membershipRole ||
    value.records !== data.records
  )
    throw invalidResponse();
  for (const item of data.records) requireTenantDecisionRecordV2(item, scope);
  return value as unknown as TenantDecisionRecordsSnapshot;
}

export function requireTenantDecisionRecordV2(
  value: unknown,
  scope: TenantManagementWorkspaceScope
): TenantDecisionRecord {
  if (
    !record(value) ||
    value.tenantId !== scope.tenantId ||
    value.workspaceId !== scope.workspaceId ||
    typeof value.id !== 'string' ||
    !value.id ||
    typeof value.agentInstanceId !== 'string' ||
    typeof value.decisionType !== 'string' ||
    !record(value.proposal) ||
    !['pending', 'approved', 'denied', 'success', 'rejected'].includes(String(value.outcome)) ||
    typeof value.createdAt !== 'string'
  )
    throw invalidResponse();
  return value as unknown as TenantDecisionRecord;
}

function prepareCommon(input: DesktopTenantDecisionRecordsLoadInputV2) {
  if (!record(input)) throw invalidInput();
  const config = freezeTenantDecisionRecordsConfigV2(input.config);
  if (
    !record(input.scope) ||
    Object.keys(input.scope).length !== 3 ||
    input.scope.authority !== config.mode ||
    identifier(input.scope.tenantId) !== config.tenantId ||
    identifier(input.scope.workspaceId) !== config.workspaceId
  )
    throw invalidInput();
  if (
    input.signal !== undefined &&
    (!record(input.signal) ||
      typeof input.signal.aborted !== 'boolean' ||
      typeof input.signal.addEventListener !== 'function')
  )
    throw invalidInput();
  let filters: TenantDecisionFilters | undefined;
  if (input.filters !== undefined) {
    if (
      !record(input.filters) ||
      Object.keys(input.filters).some((key) => key !== 'agentId' && key !== 'decisionType')
    )
      throw invalidInput();
    if (input.filters.agentId !== undefined && typeof input.filters.agentId !== 'string')
      throw invalidInput();
    if (input.filters.decisionType !== undefined && typeof input.filters.decisionType !== 'string')
      throw invalidInput();
    filters = Object.freeze({
      ...(input.filters.agentId === undefined ? {} : { agentId: input.filters.agentId }),
      ...(input.filters.decisionType === undefined
        ? {}
        : { decisionType: input.filters.decisionType }),
    });
  }
  return {
    config,
    scope: Object.freeze({
      authority: input.scope.authority,
      tenantId: input.scope.tenantId,
      workspaceId: input.scope.workspaceId,
    }),
    ...(filters === undefined ? {} : { filters }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  };
}
function identifier(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) throw invalidInput();
  return value;
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function nonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_decision_records_operation_input_invalid',
    'desktop tenant decision records operation input invalid'
  );
}
function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_decision_records_operation_response_invalid',
    'desktop tenant decision records operation response invalid'
  );
}
