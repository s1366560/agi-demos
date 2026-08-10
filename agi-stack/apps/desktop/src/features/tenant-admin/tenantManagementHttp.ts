import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import {
  desktopApiAuthenticationAvailable,
  desktopApiFetch,
} from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import {
  requireIdentifier,
  requireNonnegativeInteger,
  tenantAdminError,
  type TenantAdminRequestOptions,
  type TenantAdminRole,
  type TenantAdminScope,
} from './tenantAdminHttp';

export type TenantManagementAuthority = 'cloud' | 'sidecar';
export type TenantManagementLocalPolicy = 'cloud_only' | 'native_equivalent';
export type TenantManagementScope = TenantAdminScope;
export type TenantManagementWorkspaceScope = TenantManagementScope &
  Readonly<{ workspaceId: string }>;

export type TenantManagementAuthoritySnapshot<
  TScope extends TenantManagementScope,
  TData,
> = Readonly<{
  scope: TScope;
  scopeRevision: number;
  authority: TenantManagementAuthority;
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  contractVersion: '4.0.0';
  allowedActions: readonly string[];
  data: TData;
}>;

export type TenantManagementRequestOptions = TenantAdminRequestOptions;
export type TenantManagementScopeObservation = Readonly<{
  membershipRole: TenantAdminRole;
  scopeRevision: number;
}>;

type TenantManagementRequest = TenantManagementRequestOptions &
  Readonly<{
    method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    body?: Readonly<Record<string, unknown>> | null;
  }>;

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const TENANT_ROLES = new Set<TenantAdminRole>(['owner', 'admin', 'member', 'editor', 'viewer']);

export function requireTenantManagementScope<TScope extends TenantManagementScope>(
  config: DesktopRuntimeConfig,
  scope: TScope,
  localPolicy: TenantManagementLocalPolicy,
  localReasonCode: string,
): TScope {
  const configuredTenantId = requireIdentifier(
    config.tenantId,
    'tenant_management_configured_tenant_invalid',
  );
  const tenantId = requireIdentifier(scope.tenantId, 'tenant_management_tenant_scope_invalid');
  if (configuredTenantId !== tenantId) {
    throw tenantAdminError('tenant_management_tenant_scope_mismatch', 409);
  }
  if (config.mode !== scope.authority) {
    throw tenantAdminError('tenant_management_authority_mode_mismatch', 409);
  }
  if (config.mode === 'local' && localPolicy === 'cloud_only') {
    throw tenantAdminError(localReasonCode, 501);
  }
  if (!desktopApiAuthenticationAvailable(config)) {
    throw tenantAdminError('tenant_management_trusted_session_required', 401);
  }
  return scope;
}

export function authorityFor(config: DesktopRuntimeConfig): TenantManagementAuthority {
  return config.mode === 'local' ? 'sidecar' : 'cloud';
}

export async function observeTenantManagementRole(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): Promise<TenantAdminRole> {
  return (await observeTenantManagementScope(config, scope, options)).membershipRole;
}

export async function observeTenantManagementScope(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): Promise<TenantManagementScopeObservation> {
  const payload = await requestTenantManagementJson(
    config,
    '/api/v1/workspace-context',
    options,
  );
  if (!isRecord(payload) || !isRecord(payload.context)) {
    throw tenantAdminError('tenant_management_workspace_context_contract_invalid', 502);
  }
  const tenantId = requireIdentifier(
    payload.context.tenant_id,
    'tenant_management_workspace_context_contract_invalid',
  );
  const projectId = requireIdentifier(
    payload.context.project_id,
    'tenant_management_workspace_context_contract_invalid',
  );
  const configuredProjectId = requireIdentifier(
    config.projectId,
    'tenant_management_configured_project_invalid',
  );
  if (tenantId !== scope.tenantId || projectId !== configuredProjectId) {
    throw tenantAdminError('tenant_management_workspace_context_scope_conflict', 409);
  }
  const role = payload.membership_role;
  if (typeof role !== 'string' || !TENANT_ROLES.has(role as TenantAdminRole)) {
    throw tenantAdminError('tenant_management_membership_role_contract_invalid', 502);
  }
  return Object.freeze({
    membershipRole: role as TenantAdminRole,
    scopeRevision: requireNonnegativeInteger(
      payload.context.revision,
      'tenant_management_workspace_context_contract_invalid',
    ),
  });
}

