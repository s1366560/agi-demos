import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';

export type ProjectKnowledgeAuthority = 'cloud' | 'local';
export type ProjectKnowledgeScope = Readonly<{
  authority: ProjectKnowledgeAuthority;
  tenantId: string;
  projectId: string;
}>;
export type ProjectKnowledgeReadOptions = Readonly<{ signal?: AbortSignal }>;
export type ProjectKnowledgeSnapshotBase = Readonly<{
  scope: ProjectKnowledgeScope;
  scopeRevision: number;
  authority: ProjectKnowledgeAuthority;
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  allowedActions: readonly string[];
}>;
export interface ProjectKnowledgeClient<TSnapshot extends ProjectKnowledgeSnapshotBase> {
  load(scope: ProjectKnowledgeScope, options?: ProjectKnowledgeReadOptions): Promise<TSnapshot>;
}

export type ProjectKnowledgeMutationHeaders = Readonly<{
  idempotencyKey: string;
  expectedRevision?: number;
}>;

type RequestOptions = ProjectKnowledgeReadOptions &
  Readonly<{
    method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
    body?: Readonly<Record<string, unknown>>;
    mutation?: ProjectKnowledgeMutationHeaders;
  }>;

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

export function requireProjectKnowledgeScope(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
  localReasonCode: string,
): ProjectKnowledgeScope {
  const tenantId = requireIdentifier(scope.tenantId, 'project_knowledge_tenant_scope_invalid');
  const projectId = requireIdentifier(scope.projectId, 'project_knowledge_project_scope_invalid');
  if (config.mode === 'local' || scope.authority === 'local') {
    throw projectKnowledgeError(localReasonCode, 501);
  }
  if (config.mode !== 'cloud' || scope.authority !== 'cloud') {
    throw projectKnowledgeError('project_knowledge_authority_mode_mismatch', 409);
  }
  if (config.tenantId !== tenantId || config.projectId !== projectId) {
    throw projectKnowledgeError('project_knowledge_configured_scope_mismatch', 409);
  }
  if (!desktopApiAuthenticationAvailable(config)) {
    throw projectKnowledgeError('project_knowledge_trusted_session_required', 401);
  }
  return Object.freeze({ authority: 'cloud', tenantId, projectId });
}

export async function observeProjectKnowledgeScope(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
  options?: ProjectKnowledgeReadOptions,
): Promise<number> {
  const payload = await requestProjectKnowledgeJson(config, '/api/v1/workspace-context', options);
  if (!isRecord(payload) || !isRecord(payload.context)) {
    throw projectKnowledgeError('project_knowledge_scope_contract_invalid');
  }
  const context = payload.context;
  if (context.tenant_id !== scope.tenantId || context.project_id !== scope.projectId) {
    throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
  }
  return requireNonnegativeInteger(context.revision, 'project_knowledge_scope_contract_invalid');
}

export async function requestProjectKnowledgeJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptions = {},
): Promise<unknown> {
  const response = await request(config, path, options);
  const payload = await boundedPayload(response);
  if (!response.ok) throw responseError(response.status, payload);
  if (!payload.isJson || payload.value === null) {
    throw projectKnowledgeError('project_knowledge_response_contract_invalid');
  }
  return payload.value;
}

export async function requestProjectKnowledgeNoContent(
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
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.mutation !== undefined) {
    if (!options.method || options.method === 'GET') {
      throw projectKnowledgeError('project_knowledge_mutation_headers_invalid', 422);
    }
    applyMutationHeaders(headers, options.mutation);
  }
  if (options.body) headers.set('Content-Type', 'application/json');
  return desktopApiFetch(config, path, {
    method: options.method ?? 'GET',
    headers,
    credentials: 'omit',
    signal: options.signal,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
}

function applyMutationHeaders(headers: Headers, input: ProjectKnowledgeMutationHeaders): void {
  const reason = 'project_knowledge_mutation_headers_invalid';
  if (
    !isRecord(input) ||
    Object.keys(input).some((key) => key !== 'idempotencyKey' && key !== 'expectedRevision') ||
    typeof input.idempotencyKey !== 'string' ||
    !input.idempotencyKey ||
    input.idempotencyKey !== input.idempotencyKey.trim() ||
    input.idempotencyKey.length > 512 ||
    /[^\x20-\x7e]/.test(input.idempotencyKey)
  ) {
    throw projectKnowledgeError(reason, 422);
  }
  const revision = input.expectedRevision;
  if (revision !== undefined) {
    if (!Number.isSafeInteger(revision) || revision < 0 || revision > 4_294_967_295) {
      throw projectKnowledgeError(reason, 422);
    }
    headers.set('X-Expected-Revision', String(revision));
  }
  headers.set('Idempotency-Key', input.idempotencyKey);
}

async function boundedPayload(
  response: Response,
): Promise<Readonly<{ isJson: boolean; value: unknown }>> {
  const declaredLength = Number(response.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw projectKnowledgeError('project_knowledge_response_too_large');
  }
  const text = await response.text().catch(() => '');
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw projectKnowledgeError('project_knowledge_response_too_large');
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
  const nativeError = isRecord(value) ? value.error : null;
  const reasonCode = isRecord(value)
    ? (structuredReason(value.reason_code) ??
      structuredReason(value.code) ??
      (isRecord(detail) ? structuredReason(detail.code) : null) ??
      (isRecord(nativeError) ? structuredReason(nativeError.code) : null))
    : null;
  return new DesktopApiError(reasonCode ?? `HTTP ${status}`, status, value);
}

function structuredReason(value: unknown): string | null {
  return typeof value === 'string' && value && value === value.trim() ? value : null;
}

export function projectKnowledgeError(reasonCode: string, status = 502): DesktopApiError {
  return new DesktopApiError(reasonCode, status, { reason_code: reasonCode });
}

export function requireIdentifier(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) {
    throw projectKnowledgeError(reasonCode, 422);
  }
  return value;
}

export function requireText(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string') throw projectKnowledgeError(reasonCode);
  return value;
}

export function optionalText(value: unknown, reasonCode: string): string | null {
  if (value === undefined || value === null) return null;
  return requireText(value, reasonCode);
}

export function requireNonnegativeInteger(value: unknown, reasonCode: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw projectKnowledgeError(reasonCode);
  }
  return value;
}

export function requireFiniteNumber(value: unknown, reasonCode: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw projectKnowledgeError(reasonCode);
  }
  return value;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
