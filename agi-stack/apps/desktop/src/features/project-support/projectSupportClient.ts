import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  ProjectSupportClient,
  ProjectSupportCloseResult,
  ProjectSupportCreateInput,
  ProjectSupportListQuery,
  ProjectSupportListSnapshot,
  ProjectSupportPriority,
  ProjectSupportRequestOptions,
  ProjectSupportScope,
  ProjectSupportStatus,
  ProjectSupportTicket,
} from './projectSupportTypes';

const PAGE_SIZE = 25;
const CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'create',
  'close',
  'retry',
]);
const LOCAL_REASON_CODE = 'local_support_service_not_applicable';
const PRIORITIES = new Set<ProjectSupportPriority>([
  'low',
  'medium',
  'high',
  'urgent',
]);
const STATUSES = new Set<ProjectSupportStatus>([
  'open',
  'in_progress',
  'resolved',
  'closed',
]);

export function createProjectSupportClient(
  config: DesktopRuntimeConfig,
): ProjectSupportClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async list(scope, query = {}, options) {
      requireScope(runtimeConfig, scope);
      if (scope.authority === 'local') return localSnapshot(scope, query);
      const limit = boundedInteger(query.limit, PAGE_SIZE, 1, 100);
      const offset = boundedInteger(query.offset, 0, 0, Number.MAX_SAFE_INTEGER);
      const search = new URLSearchParams({
        tenant_id: scope.tenantId,
        limit: String(limit),
        offset: String(offset),
      });
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/support/tickets?${search}`,
        { method: 'GET', signal: options?.signal },
      );
      return readListSnapshot(payload, scope, limit, offset);
    },
    async create(scope, input, options) {
      requireScope(runtimeConfig, scope);
      requireCloud(scope);
      const normalized = normalizeCreateInput(input);
      const payload = await requestJson(
        runtimeConfig,
        '/api/v1/support/tickets',
        {
          method: 'POST',
          signal: options?.signal,
          body: {
            tenant_id: scope.tenantId,
            ...normalized,
          },
        },
      );
      return readCreatedTicket(payload, scope, normalized);
    },
    async close(scope, ticketId, options) {
      requireScope(runtimeConfig, scope);
      requireCloud(scope);
      const id = requireIdentifier(ticketId, 'project_support_ticket_id_invalid');
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/support/tickets/${encodeURIComponent(id)}/close`,
        { method: 'POST', signal: options?.signal },
      );
      return readCloseResult(payload, id);
    },
  });
}

type RequestInput = Readonly<{
  method: 'GET' | 'POST';
  signal?: AbortSignal;
  body?: Readonly<Record<string, unknown>>;
}>;

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  input: RequestInput,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (input.body) headers.set('Content-Type', 'application/json');
  const response = await desktopApiFetch(config, path, {
    method: input.method,
    headers,
    signal: input.signal,
    body: input.body ? JSON.stringify(input.body) : undefined,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) {
    throw contractError('cloud_project_support_contract_invalid');
  }
  return payload;
}

function readListSnapshot(
  payload: unknown,
  scope: ProjectSupportScope,
  expectedLimit: number,
  expectedOffset: number,
): ProjectSupportListSnapshot {
  const reason = 'cloud_project_support_contract_invalid';
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.tickets) ||
    !isNonnegativeInteger(payload.total) ||
    payload.limit !== expectedLimit ||
    payload.offset !== expectedOffset ||
    typeof payload.has_more !== 'boolean'
  ) {
    throw contractError(reason);
  }
  const tickets = Object.freeze(
    payload.tickets.map((ticket) => readTicket(ticket, scope, reason)),
  );
  if (
    tickets.length > expectedLimit ||
    tickets.length > payload.total ||
    payload.has_more !== expectedOffset + tickets.length < payload.total
  ) {
    throw contractError(reason);
  }
  return Object.freeze({
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: CLOUD_ACTIONS,
    authorityRevision: null,
    tickets,
    total: payload.total,
    limit: expectedLimit,
    offset: expectedOffset,
    hasMore: payload.has_more,
  });
}

function readTicket(
  payload: unknown,
  scope: ProjectSupportScope,
  reason: string,
): ProjectSupportTicket {
  if (
    !isRecord(payload) ||
    payload.tenant_id !== scope.tenantId ||
    !isPriority(payload.priority) ||
    !isStatus(payload.status)
  ) {
    throw contractError(reason);
  }
  const status = payload.status;
  return Object.freeze({
    id: requireIdentifier(payload.id, reason),
    tenantId: scope.tenantId,
    subject: requireText(payload.subject, reason),
    message: requireText(payload.message, reason),
    priority: payload.priority,
    status,
    createdAt: requireTimestamp(payload.created_at, reason),
    updatedAt: requireTimestamp(payload.updated_at, reason),
    resolvedAt: nullableTimestamp(payload.resolved_at, reason),
    allowedActions: Object.freeze(
      status === 'open' || status === 'in_progress'
        ? ['view', 'close']
        : ['view'],
    ),
  });
}

