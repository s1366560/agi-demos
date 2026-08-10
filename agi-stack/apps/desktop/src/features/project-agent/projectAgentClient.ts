import { DesktopApiError, desktopApiCredential } from '../../api/client';
import {
  desktopApiAuthenticationAvailable,
  desktopApiFetch,
} from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';

export type ProjectAgentAuthority = 'cloud' | 'local';
export type ProjectAgentScope = Readonly<{
  authority: ProjectAgentAuthority;
  tenantId: string;
  projectId: string;
}>;
export type ProjectAgentReadOptions = Readonly<{ signal?: AbortSignal }>;
export type ProjectAgentSnapshotBase = Readonly<{
  scope: ProjectAgentScope;
  scopeRevision: number;
  authority: ProjectAgentAuthority;
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  allowedActions: readonly string[];
}>;

type RequestOptions = ProjectAgentReadOptions &
  Readonly<{
    path: string;
    query?: Readonly<Record<string, string | number | undefined>>;
  }>;

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

export function requireProjectAgentScope(
  config: DesktopRuntimeConfig,
  scope: ProjectAgentScope,
  localReasonCode: string,
): ProjectAgentScope {
  const tenantId = requireIdentifier(scope.tenantId, 'project_agent_tenant_scope_invalid');
  const projectId = requireIdentifier(scope.projectId, 'project_agent_project_scope_invalid');
  if (config.mode === 'local' || scope.authority === 'local') {
    throw projectAgentError(localReasonCode, 501);
  }
  if (config.mode !== 'cloud' || scope.authority !== 'cloud') {
    throw projectAgentError('project_agent_authority_mode_mismatch', 409);
  }
  if (config.tenantId !== tenantId || config.projectId !== projectId) {
    throw projectAgentError('project_agent_configured_scope_mismatch', 409);
  }
  if (!desktopApiAuthenticationAvailable(config)) {
    throw projectAgentError('project_agent_trusted_session_required', 401);
  }
  return Object.freeze({ authority: 'cloud', tenantId, projectId });
}

export async function observeProjectAgentScope(
  config: DesktopRuntimeConfig,
  scope: ProjectAgentScope,
  options?: ProjectAgentReadOptions,
): Promise<number> {
  const payload = await requestProjectAgentJson(config, {
    path: '/api/v1/workspace-context',
    signal: options?.signal,
  });
  if (!isRecord(payload) || !isRecord(payload.context)) {
    throw projectAgentError('project_agent_scope_contract_invalid');
  }
  if (
    payload.context.tenant_id !== scope.tenantId ||
    payload.context.project_id !== scope.projectId
  ) {
    throw projectAgentError('project_agent_scope_conflict', 409);
  }
  return requireNonnegativeInteger(
    payload.context.revision,
    'project_agent_scope_contract_invalid',
  );
}

export async function requestProjectAgentJson(
  config: DesktopRuntimeConfig,
  options: RequestOptions,
): Promise<unknown> {
  const url = new URL(options.path, 'https://desktop.invalid');
  for (const [name, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined) url.searchParams.set(name, String(value));
  }
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const response = await desktopApiFetch(config, `${url.pathname}${url.search}`, {
    method: 'GET',
    headers,
    credentials: 'omit',
    signal: options.signal,
  });
  const payload = await boundedPayload(response);
  if (!response.ok) throw responseError(response.status, payload);
  if (!payload.isJson || payload.value === null) {
    throw projectAgentError('project_agent_response_contract_invalid');
  }
  return payload.value;
}

async function boundedPayload(
  response: Response,
): Promise<Readonly<{ isJson: boolean; value: unknown }>> {
  const declaredLength = Number(response.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw projectAgentError('project_agent_response_too_large');
  }
  const text = await response.text().catch(() => '');
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw projectAgentError('project_agent_response_too_large');
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

export function projectAgentError(reasonCode: string, status = 502): DesktopApiError {
  return new DesktopApiError(reasonCode, status, { reason_code: reasonCode });
}

export function requireIdentifier(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) {
    throw projectAgentError(reasonCode);
  }
  return value;
}

export function requireText(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string') throw projectAgentError(reasonCode);
  return value;
}

export function optionalText(value: unknown, reasonCode: string): string | null {
  if (value === undefined || value === null) return null;
  return requireText(value, reasonCode);
}

export function requireNonnegativeInteger(value: unknown, reasonCode: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw projectAgentError(reasonCode);
  }
  return value;
}

export function requireFiniteNumber(value: unknown, reasonCode: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw projectAgentError(reasonCode);
  }
  return value;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function structuredReason(value: unknown): string | null {
  return typeof value === 'string' && value && value === value.trim() ? value : null;
}
