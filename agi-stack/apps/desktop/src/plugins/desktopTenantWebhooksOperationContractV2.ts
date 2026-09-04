import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  TenantWebhook,
  TenantWebhookInput,
  TenantWebhooksSnapshot,
} from '../features/tenant-admin/tenantWebhooksClient';
import type { TenantManagementScope } from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantWebhooksLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantManagementScope;
  signal?: AbortSignal;
}>;
export type DesktopTenantWebhookCreateInputV2 = DesktopTenantWebhooksLoadInputV2 &
  Readonly<{ webhook: TenantWebhookInput }>;
export type DesktopTenantWebhookUpdateInputV2 = DesktopTenantWebhooksLoadInputV2 &
  Readonly<{
    webhookId: string;
    webhook: TenantWebhookInput & Readonly<{ isActive: boolean }>;
  }>;
export type DesktopTenantWebhookDeleteInputV2 = DesktopTenantWebhooksLoadInputV2 &
  Readonly<{ webhookId: string }>;

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
const WEBHOOK_KEYS = Object.freeze(['name', 'url', 'events', 'isActive']);

export function prepareTenantWebhooksLoadV2(
  input: DesktopTenantWebhooksLoadInputV2
): DesktopTenantWebhooksLoadInputV2 {
  return Object.freeze(prepareCommon(input));
}
export function prepareTenantWebhookCreateV2(
  input: DesktopTenantWebhookCreateInputV2
): DesktopTenantWebhookCreateInputV2 {
  return Object.freeze({
    ...prepareCommon(input),
    webhook: freezeWebhookInput(input.webhook, false),
  });
}
export function prepareTenantWebhookUpdateV2(
  input: DesktopTenantWebhookUpdateInputV2
): DesktopTenantWebhookUpdateInputV2 {
  return Object.freeze({
    ...prepareCommon(input),
    webhookId: identifier(input.webhookId),
    webhook: freezeWebhookInput(input.webhook, true) as TenantWebhookInput &
      Readonly<{ isActive: boolean }>,
  });
}
export function prepareTenantWebhookDeleteV2(
  input: DesktopTenantWebhookDeleteInputV2
): DesktopTenantWebhookDeleteInputV2 {
  return Object.freeze({ ...prepareCommon(input), webhookId: identifier(input.webhookId) });
}
export function freezeTenantWebhooksConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (
    !record(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  )
    throw invalidInput();
  for (const key of CONFIG_KEYS)
    if (key !== 'mode' && typeof config[key as keyof DesktopRuntimeConfig] !== 'string')
      throw invalidInput();
  identifier(config.tenantId);
  return Object.freeze({ ...config });
}
export function requireTenantWebhooksSnapshotV2(
  value: unknown,
  scope: TenantManagementScope
): TenantWebhooksSnapshot {
  if (
    !record(value) ||
    !record(value.scope) ||
    !record(value.data) ||
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    value.authority !== scope.authority ||
    !nonnegative(value.scopeRevision) ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    value.contractVersion !== '4.0.0' ||
    !Array.isArray(value.allowedActions) ||
    !value.allowedActions.every((item) => typeof item === 'string') ||
    typeof value.data.membershipRole !== 'string' ||
    !Array.isArray(value.data.webhooks) ||
    !Array.isArray(value.data.eventTypes) ||
    !value.data.eventTypes.every((item) => typeof item === 'string') ||
    value.membershipRole !== value.data.membershipRole ||
    value.webhooks !== value.data.webhooks ||
    value.eventTypes !== value.data.eventTypes
  )
    throw invalidResponse();
  for (const webhook of value.data.webhooks) requireTenantWebhookV2(webhook, scope);
  return value as unknown as TenantWebhooksSnapshot;
}
export function requireTenantWebhookV2(
  value: unknown,
  scope: TenantManagementScope
): TenantWebhook {
  if (
    !record(value) ||
    typeof value.id !== 'string' ||
    value.tenantId !== scope.tenantId ||
    typeof value.name !== 'string' ||
    typeof value.url !== 'string' ||
    (value.secret !== null && typeof value.secret !== 'string') ||
    !Array.isArray(value.events) ||
    !value.events.every((item) => typeof item === 'string') ||
    typeof value.isActive !== 'boolean' ||
    (value.createdAt !== null && typeof value.createdAt !== 'string') ||
    (value.updatedAt !== null && typeof value.updatedAt !== 'string')
  )
    throw invalidResponse();
  return value as unknown as TenantWebhook;
}

function prepareCommon(input: DesktopTenantWebhooksLoadInputV2) {
  if (!record(input)) throw invalidInput();
  const config = freezeTenantWebhooksConfigV2(input.config);
  if (
    !record(input.scope) ||
    Object.keys(input.scope).length !== 2 ||
    input.scope.authority !== config.mode ||
    identifier(input.scope.tenantId) !== config.tenantId
  )
    throw invalidInput();
  if (
    input.signal !== undefined &&
    (!record(input.signal) ||
      typeof input.signal.aborted !== 'boolean' ||
      typeof input.signal.addEventListener !== 'function')
  )
    throw invalidInput();
  return {
    config,
    scope: Object.freeze({ authority: input.scope.authority, tenantId: input.scope.tenantId }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  };
}
function freezeWebhookInput(value: unknown, activeRequired: boolean): TenantWebhookInput {
  if (
    !record(value) ||
    Object.keys(value).some((key) => !WEBHOOK_KEYS.includes(key)) ||
    identifier(value.name) !== value.name ||
    identifier(value.url) !== value.url ||
    !Array.isArray(value.events) ||
    !value.events.every((item) => typeof item === 'string') ||
    (activeRequired
      ? typeof value.isActive !== 'boolean'
      : value.isActive !== undefined && typeof value.isActive !== 'boolean')
  )
    throw invalidInput();
  const isActive = value.isActive as boolean | undefined;
  return Object.freeze({
    name: value.name,
    url: value.url,
    events: Object.freeze([...value.events]),
    ...(isActive === undefined ? {} : { isActive }),
  });
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
    'desktop_tenant_webhooks_operation_input_invalid',
    'desktop tenant webhooks operation input invalid'
  );
}
function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_webhooks_operation_response_invalid',
    'desktop tenant webhooks operation response invalid'
  );
}