function readCreatedTicket(
  payload: unknown,
  scope: ProjectSupportScope,
  input: ProjectSupportCreateInput,
): ProjectSupportTicket {
  const reason = 'cloud_project_support_create_contract_invalid';
  if (
    !isRecord(payload) ||
    payload.subject !== input.subject ||
    payload.message !== input.message ||
    payload.priority !== input.priority ||
    payload.status !== 'open'
  ) {
    throw contractError(reason);
  }
  return Object.freeze({
    id: requireIdentifier(payload.id, reason),
    tenantId: scope.tenantId,
    subject: input.subject,
    message: input.message,
    priority: input.priority,
    status: 'open',
    createdAt: requireTimestamp(payload.created_at, reason),
    updatedAt: requireTimestamp(payload.updated_at, reason),
    resolvedAt: null,
    allowedActions: Object.freeze(['view', 'close']),
  });
}

function readCloseResult(
  payload: unknown,
  expectedId: string,
): ProjectSupportCloseResult {
  const reason = 'cloud_project_support_close_contract_invalid';
  if (
    !isRecord(payload) ||
    payload.id !== expectedId ||
    payload.status !== 'closed'
  ) {
    throw contractError(reason);
  }
  return Object.freeze({
    id: expectedId,
    status: 'closed',
    resolvedAt: requireTimestamp(payload.resolved_at, reason),
  });
}

function localSnapshot(
  scope: ProjectSupportScope,
  query: ProjectSupportListQuery,
): ProjectSupportListSnapshot {
  return Object.freeze({
    scope,
    authority: 'local',
    availability: 'not_applicable',
    reasonCode: LOCAL_REASON_CODE,
    serviceVersion: null,
    contractVersion: null,
    allowedActions: Object.freeze([]),
    authorityRevision: null,
    tickets: Object.freeze([]),
    total: 0,
    limit: boundedInteger(query.limit, PAGE_SIZE, 1, 100),
    offset: boundedInteger(query.offset, 0, 0, Number.MAX_SAFE_INTEGER),
    hasMore: false,
  });
}

function requireCloud(scope: ProjectSupportScope): void {
  if (scope.authority === 'cloud') return;
  throw new DesktopApiError(LOCAL_REASON_CODE, 501, {
    reason_code: LOCAL_REASON_CODE,
  });
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: ProjectSupportScope,
): void {
  if (
    scope.authority !== config.mode ||
    scope.tenantId !== config.tenantId ||
    scope.projectId !== config.projectId
  ) {
    throw new Error('project_support_scope_mismatch');
  }
}

function normalizeCreateInput(
  input: ProjectSupportCreateInput,
): ProjectSupportCreateInput {
  const subject = input.subject.trim();
  const message = input.message.trim();
  if (
    !subject ||
    subject.length > 500 ||
    !message ||
    message.length > 20_000 ||
    !isPriority(input.priority)
  ) {
    throw new Error('project_support_create_input_invalid');
  }
  return Object.freeze({ subject, message, priority: input.priority });
}

function boundedInteger(
  input: number | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  if (input === undefined) return fallback;
  if (!Number.isSafeInteger(input) || input < minimum || input > maximum) {
    throw new Error('project_support_pagination_invalid');
  }
  return input;
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string') {
    return payload.detail;
  }
  return `Project Support request failed (${status})`;
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 502, { reason_code: reasonCode });
}

function requireIdentifier(input: unknown, reason: string): string {
  if (typeof input !== 'string' || !input || input.trim() !== input) {
    throw contractError(reason);
  }
  return input;
}

function requireText(input: unknown, reason: string): string {
  if (typeof input !== 'string' || !input.trim()) throw contractError(reason);
  return input;
}

function requireTimestamp(input: unknown, reason: string): string {
  if (
    typeof input !== 'string' ||
    !input.trim() ||
    Number.isNaN(Date.parse(input))
  ) {
    throw contractError(reason);
  }
  return input;
}

function nullableTimestamp(input: unknown, reason: string): string | null {
  return input === null ? null : requireTimestamp(input, reason);
}

function isPriority(input: unknown): input is ProjectSupportPriority {
  return typeof input === 'string' && PRIORITIES.has(input as ProjectSupportPriority);
}

function isStatus(input: unknown): input is ProjectSupportStatus {
  return typeof input === 'string' && STATUSES.has(input as ProjectSupportStatus);
}

function isNonnegativeInteger(input: unknown): input is number {
  return Number.isSafeInteger(input) && (input as number) >= 0;
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return input !== null && typeof input === 'object' && !Array.isArray(input);
}