export async function withStableTenantManagementAuthority<T>(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  options: TenantManagementRequestOptions | undefined,
  load: (authority: TenantManagementScopeObservation) => Promise<T>,
): Promise<TenantManagementScopeObservation & Readonly<{ value: T }>> {
  const before = await observeTenantManagementScope(config, scope, options);
  const value = await load(before);
  const after = await observeTenantManagementScope(config, scope, options);
  if (
    before.scopeRevision !== after.scopeRevision ||
    before.membershipRole !== after.membershipRole
  ) {
    throw tenantAdminError('tenant_management_authority_stale', 409);
  }
  return Object.freeze({ ...before, value });
}

export async function requestTenantManagementJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: TenantManagementRequest = {},
  allowNull = false,
): Promise<unknown> {
  const response = await request(config, path, options);
  const payload = await boundedPayload(response);
  if (!response.ok) throw responseError(response.status, payload);
  if (!payload.isJson || (!allowNull && payload.value === null)) {
    throw tenantAdminError('tenant_management_response_contract_invalid', 502);
  }
  return payload.value;
}

export async function requestTenantManagementNoContent(
  config: DesktopRuntimeConfig,
  path: string,
  options: TenantManagementRequest,
): Promise<void> {
  const response = await request(config, path, options);
  const payload = await boundedPayload(response);
  if (!response.ok) throw responseError(response.status, payload);
}

export async function requestNativeEquivalentJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: TenantManagementRequest,
  localUnavailableReason: string,
): Promise<unknown> {
  try {
    return await requestTenantManagementJson(config, path, options);
  } catch (error) {
    if (
      config.mode === 'local' &&
      error instanceof DesktopApiError &&
      (error.status === 404 || error.status === 501)
    ) {
      throw tenantAdminError(localUnavailableReason, 501);
    }
    throw error;
  }
}

export function requireRole(
  role: TenantAdminRole,
  allowed: readonly TenantAdminRole[],
  reasonCode: string,
): void {
  if (!allowed.includes(role)) throw tenantAdminError(reasonCode, 403);
}

async function request(
  config: DesktopRuntimeConfig,
  path: string,
  options: TenantManagementRequest,
): Promise<Response> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  const launchCapability = desktopLaunchCapability(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  return desktopApiFetch(config, path, {
    method: options.method ?? 'GET',
    headers,
    credentials: 'omit',
    signal: options.signal,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
}

async function boundedPayload(
  response: Response,
): Promise<Readonly<{ isJson: boolean; value: unknown }>> {
  const declaredLength = Number(response.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw tenantAdminError('tenant_management_response_too_large', 502);
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw tenantAdminError('tenant_management_response_too_large', 502);
  }
  if (!text) return Object.freeze({ isJson: false, value: null });
  if (!(response.headers.get('content-type')?.toLowerCase() ?? '').includes('application/json')) {
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
    ? (exactReason(value.reason_code) ??
      exactReason(value.code) ??
      (isRecord(detail) ? exactReason(detail.code) : null))
    : null;
  return new DesktopApiError(reasonCode ?? `HTTP ${status}`, status, value);
}

function exactReason(value: unknown): string | null {
  return typeof value === 'string' && value && value === value.trim() ? value : null;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function requireBoolean(value: unknown, reasonCode: string): boolean {
  if (typeof value !== 'boolean') throw tenantAdminError(reasonCode, 502);
  return value;
}

export function requireStringArray(value: unknown, reasonCode: string): readonly string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw tenantAdminError(reasonCode, 502);
  }
  return Object.freeze([...value]);
}

export function requireRecord(
  value: unknown,
  reasonCode: string,
): Readonly<Record<string, unknown>> {
  if (!isRecord(value)) throw tenantAdminError(reasonCode, 502);
  return Object.freeze({ ...value });
}
