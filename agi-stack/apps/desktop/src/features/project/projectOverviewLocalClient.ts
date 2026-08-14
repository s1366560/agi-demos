import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

const PROJECT_OVERVIEW_CONTRACT_VERSION = '4.0.0' as const;
const PROJECT_OVERVIEW_REASON = 'local_project_overview_timeline_projection_only' as const;
const PROJECT_GRAPH_REASON = 'local_project_graph_projection_unavailable' as const;
const PROJECT_STORAGE_REASON = 'local_project_storage_quota_not_applicable' as const;
const PROJECT_COLLABORATION_REASON =
  'local_project_collaboration_governance_not_applicable' as const;
const TIMELINE_SOURCE = 'desktop_timeline' as const;
const MAX_RESPONSE_BYTES = 256 * 1024;
const RECENT_ITEM_LIMIT = 5;

export type LocalProjectOverviewScope = Readonly<{
  authority: 'local';
  tenantId: string;
  projectId: string;
}>;

export type LocalProjectOverviewCapabilityScope = Readonly<{
  tenantId: string;
  projectId: string;
  workspaceId: null;
  instanceId: null;
}>;

export type LocalProjectOverviewCapability = Readonly<{
  availability: 'degraded';
  reasonCode: typeof PROJECT_OVERVIEW_REASON;
  serviceVersion: string;
  contractVersion: typeof PROJECT_OVERVIEW_CONTRACT_VERSION;
  allowedActions: readonly ['view'];
  scope: LocalProjectOverviewCapabilityScope;
  authorityRevision: number;
}>;

export type LocalProjectOverviewProject = Readonly<{
  id: string;
  tenantId: string;
  name: string;
  description: string | null;
  agentConversationMode: string;
  createdAt: string;
}>;

export type LocalProjectOverviewKnowledgeItem = Readonly<{
  id: string;
  conversationId: string;
  title: string;
  content: string;
  resultType: string;
  source: typeof TIMELINE_SOURCE;
  createdAt: string | null;
  tags: readonly string[];
}>;

export type LocalAvailableField<T> = Readonly<{
  availability: 'available';
  reasonCode: null;
  value: T;
}>;

export type LocalConversationStatusSummary = Readonly<{
  total: number;
  idle: number;
  queued: number;
  running: number;
  attention: number;
  completed: number;
  failed: number;
  cancelled: number;
}>;

export type LocalConversationStatusRequest = Readonly<{
  generation: number;
  scope: string;
}>;

export function nextLocalConversationStatusRequest(
  currentGeneration: number,
  scope: string,
): LocalConversationStatusRequest {
  return Object.freeze({ generation: currentGeneration + 1, scope });
}

export function isCurrentLocalConversationStatusRequest(
  request: LocalConversationStatusRequest,
  currentGeneration: number,
  currentScope: string,
): boolean {
  return request.generation === currentGeneration && request.scope === currentScope;
}

export type LocalRecentKnowledgeField = Readonly<{
  availability: 'degraded';
  reasonCode: typeof PROJECT_OVERVIEW_REASON;
  source: typeof TIMELINE_SOURCE;
  total: number;
  value: readonly LocalProjectOverviewKnowledgeItem[];
}>;

export type LocalUnavailableField = Readonly<{
  availability: 'unavailable';
  reasonCode: typeof PROJECT_GRAPH_REASON;
  value: null;
}>;

export type LocalNotApplicableField<
  Reason extends typeof PROJECT_STORAGE_REASON | typeof PROJECT_COLLABORATION_REASON,
> = Readonly<{
  availability: 'not_applicable';
  reasonCode: Reason;
  value: null;
}>;

export type LocalProjectOverviewSnapshot = Readonly<{
  scope: LocalProjectOverviewScope;
  capability: LocalProjectOverviewCapability;
  backfillCursor: string | null;
  project: LocalAvailableField<LocalProjectOverviewProject>;
  conversationCount: LocalAvailableField<number>;
  conversationStatusSummary: LocalAvailableField<LocalConversationStatusSummary>;
  recentKnowledgeItems: LocalRecentKnowledgeField;
  activeNodes: LocalUnavailableField;
  storageQuota: LocalNotApplicableField<typeof PROJECT_STORAGE_REASON>;
  collaborators: LocalNotApplicableField<typeof PROJECT_COLLABORATION_REASON>;
}>;

