import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  TenantEventFilters,
  TenantEventsSnapshot,
} from '../features/tenant-admin/tenantEventsClient';
import type { TenantManagementScope } from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantEventsOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantManagementScope;
  filters?: TenantEventFilters;
  signal?: AbortSignal;
}>;

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
const FILTER_KEYS = new Set(['eventType', 'dateFrom', 'dateTo', 'page', 'pageSize']);

export function prepareDesktopTenantEventsOperationV2(
  input: DesktopTenantEventsOperationInputV2
): DesktopTenantEventsOperationInputV2 {
  if (!isRecord(input)) throw invalidInput();
  const config = freezeDesktopRuntimeConfigV2(input.config);
  const scope = input.scope;
  if (
    !isRecord(scope) ||
    Object.keys(scope).length !== 2 ||
    scope.authority !== config.mode ||
    requireIdentifier(scope.tenantId) !== config.tenantId
  ) {
    throw invalidInput();
  }
  if (
    input.signal !== undefined &&
    (!isRecord(input.signal) ||
      typeof input.signal.aborted !== 'boolean' ||
      typeof input.signal.addEventListener !== 'function')
  ) {
    throw invalidInput();
  }
  const filters = input.filters === undefined ? undefined : freezeFilters(input.filters);
  return Object.freeze({
    config,
    scope: Object.freeze({
      authority: scope.authority,
      tenantId: scope.tenantId,
    }),
    ...(filters === undefined ? {} : { filters }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function freezeDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (
    !isRecord(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  ) {
    throw invalidInput();
  }
  for (const key of CONFIG_KEYS) {
    if (key !== 'mode' && typeof config[key as keyof DesktopRuntimeConfig] !== 'string') {
      throw invalidInput();
    }
  }
  requireIdentifier(config.tenantId);
  return Object.freeze({ ...config });
}

export function requireDesktopTenantEventsSnapshotV2(
  value: unknown,
  expectedScope: TenantManagementScope
): TenantEventsSnapshot {
  if (!isRecord(value) || !isRecord(value.scope) || !isRecord(value.data)) throw invalidResponse();
  const data = value.data;
  if (
    value.scope.authority !== expectedScope.authority ||
    value.scope.tenantId !== expectedScope.tenantId ||
    value.authority !== expectedScope.authority ||
    !Number.isSafeInteger(value.scopeRevision) ||
    (value.scopeRevision as number) < 0 ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    value.contractVersion !== '4.0.0' ||
    !Array.isArray(value.allowedActions) ||
    !value.allowedActions.every((action) => typeof action === 'string') ||
    typeof data.membershipRole !== 'string' ||
    !Array.isArray(data.events) ||
    !Array.isArray(data.eventTypes) ||
    !data.eventTypes.every((eventType) => typeof eventType === 'string') ||
    !isNonnegativeInteger(data.total) ||
    !isNonnegativeInteger(data.page) ||
    !isNonnegativeInteger(data.pageSize) ||
    value.membershipRole !== data.membershipRole ||
    value.events !== data.events ||
    value.eventTypes !== data.eventTypes ||
    value.total !== data.total ||
    value.page !== data.page ||
    value.pageSize !== data.pageSize
  ) {
    throw invalidResponse();
  }
  return value as unknown as TenantEventsSnapshot;
}

function freezeFilters(filters: TenantEventFilters): TenantEventFilters {
  if (!isRecord(filters) || Object.keys(filters).some((key) => !FILTER_KEYS.has(key))) {
    throw invalidInput();
  }
  for (const key of ['eventType', 'dateFrom', 'dateTo'] as const) {
    const value = filters[key];
    if (value !== undefined && typeof value !== 'string') throw invalidInput();
  }
  for (const key of ['page', 'pageSize'] as const) {
    const value = filters[key];
    if (value !== undefined && (!Number.isSafeInteger(value) || value < 1)) throw invalidInput();
  }
  return Object.freeze({ ...filters });
}

function requireIdentifier(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) throw invalidInput();
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_events_operation_input_invalid',
    'desktop tenant events operation input invalid'
  );
}

function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_events_operation_response_invalid',
    'desktop tenant events operation response invalid'
  );
}
