import { DesktopApiError, desktopApiCredential } from '../../api/client';
import {
  desktopApiAuthenticationAvailable,
  desktopApiFetch,
} from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';

export type ProjectAdministrationAuthority = 'cloud' | 'local';
export type ProjectAdministrationScope = Readonly<{
  authority: ProjectAdministrationAuthority;
  tenantId: string;
  projectId: string;
}>;
export type ProjectMembershipRole = 'owner' | 'admin' | 'member' | 'viewer';
export type ProjectAdministrationOptions = Readonly<{ signal?: AbortSignal }>;
export type ProjectAdministrationSnapshotBase = Readonly<{
  scope: ProjectAdministrationScope;
  scopeRevision: number;
  authority: ProjectAdministrationAuthority;
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  contractVersion: '4.0.0';
  allowedActions: readonly string[];
  membershipRole: ProjectMembershipRole;
}>;

type RequestOptions = ProjectAdministrationOptions &
  Readonly<{
    method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
    body?: unknown;
    query?: Readonly<Record<string, string | number | boolean | undefined>>;
  }>;

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const ROLES = new Set<ProjectMembershipRole>(['owner', 'admin', 'member', 'viewer']);

export function requireProjectAdministrationScope(
  config: DesktopRuntimeConfig,
  scope: ProjectAdministrationScope,
  localReasonCode: string,
): ProjectAdministrationScope {
  const tenantId = requireIdentifier(scope.tenantId, 'project_administration_tenant_scope_invalid');
  const projectId = requireIdentifier(scope.projectId, 'project_administration_project_scope_invalid');
  if (config.mode === 'local' || scope.authority === 'local') {
    throw projectAdministrationError(localReasonCode, 501);
  }
  if (config.mode !== 'cloud' || scope.authority !== 'cloud') {
    throw projectAdministrationError('project_administration_authority_mode_mismatch', 409);
  }
  if (config.tenantId !== tenantId || config.projectId !== projectId) {
    throw projectAdministrationError('project_administration_configured_scope_mismatch', 409);
  }
  if (!desktopApiAuthenticationAvailable(config)) {
    throw projectAdministrationError('project_administration_trusted_session_required', 401);
  }
  return Object.freeze({ authority: 'cloud', tenantId, projectId });
}

export async function observeProjectAdministrationScope(
  config: DesktopRuntimeConfig,
  scope: ProjectAdministrationScope,
  options?: ProjectAdministrationOptions,
): Promise<Readonly<{ revision: number; membershipRole: ProjectMembershipRole }>> {
  const [contextPayload, userPayload, membersPayload] = await Promise.all([
    requestProjectAdministrationJson(config, '/api/v1/workspace-context', options),
    requestProjectAdministrationJson(config, '/api/v1/auth/me', options),
    requestProjectAdministrationJson(
      config,
      `/api/v1/projects/${encodeURIComponent(scope.projectId)}/members`,
      options,
    ),
  ]);
  const members: readonly unknown[] | null =
    isRecord(membersPayload) && Array.isArray(membersPayload.members)
      ? membersPayload.members
      : null;
  if (
    !isRecord(contextPayload) ||
    !isRecord(contextPayload.context) ||
    contextPayload.context.tenant_id !== scope.tenantId ||
    contextPayload.context.project_id !== scope.projectId ||
    !isRecord(userPayload) ||
    !members
  ) {
    throw projectAdministrationError('project_administration_scope_contract_invalid');
  }
  const userId = requireIdentifier(userPayload.id, 'project_administration_scope_contract_invalid');
  const member = members.find((value: unknown) => isRecord(value) && value.user_id === userId);
  if (
    !isRecord(member) ||
    typeof member.role !== 'string' ||
    !ROLES.has(member.role as ProjectMembershipRole)
  ) {
    throw projectAdministrationError('project_administration_membership_contract_invalid', 403);
  }
  return Object.freeze({
    revision: requireNonnegativeInteger(
      contextPayload.context.revision,
      'project_administration_scope_contract_invalid',
    ),
    membershipRole: member.role as ProjectMembershipRole,
  });
}

export async function requestProjectAdministrationJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptions = {},
): Promise<unknown> {
  const response = await request(config, path, options);
  const payload = await boundedPayload(response);
  if (!response.ok) throw responseError(response.status, payload);
  if (!payload.isJson || payload.value === null) {
    throw projectAdministrationError('project_administration_response_contract_invalid');
  }
  return payload.value;
}

export async function requestProjectAdministrationNoContent(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptions,
): Promise<void> {
  const response = await request(config, path, options);
  const payload = await boundedPayload(response);
  if (!response.ok) throw responseError(response.status, payload);
}

async function request(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptions,
): Promise<Response> {
  const url = new URL(path, 'https://desktop.invalid');
  for (const [name, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined) url.searchParams.set(name, String(value));
  }
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  return desktopApiFetch(config, `${url.pathname}${url.search}`, {
    method: options.method ?? 'GET',
    headers,
    credentials: 'omit',
    signal: options.signal,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
}

async function boundedPayload(
  response: Response,
): Promise<Readonly<{ isJson: boolean; value: unknown }>> {
  const declaredLength = Number(response.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw projectAdministrationError('project_administration_response_too_large');
  }
  const text = await response.text().catch(() => '');
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw projectAdministrationError('project_administration_response_too_large');
  }
  const isJson = (response.headers.get('content-type') ?? '')
    .toLowerCase()
    .includes('application/json');
  if (!isJson || !text) return Object.freeze({ isJson, value: text || null });
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

export function projectAdministrationError(reasonCode: string, status = 502): DesktopApiError {
  return new DesktopApiError(reasonCode, status, { reason_code: reasonCode });
}

export function requireIdentifier(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string' || !value || value.trim() !== value) {
    throw projectAdministrationError(reasonCode);
  }
  return value;
}

export function requireText(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string') throw projectAdministrationError(reasonCode);
  return value;
}

export function optionalText(value: unknown, reasonCode: string): string | null {
  if (value === undefined || value === null) return null;
  return requireText(value, reasonCode);
}

export function requireBoolean(value: unknown, reasonCode: string): boolean {
  if (typeof value !== 'boolean') throw projectAdministrationError(reasonCode);
  return value;
}

export function requireNonnegativeInteger(value: unknown, reasonCode: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw projectAdministrationError(reasonCode);
  }
  return value;
}

export function requireFiniteNumber(value: unknown, reasonCode: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw projectAdministrationError(reasonCode);
  }
  return value;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function structuredReason(value: unknown): string | null {
  return typeof value === 'string' && value && value.trim() === value ? value : null;
}