export type LocalProjectOverviewReadOptions = Readonly<{
  signal?: AbortSignal;
}>;

export interface LocalProjectOverviewClient {
  load(
    scope: LocalProjectOverviewScope,
    options?: LocalProjectOverviewReadOptions,
  ): Promise<LocalProjectOverviewSnapshot>;
}

export function createLocalProjectOverviewClient(
  config: DesktopRuntimeConfig,
): LocalProjectOverviewClient {
  if (config.mode !== 'local') {
    throw contractError('local_project_overview_config_required');
  }
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(
      scope: LocalProjectOverviewScope,
      options?: LocalProjectOverviewReadOptions,
    ): Promise<LocalProjectOverviewSnapshot> {
      const currentScope = requireLocalScope(scope);
      requireRuntimeScope(runtimeConfig, currentScope);
      const sessionCredential = desktopApiCredential(runtimeConfig);
      if (!sessionCredential) {
        throw contractError('local_project_overview_session_credential_required');
      }
      const launchCapability = desktopLaunchCapability(runtimeConfig);
      if (!launchCapability) {
        throw contractError('local_project_overview_launch_capability_required');
      }
      const payload = await requestLocalJson(
        runtimeConfig,
        currentScope,
        sessionCredential,
        launchCapability,
        options,
      );
      const snapshot = parseLocalProjectOverviewPayload(payload, currentScope);
      if (!snapshot) {
        throw contractError('local_project_overview_contract_invalid');
      }
      return snapshot;
    },
  });
}

export function parseLocalProjectOverviewPayload(
  input: unknown,
  expectedScope: LocalProjectOverviewScope,
): LocalProjectOverviewSnapshot | null {
  if (!isLocalScope(expectedScope) || !isExactRecord(input, TOP_LEVEL_KEYS)) return null;
  if (
    input.capability !== 'project_overview' ||
    input.availability !== 'degraded' ||
    input.reason_code !== PROJECT_OVERVIEW_REASON ||
    !isServiceVersion(input.service_version) ||
    input.contract_version !== PROJECT_OVERVIEW_CONTRACT_VERSION ||
    !isViewOnlyActions(input.allowed_actions) ||
    !isSafeNonnegativeInteger(input.authority_revision) ||
    !isBackfillCursor(input.backfill_cursor)
  ) {
    return null;
  }

  const capabilityScope = parseCapabilityScope(input.scope, expectedScope);
  const project = parseProjectField(input.project, expectedScope);
  const conversationCount = parseConversationCount(input.conversation_count);
  const conversationStatusSummary = parseConversationStatusSummary(
    input.conversation_status_summary,
  );
  const recentKnowledgeItems = parseRecentKnowledge(input.recent_knowledge_items);
  const activeNodes = parseNullField(
    input.active_nodes,
    'unavailable',
    PROJECT_GRAPH_REASON,
  );
  const storageQuota = parseNullField(
    input.storage_quota,
    'not_applicable',
    PROJECT_STORAGE_REASON,
  );
  const collaborators = parseNullField(
    input.collaborators,
    'not_applicable',
    PROJECT_COLLABORATION_REASON,
  );
  if (
    !capabilityScope ||
    !project ||
    !conversationCount ||
    !conversationStatusSummary ||
    conversationStatusSummary.value.total !== conversationCount.value ||
    !recentKnowledgeItems ||
    !activeNodes ||
    !storageQuota ||
    !collaborators
  ) {
    return null;
  }

  return {
    scope: {
      authority: 'local',
      tenantId: expectedScope.tenantId,
      projectId: expectedScope.projectId,
    },
    capability: {
      availability: 'degraded',
      reasonCode: PROJECT_OVERVIEW_REASON,
      serviceVersion: input.service_version,
      contractVersion: PROJECT_OVERVIEW_CONTRACT_VERSION,
      allowedActions: ['view'],
      scope: capabilityScope,
      authorityRevision: input.authority_revision,
    },
    backfillCursor: input.backfill_cursor,
    project,
    conversationCount,
    conversationStatusSummary,
    recentKnowledgeItems,
    activeNodes,
    storageQuota,
    collaborators,
  };
}

