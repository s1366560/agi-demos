import {
  DesktopApiError,
  desktopApiCredential,
} from '../../api/client';
import {
  desktopApiAuthenticationAvailable,
  desktopApiFetch,
} from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';

export type TenantAdminAuthority = 'cloud' | 'local';
export type TenantAdminRole = 'owner' | 'admin' | 'member' | 'editor' | 'viewer';
export type TenantAdminScope = Readonly<{
  authority: TenantAdminAuthority;
  tenantId: string;
}>;
export type TenantAdminRequestOptions = Readonly<{ signal?: AbortSignal }>;

type TenantAdminRequest = TenantAdminRequestOptions &
  Readonly<{
    method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
    body?: Readonly<Record<string, unknown>>;
  }>;

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const TENANT_ROLES = new Set<TenantAdminRole>(['owner', 'admin', 'member', 'editor', 'viewer']);

export function requireCloudTenantScope<TScope extends TenantAdminScope>(
  config: DesktopRuntimeConfig,
  scope: TScope,
  localReasonCode: string,
): TScope {
  if (config.mode === 'local' || scope.authority === 'local') {
    throw tenantAdminError(localReasonCode, 501);
  }
  if (config.mode !== 'cloud' || scope.authority !== 'cloud') {
    throw tenantAdminError('tenant_admin_authority_mode_mismatch', 409);
  }
  const configuredTenantId = requireIdentifier(
    config.tenantId,
    'tenant_admin_configured_tenant_invalid',
  );
  const tenantId = requireIdentifier(scope.tenantId, 'tenant_admin_tenant_scope_invalid');
  if (configuredTenantId !== tenantId) {
    throw tenantAdminError('tenant_admin_configured_tenant_scope_mismatch', 409);
  }
  if (!desktopApiAuthenticationAvailable(config)) {
    throw tenantAdminError('tenant_admin_trusted_session_required', 401);
  }
  return scope;
}

export async function observeTenantMembership(
  config: DesktopRuntimeConfig,
  scope: TenantAdminScope,
  options?: TenantAdminRequestOptions,
): Promise<TenantAdminRole> {
  const payload = await requestTenantAdminJson(config, '/api/v1/workspace-context', options);
  if (!isRecord(payload) || !isRecord(payload.context)) {
    throw tenantAdminError('tenant_admin_workspace_context_contract_invalid', 502);
  }
  const tenantId = requireIdentifier(
    payload.context.tenant_id,
    'tenant_admin_workspace_context_contract_invalid',
  );
  if (tenantId !== scope.tenantId) {
    throw tenantAdminError('tenant_admin_workspace_context_scope_conflict', 409);
  }
  const role = payload.membership_role;
  if (typeof role !== 'string' || !TENANT_ROLES.has(role as TenantAdminRole)) {
    throw tenantAdminError('tenant_admin_membership_role_contract_invalid', 502);
  }
  return role as TenantAdminRole;
}

export async function requestTenantAdminJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: TenantAdminRequest = {},
): Promise<unknown> {
  const response = await request(config, path, options);
  const payload = await boundedPayload(response);
  if (!response.ok) throw responseError(response.status, payload);
  if (!payload.isJson || payload.value === null) {
    throw tenantAdminError('tenant_admin_response_contract_invalid', 502);
  }
  return payload.value;
}

export async function requestTenantAdminNoContent(
  config: DesktopRuntimeConfig,
  path: string,
  options: TenantAdminRequest,
): Promise<void> {
  const response = await request(config, path, options);
  const payload = await boundedPayload(response);
  if (!response.ok) throw responseError(response.status, payload);
}

async function request(
  config: DesktopRuntimeConfig,
  path: string,
  options: TenantAdminRequest,
): Promise<Response> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  if (options.body) headers.set('Content-Type', 'application/json');
  return desktopApiFetch(config, path, {
    method: options.method ?? 'GET',
    headers,
    credentials: 'omit',
    signal: options.signal,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
}

async function boundedPayload(
  response: Response,
): Promise<Readonly<{ isJson: boolean; value: unknown }>> {
  const declaredLength = Number(response.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw tenantAdminError('tenant_admin_response_too_large', 502);
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw tenantAdminError('tenant_admin_response_too_large', 502);
  }
  if (!text) return Object.freeze({ isJson: false, value: null });
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (!contentType.includes('application/json')) {
    return Object.freeze({ isJson: false, value: text });
  }
  try {
    return Object.freeze({ isJson: true, value: JSON.parse(text) as unknown });
  } catch {
    return Object.freeze({ isJson: true, value: null });
  }
}

function responseError(
  status: number,
  payload: Readonly<{ isJson: boolean; value: unknown }>,
): DesktopApiError {
  const value = payload.value;
  const detail = isRecord(value) ? value.detail : null;
  const reasonCode = isRecord(value)
    ? (structuredReason(value.reason_code) ??
      structuredReason(value.code) ??
      (isRecord(detail) ? structuredReason(detail.code) : null))
    : null;
  return new DesktopApiError(reasonCode ?? `HTTP ${status}`, status, value);
}

function structuredReason(value: unknown): string | null {
  return typeof value === 'string' && value && value === value.trim() ? value : null;
}

export function tenantAdminError(reasonCode: string, status = 502): DesktopApiError {
  return new DesktopApiError(reasonCode, status, { reason_code: reasonCode });
}

export function requireIdentifier(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) {
    throw tenantAdminError(reasonCode, 422);
  }
  return value;
}

export function requireText(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string') throw tenantAdminError(reasonCode, 502);
  return value;
}

export function optionalText(value: unknown, reasonCode: string): string | null {
  if (value === null || value === undefined) return null;
  return requireText(value, reasonCode);
}

export function requireFiniteNumber(value: unknown, reasonCode: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw tenantAdminError(reasonCode, 502);
  }
  return value;
}

export function requireNonnegativeInteger(value: unknown, reasonCode: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw tenantAdminError(reasonCode, 502);
  }
  return value;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
