import { RuntimeV2Error } from '@agistack/plugin-runtime';
import { DesktopApiError } from '../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import type { ManagementRouteScope } from '../features/settings-routes/managementRouteTypes';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';

export type SkillScopeV2 = ManagementRouteScope;
export type SkillInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: SkillScopeV2;
  signal?: AbortSignal;
}>;
const CONFIG_KEYS = [
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
];
export function skillErrorV2(code: string, status = 422): DesktopApiError {
  return new DesktopApiError(code, status, Object.freeze({ code, reason_code: code }));
}
export function skillRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function skillIdentifierV2(value: unknown): string {
  if (typeof value !== 'string' || !value.trim() || value !== value.trim()) {
    throw skillErrorV2('tenant_skill_identifier_invalid');
  }
  return value;
}
export function skillIntegerV2(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    throw skillErrorV2('tenant_skill_integer_invalid');
  }
  return Number(value);
}
export function freezeSkillConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (
    !skillRecordV2(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => typeof config[key as keyof DesktopRuntimeConfig] !== 'string') ||
    !['local', 'cloud'].includes(config.mode)
  )
    throw skillErrorV2('tenant_skill_config_invalid');
  return Object.freeze({ ...config });
}
export function prepareSkillInputV2(input: SkillInputV2): SkillInputV2 {
  if (!skillRecordV2(input) || !skillRecordV2(input.scope) || Object.keys(input.scope).length !== 3)
    throw skillErrorV2('tenant_skill_scope_invalid');
  const config = freezeSkillConfigV2(input.config);
  const { authority, tenantId, projectId } = input.scope;
  skillIdentifierV2(tenantId);
  if (
    authority !== config.mode ||
    tenantId !== config.tenantId ||
    (projectId !== null &&
      (!skillIdentifierV2(projectId) ||
        (config.mode === 'local' && projectId !== config.projectId)))
  ) {
    throw skillErrorV2('tenant_skill_scope_mismatch', 409);
  }
  if (input.signal !== undefined && !(input.signal instanceof AbortSignal)) {
    throw skillErrorV2('tenant_skill_signal_invalid');
  }
  if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  return Object.freeze({
    config,
    scope: Object.freeze({ authority, tenantId, projectId }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
export function freezeSkillJsonV2<T>(value: T, depth = 0): T {
  if (depth > 32) throw skillErrorV2('tenant_skill_json_invalid');
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (Array.isArray(value))
    return Object.freeze(value.map((item) => freezeSkillJsonV2(item, depth + 1))) as T;
  if (!skillRecordV2(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) {
    throw skillErrorV2('tenant_skill_json_invalid');
  }
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (['__proto__', 'constructor', 'prototype'].includes(key))
      throw skillErrorV2('tenant_skill_json_invalid');
    if (item !== undefined) result[key] = freezeSkillJsonV2(item, depth + 1);
  }
  return Object.freeze(result) as T;
}
export async function runSkillOperationV2<TAuthority extends object, TResult>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  service: string,
  methods: readonly string[],
  input: SkillInputV2,
  operation: (authority: TAuthority) => Promise<TResult>,
): Promise<TResult> {
  const actions = resolve();
  if (!actions) throw skillErrorV2('desktop_renderer_generation_actions_unavailable', 503);
  const lease = await actions.acquireServiceOperationLease<{
    bindOperation(config: DesktopRuntimeConfig): TAuthority;
  }>({
    service,
    version: '1.0.0',
    scope: Object.freeze({ kind: 'tenant', tenant_id: input.scope.tenantId }),
  });
  if (lease.status === 'rejected') throw skillErrorV2(lease.reasonCode, 503);
  let active = true;
  let failed = false;
  try {
    return await lease.useService(async (candidate) => {
      if (!active)
        throw new RuntimeV2Error(
          'tenant_skill_operation_released',
          'tenant skill operation released',
        );
      if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      if (
        !skillRecordV2(candidate) ||
        Object.keys(candidate).length !== 1 ||
        typeof candidate.bindOperation !== 'function'
      )
        throw skillErrorV2('tenant_skill_service_invalid', 502);
      const raw = candidate.bindOperation(input.config);
      if (
        !skillRecordV2(raw) ||
        Object.keys(raw).length !== methods.length ||
        methods.some((method) => typeof raw[method] !== 'function')
      ) {
        throw skillErrorV2('tenant_skill_service_invalid', 502);
      }
      const bound: Record<string, unknown> = {};
      for (const method of methods) {
        bound[method] = (...args: unknown[]) => {
          if (!active)
            throw new RuntimeV2Error(
              'tenant_skill_operation_released',
              'tenant skill operation released',
            );
          if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
          return Reflect.apply(raw[method] as (...values: unknown[]) => unknown, raw, args);
        };
      }
      const result = await operation(Object.freeze(bound) as TAuthority);
      if (!active)
        throw new RuntimeV2Error(
          'tenant_skill_operation_released',
          'tenant skill operation released',
        );
      if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return result;
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    active = false;
    try {
      await lease.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}
export async function requestSkillJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  options: Readonly<{ method?: 'GET' | 'POST'; body?: unknown; signal?: AbortSignal }> = {},
): Promise<unknown> {
  if (!desktopApiAuthenticationAvailable(config))
    throw skillErrorV2('tenant_management_trusted_session_required', 401);
  const headers = new Headers({ Accept: 'application/json' });
  const multipart = typeof FormData !== 'undefined' && options.body instanceof FormData;
  if (options.body !== undefined && !multipart) headers.set('Content-Type', 'application/json');
  if (config.apiKey.trim()) headers.set('Authorization', `Bearer ${config.apiKey.trim()}`);
  if (config.mode === 'local' && config.localApiToken.trim())
    headers.set('X-Agistack-Launch', config.localApiToken.trim());
  const response = await desktopApiFetch(config, path, {
    method: options.method ?? 'GET',
    headers,
    body: multipart
      ? (options.body as FormData)
      : options.body === undefined
        ? undefined
        : JSON.stringify(options.body),
    signal: options.signal,
  });
  const payload: unknown = response.headers.get('content-type')?.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) throw new DesktopApiError('tenant_skill_http_failed', response.status, payload);
  return payload;
}
export function skillMutationBodyV2(
  value: unknown,
  expectedRevision: number | undefined,
  resourceId?: string,
  targetRevision?: number,
): Readonly<Record<string, unknown>> {
  if (
    expectedRevision === undefined ||
    !Number.isSafeInteger(expectedRevision) ||
    expectedRevision < 0
  ) {
    throw skillErrorV2('managed_resource_revision_required', 428);
  }
  return Object.freeze({
    contract_version: 2,
    expected_revision: expectedRevision,
    idempotency_key: crypto.randomUUID(),
    ...(resourceId === undefined ? {} : { resource_id: resourceId }),
    value,
    ...(targetRevision === undefined ? {} : { target_revision: targetRevision }),
    vault_refs: Object.freeze([]),
  });
}