async function requestLocalJson(
  config: DesktopRuntimeConfig,
  scope: LocalProjectOverviewScope,
  sessionCredential: string,
  launchCapability: string,
  options?: LocalProjectOverviewReadOptions,
): Promise<unknown> {
  const headers = new Headers({
    Accept: 'application/json',
    Authorization: `Bearer ${sessionCredential}`,
    'X-Agistack-Launch': launchCapability,
  });
  const path = `/api/v1/projects/${encodeURIComponent(scope.projectId)}/overview`;
  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: 'GET',
    headers,
    credentials: 'omit',
    signal: options?.signal,
  });
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  const isJson = contentType.includes('application/json');
  const declaredLength = parseContentLength(response.headers.get('content-length'));
  if (declaredLength !== null && declaredLength > MAX_RESPONSE_BYTES) {
    throw contractError('local_project_overview_response_too_large');
  }
  const text = await response.text().catch(() => '');
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw contractError('local_project_overview_response_too_large');
  }
  const payload = isJson ? parseJson(text) : text;
  if (!response.ok) {
    throw new DesktopApiError(errorMessage(response.status, payload), response.status, payload);
  }
  if (!isJson) {
    throw contractError('local_project_overview_response_not_json');
  }
  if (payload === null) {
    throw contractError('local_project_overview_response_malformed');
  }
  return payload;
}

function requireLocalScope(scope: LocalProjectOverviewScope): LocalProjectOverviewScope {
  if (!isLocalScope(scope)) {
    throw contractError('local_project_overview_scope_invalid');
  }
  return scope;
}

function requireRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: LocalProjectOverviewScope,
): void {
  if (
    !isExactIdentifier(config.tenantId) ||
    !isExactIdentifier(config.projectId) ||
    config.tenantId !== scope.tenantId ||
    config.projectId !== scope.projectId
  ) {
    throw contractError('local_project_overview_runtime_scope_mismatch');
  }
}

function parseCapabilityScope(
  input: unknown,
  expectedScope: LocalProjectOverviewScope,
): LocalProjectOverviewCapabilityScope | null {
  if (
    !isExactRecord(input, CAPABILITY_SCOPE_KEYS) ||
    input.tenant_id !== expectedScope.tenantId ||
    input.project_id !== expectedScope.projectId ||
    input.workspace_id !== null ||
    input.instance_id !== null
  ) {
    return null;
  }
  return {
    tenantId: expectedScope.tenantId,
    projectId: expectedScope.projectId,
    workspaceId: null,
    instanceId: null,
  };
}

function parseProjectField(
  input: unknown,
  expectedScope: LocalProjectOverviewScope,
): LocalAvailableField<LocalProjectOverviewProject> | null {
  if (
    !isExactRecord(input, FIELD_KEYS) ||
    input.availability !== 'available' ||
    input.reason_code !== null ||
    !isExactRecord(input.value, PROJECT_KEYS)
  ) {
    return null;
  }
  const project = input.value;
  if (
    project.id !== expectedScope.projectId ||
    project.tenant_id !== expectedScope.tenantId ||
    !isNonEmptyString(project.name) ||
    !isNullableString(project.description) ||
    !isNonEmptyString(project.agent_conversation_mode) ||
    !isNonEmptyString(project.created_at)
  ) {
    return null;
  }
  return {
    availability: 'available',
    reasonCode: null,
    value: {
      id: project.id,
      tenantId: project.tenant_id,
      name: project.name,
      description: project.description,
      agentConversationMode: project.agent_conversation_mode,
      createdAt: project.created_at,
    },
  };
}

function parseConversationCount(input: unknown): LocalAvailableField<number> | null {
  if (
    !isExactRecord(input, FIELD_KEYS) ||
    input.availability !== 'available' ||
    input.reason_code !== null ||
    !isSafeNonnegativeInteger(input.value)
  ) {
    return null;
  }
  return {
    availability: 'available',
    reasonCode: null,
    value: input.value,
  };
}

function parseConversationStatusSummary(
  input: unknown,
): LocalAvailableField<LocalConversationStatusSummary> | null {
  if (
    !isExactRecord(input, FIELD_KEYS) ||
    input.availability !== 'available' ||
    input.reason_code !== null ||
    !isExactRecord(input.value, CONVERSATION_STATUS_KEYS)
  ) {
    return null;
  }
  const value = input.value;
  if (!CONVERSATION_STATUS_KEYS.every((key) => isSafeNonnegativeInteger(value[key]))) {
    return null;
  }
  const partitionTotal = CONVERSATION_STATUS_BUCKET_KEYS.reduce(
    (total, key) => total + Number(value[key]),
    0,
  );
  if (partitionTotal !== Number(value.total)) return null;
  return {
    availability: 'available',
    reasonCode: null,
    value: {
      total: Number(value.total),
      idle: Number(value.idle),
      queued: Number(value.queued),
      running: Number(value.running),
      attention: Number(value.attention),
      completed: Number(value.completed),
      failed: Number(value.failed),
      cancelled: Number(value.cancelled),
    },
  };
}

function parseRecentKnowledge(input: unknown): LocalRecentKnowledgeField | null {
  if (
    !isExactRecord(input, RECENT_FIELD_KEYS) ||
    input.availability !== 'degraded' ||
    input.reason_code !== PROJECT_OVERVIEW_REASON ||
    input.source !== TIMELINE_SOURCE ||
    !isSafeNonnegativeInteger(input.total) ||
    !Array.isArray(input.value) ||
    input.value.length > RECENT_ITEM_LIMIT ||
    input.total < input.value.length
  ) {
    return null;
  }
  const items: LocalProjectOverviewKnowledgeItem[] = [];
  const ids = new Set<string>();
  for (const item of input.value) {
    const parsed = parseKnowledgeItem(item);
    if (!parsed || ids.has(parsed.id)) return null;
    ids.add(parsed.id);
    items.push(parsed);
  }
  return {
    availability: 'degraded',
    reasonCode: PROJECT_OVERVIEW_REASON,
    source: TIMELINE_SOURCE,
    total: input.total,
    value: items,
  };
}

function parseKnowledgeItem(input: unknown): LocalProjectOverviewKnowledgeItem | null {
  if (
    !isExactRecord(input, KNOWLEDGE_ITEM_KEYS) ||
    !isExactIdentifier(input.id) ||
    !isExactIdentifier(input.conversation_id) ||
    !isNonEmptyString(input.title) ||
    !isNonEmptyString(input.content) ||
    !isNonEmptyString(input.result_type) ||
    input.source !== TIMELINE_SOURCE ||
    !isNullableNonEmptyString(input.created_at) ||
    !Array.isArray(input.tags) ||
    !input.tags.every(isNonEmptyString)
  ) {
    return null;
  }
  return {
    id: input.id,
    conversationId: input.conversation_id,
    title: input.title,
    content: input.content,
    resultType: input.result_type,
    source: TIMELINE_SOURCE,
    createdAt: input.created_at,
    tags: [...input.tags],
  };
}

function parseNullField<
  Availability extends 'unavailable' | 'not_applicable',
  Reason extends
    | typeof PROJECT_GRAPH_REASON
    | typeof PROJECT_STORAGE_REASON
    | typeof PROJECT_COLLABORATION_REASON,
>(
  input: unknown,
  availability: Availability,
  reasonCode: Reason,
): Readonly<{
  availability: Availability;
  reasonCode: Reason;
  value: null;
}> | null {
  if (
    !isExactRecord(input, FIELD_KEYS) ||
    input.availability !== availability ||
    input.reason_code !== reasonCode ||
    input.value !== null
  ) {
    return null;
  }
  return { availability, reasonCode, value: null };
}

function isLocalScope(input: unknown): input is LocalProjectOverviewScope {
  return (
    isExactRecord(input, LOCAL_SCOPE_KEYS) &&
    input.authority === 'local' &&
    isExactIdentifier(input.tenantId) &&
    isExactIdentifier(input.projectId)
  );
}

function isViewOnlyActions(input: unknown): input is ['view'] {
  return Array.isArray(input) && input.length === 1 && input[0] === 'view';
}

function isBackfillCursor(input: unknown): input is string | null {
  if (input === null) return true;
  if (typeof input !== 'string' || !input.startsWith('timeline_rowid:')) return false;
  const rowId = input.slice('timeline_rowid:'.length);
  if (!rowId || ![...rowId].every((character) => character >= '0' && character <= '9')) {
    return false;
  }
  return isSafeNonnegativeInteger(Number(rowId));
}

function parseJson(input: string): unknown {
  if (!input) return null;
  try {
    return JSON.parse(input) as unknown;
  } catch {
    return null;
  }
}

function parseContentLength(input: string | null): number | null {
  if (input === null) return null;
  const value = Number(input);
  return isSafeNonnegativeInteger(value) ? value : null;
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  return `HTTP ${status}`;
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}

function isExactRecord(
  input: unknown,
  expectedKeys: readonly string[],
): input is Record<string, unknown> {
  if (!isRecord(input)) return false;
  const actualKeys = Object.keys(input);
  return (
    actualKeys.length === expectedKeys.length &&
    expectedKeys.every((key) => Object.hasOwn(input, key))
  );
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}

function isExactIdentifier(input: unknown): input is string {
  return (
    typeof input === 'string' &&
    input.length > 0 &&
    input.length <= 512 &&
    input === input.trim()
  );
}

function isNonEmptyString(input: unknown): input is string {
  return typeof input === 'string' && input.trim().length > 0;
}

function isNullableString(input: unknown): input is string | null {
  return input === null || typeof input === 'string';
}

function isNullableNonEmptyString(input: unknown): input is string | null {
  return input === null || isNonEmptyString(input);
}

function isSafeNonnegativeInteger(input: unknown): input is number {
  return Number.isSafeInteger(input) && Number(input) >= 0;
}

function isServiceVersion(input: unknown): input is string {
  return (
    typeof input === 'string' &&
    input.length <= 63 &&
    /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/u.test(input)
  );
}

const TOP_LEVEL_KEYS = [
  'capability',
  'availability',
  'reason_code',
  'service_version',
  'contract_version',
  'allowed_actions',
  'scope',
  'authority_revision',
  'backfill_cursor',
  'project',
  'conversation_count',
  'conversation_status_summary',
  'recent_knowledge_items',
  'active_nodes',
  'storage_quota',
  'collaborators',
] as const;
const CONVERSATION_STATUS_BUCKET_KEYS = [
  'idle',
  'queued',
  'running',
  'attention',
  'completed',
  'failed',
  'cancelled',
] as const;
const CONVERSATION_STATUS_KEYS = ['total', ...CONVERSATION_STATUS_BUCKET_KEYS] as const;
const CAPABILITY_SCOPE_KEYS = [
  'tenant_id',
  'project_id',
  'workspace_id',
  'instance_id',
] as const;
const FIELD_KEYS = ['availability', 'reason_code', 'value'] as const;
const RECENT_FIELD_KEYS = [
  'availability',
  'reason_code',
  'source',
  'total',
  'value',
] as const;
const PROJECT_KEYS = [
  'id',
  'tenant_id',
  'name',
  'description',
  'agent_conversation_mode',
  'created_at',
] as const;
const KNOWLEDGE_ITEM_KEYS = [
  'id',
  'conversation_id',
  'title',
  'content',
  'result_type',
  'source',
  'created_at',
  'tags',
] as const;
const LOCAL_SCOPE_KEYS = ['authority', 'tenantId', 'projectId'] as const;
