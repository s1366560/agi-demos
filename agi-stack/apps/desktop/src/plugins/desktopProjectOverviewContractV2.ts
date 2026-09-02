import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  CloudProjectOverviewMemory,
  CloudProjectOverviewProject,
  CloudProjectOverviewSnapshot,
  CloudProjectOverviewStats,
  ProjectOverviewReadResult,
  ProjectOverviewScope,
} from '../features/project/projectOverviewClient';
import type {
  LocalConversationStatusSummary,
  LocalProjectOverviewCapability,
  LocalProjectOverviewKnowledgeItem,
  LocalProjectOverviewProject,
  LocalProjectOverviewSnapshot,
} from '../features/project/projectOverviewLocalClient';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';

const RESULT_KEYS_V2 = new Set(['kind', 'snapshot']);
const EMPTY_RESULT_KEYS_V2 = new Set(['kind']);
const CLOUD_SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'project',
  'stats',
  'latestMemories',
  'latestMemoriesTotal',
]);
const CLOUD_PROJECT_KEYS_V2 = new Set([
  'id',
  'tenant_id',
  'name',
  'description',
  'created_at',
  'updated_at',
]);
const CLOUD_STATS_KEYS_V2 = new Set([
  'memory_count',
  'storage_used',
  'storage_limit',
  'active_nodes',
  'collaborators',
]);
const CLOUD_MEMORY_KEYS_V2 = new Set([
  'id',
  'project_id',
  'title',
  'content',
  'content_type',
  'status',
  'metadata',
  'created_at',
  'updated_at',
]);
const LOCAL_SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'capability',
  'backfillCursor',
  'project',
  'conversationCount',
  'conversationStatusSummary',
  'recentKnowledgeItems',
  'activeNodes',
  'storageQuota',
  'collaborators',
]);
const LOCAL_CAPABILITY_KEYS_V2 = new Set([
  'availability',
  'reasonCode',
  'serviceVersion',
  'contractVersion',
  'allowedActions',
  'scope',
  'authorityRevision',
]);
const CAPABILITY_SCOPE_KEYS_V2 = new Set(['tenantId', 'projectId', 'workspaceId', 'instanceId']);
const CAPABILITY_KEYS_V2 = new Set([
  'availability',
  'reason_code',
  'service_version',
  'contract_version',
  'allowed_actions',
  'scope',
  'authority_revision',
]);
const PROJECTED_SCOPE_KEYS_V2 = new Set(['tenant_id', 'project_id', 'workspace_id', 'instance_id']);
const FIELD_KEYS_V2 = new Set(['availability', 'reasonCode', 'value']);
const RECENT_FIELD_KEYS_V2 = new Set(['availability', 'reasonCode', 'source', 'total', 'value']);
const LOCAL_PROJECT_KEYS_V2 = new Set([
  'id',
  'tenantId',
  'name',
  'description',
  'agentConversationMode',
  'createdAt',
]);
const STATUS_KEYS_V2 = new Set([
  'total',
  'idle',
  'queued',
  'running',
  'attention',
  'completed',
  'failed',
  'cancelled',
]);
const KNOWLEDGE_KEYS_V2 = new Set([
  'id',
  'conversationId',
  'title',
  'content',
  'resultType',
  'source',
  'createdAt',
  'tags',
]);

export function requireDesktopProjectOverviewResultV2(
  value: unknown,
  expectedScope: ProjectOverviewScope
): ProjectOverviewReadResult {
  if (!isPlainRecordV2(value)) throw contractErrorV2();
  if (value.kind === 'empty') {
    if (expectedScope.authority !== 'cloud' || !hasExactKeysV2(value, EMPTY_RESULT_KEYS_V2)) {
      throw contractErrorV2();
    }
    return Object.freeze({ kind: 'empty' });
  }
  if (!hasExactKeysV2(value, RESULT_KEYS_V2)) throw contractErrorV2();
  if (value.kind === 'cloud-ready' && expectedScope.authority === 'cloud') {
    return Object.freeze({
      kind: 'cloud-ready',
      snapshot: requireCloudSnapshotV2(value.snapshot, expectedScope),
    });
  }
  if (value.kind === 'local-ready' && expectedScope.authority === 'local') {
    return Object.freeze({
      kind: 'local-ready',
      snapshot: requireLocalSnapshotV2(value.snapshot, expectedScope),
    });
  }
  throw contractErrorV2();
}

export function requireDesktopProjectOverviewCapabilityV2(
  value: unknown,
  expectedScope: ProjectOverviewScope
): DesktopCapabilityAvailability {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, CAPABILITY_KEYS_V2) ||
    !isAvailabilityV2(value.availability) ||
    !isNullableCanonicalStringV2(value.reason_code) ||
    !isCanonicalStringV2(value.service_version) ||
    !isCanonicalStringV2(value.contract_version) ||
    !isOrderedActionsV2(value.allowed_actions) ||
    !isNullableNonnegativeIntegerV2(value.authority_revision) ||
    !isProjectedCapabilityScopeV2(value.scope, expectedScope)
  ) {
    throw contractErrorV2();
  }
  if (
    value.availability === 'unavailable' &&
    (value.allowed_actions.length !== 0 || value.authority_revision !== null)
  ) {
    throw contractErrorV2();
  }
  if (
    expectedScope.authority === 'cloud' &&
    (value.availability !== 'unavailable' ||
      value.reason_code !== 'capability_authority_revision_unavailable' ||
      value.allowed_actions.length !== 0 ||
      value.authority_revision !== null)
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    availability: value.availability,
    reason_code: value.reason_code,
    service_version: value.service_version,
    contract_version: value.contract_version,
    allowed_actions: Object.freeze([...value.allowed_actions]),
    scope: Object.freeze({
      tenant_id: expectedScope.tenantId,
      project_id: expectedScope.projectId,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: value.authority_revision,
  });
}

function requireCloudSnapshotV2(
  value: unknown,
  expectedScope: Extract<ProjectOverviewScope, { authority: 'cloud' }>
): CloudProjectOverviewSnapshot {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, CLOUD_SNAPSHOT_KEYS_V2) ||
    !isProjectOverviewScopeV2(value.scope, expectedScope) ||
    !Array.isArray(value.latestMemories) ||
    value.latestMemories.length > 5 ||
    !isNonnegativeIntegerV2(value.latestMemoriesTotal) ||
    value.latestMemoriesTotal < value.latestMemories.length
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    scope: Object.freeze({ ...expectedScope }),
    project: requireCloudProjectV2(value.project, expectedScope),
    stats: requireCloudStatsV2(value.stats),
    latestMemories: Object.freeze(
      value.latestMemories.map((memory) => requireCloudMemoryV2(memory, expectedScope))
    ),
    latestMemoriesTotal: value.latestMemoriesTotal,
  });
}

function requireCloudProjectV2(
  value: unknown,
  expectedScope: Extract<ProjectOverviewScope, { authority: 'cloud' }>
): CloudProjectOverviewProject {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, CLOUD_PROJECT_KEYS_V2) ||
    value.id !== expectedScope.projectId ||
    value.tenant_id !== expectedScope.tenantId ||
    !isCanonicalStringV2(value.name) ||
    !isNullableStringV2(value.description) ||
    !isNullableStringV2(value.created_at) ||
    !isNullableStringV2(value.updated_at)
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    id: value.id,
    tenant_id: value.tenant_id,
    name: value.name,
    description: value.description,
    created_at: value.created_at,
    updated_at: value.updated_at,
  });
}

function requireCloudStatsV2(value: unknown): CloudProjectOverviewStats {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, CLOUD_STATS_KEYS_V2) ||
    [...CLOUD_STATS_KEYS_V2].some((key) => !isFiniteNonnegativeV2(value[key]))
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    memory_count: Number(value.memory_count),
    storage_used: Number(value.storage_used),
    storage_limit: Number(value.storage_limit),
    active_nodes: Number(value.active_nodes),
    collaborators: Number(value.collaborators),
  });
}

function requireCloudMemoryV2(
  value: unknown,
  expectedScope: Extract<ProjectOverviewScope, { authority: 'cloud' }>
): CloudProjectOverviewMemory {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, CLOUD_MEMORY_KEYS_V2) ||
    !isCanonicalStringV2(value.id) ||
    value.project_id !== expectedScope.projectId ||
    !isCanonicalStringV2(value.title) ||
    typeof value.content !== 'string' ||
    !isCanonicalStringV2(value.content_type) ||
    !isCanonicalStringV2(value.status) ||
    !isPlainRecordV2(value.metadata) ||
    !isCanonicalStringV2(value.created_at) ||
    !isNullableStringV2(value.updated_at)
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    id: value.id,
    project_id: value.project_id,
    title: value.title,
    content: value.content,
    content_type: value.content_type,
    status: value.status,
    metadata: Object.freeze({ ...value.metadata }),
    created_at: value.created_at,
    updated_at: value.updated_at,
  });
}

function requireLocalSnapshotV2(
  value: unknown,
  expectedScope: Extract<ProjectOverviewScope, { authority: 'local' }>
): LocalProjectOverviewSnapshot {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, LOCAL_SNAPSHOT_KEYS_V2) ||
    !isProjectOverviewScopeV2(value.scope, expectedScope) ||
    !isNullableStringV2(value.backfillCursor)
  ) {
    throw contractErrorV2();
  }
  const capability = requireLocalCapabilityV2(value.capability, expectedScope);
  const project = requireAvailableLocalProjectV2(value.project, expectedScope);
  const conversationCount = requireAvailableCountV2(value.conversationCount);
  const conversationStatusSummary = requireStatusSummaryFieldV2(value.conversationStatusSummary);
  const recentKnowledgeItems = requireRecentKnowledgeV2(value.recentKnowledgeItems);
  if (conversationStatusSummary.value.total !== conversationCount.value) {
    throw contractErrorV2();
  }
  return Object.freeze({
    scope: Object.freeze({ ...expectedScope }),
    capability,
    backfillCursor: value.backfillCursor,
    project,
    conversationCount,
    conversationStatusSummary,
    recentKnowledgeItems,
    activeNodes: requireNullFieldV2(
      value.activeNodes,
      'unavailable',
      'local_project_graph_projection_unavailable'
    ),
    storageQuota: requireNullFieldV2(
      value.storageQuota,
      'not_applicable',
      'local_project_storage_quota_not_applicable'
    ),
    collaborators: requireNullFieldV2(
      value.collaborators,
      'not_applicable',
      'local_project_collaboration_governance_not_applicable'
    ),
  });
}

function requireLocalCapabilityV2(
  value: unknown,
  expectedScope: Extract<ProjectOverviewScope, { authority: 'local' }>
): LocalProjectOverviewCapability {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, LOCAL_CAPABILITY_KEYS_V2) ||
    value.availability !== 'degraded' ||
    value.reasonCode !== 'local_project_overview_timeline_projection_only' ||
    !isCanonicalStringV2(value.serviceVersion) ||
    value.contractVersion !== '4.0.0' ||
    !isViewOnlyActionsV2(value.allowedActions) ||
    !isNonnegativeIntegerV2(value.authorityRevision) ||
    !isPlainRecordV2(value.scope) ||
    !hasExactKeysV2(value.scope, CAPABILITY_SCOPE_KEYS_V2) ||
    value.scope.tenantId !== expectedScope.tenantId ||
    value.scope.projectId !== expectedScope.projectId ||
    value.scope.workspaceId !== null ||
    value.scope.instanceId !== null
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    availability: 'degraded',
    reasonCode: 'local_project_overview_timeline_projection_only',
    serviceVersion: value.serviceVersion,
    contractVersion: '4.0.0',
    allowedActions: Object.freeze(['view'] as const),
    scope: Object.freeze({
      tenantId: expectedScope.tenantId,
      projectId: expectedScope.projectId,
      workspaceId: null,
      instanceId: null,
    }),
    authorityRevision: value.authorityRevision,
  });
}

function requireAvailableLocalProjectV2(
  value: unknown,
  expectedScope: Extract<ProjectOverviewScope, { authority: 'local' }>
): LocalProjectOverviewSnapshot['project'] {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, FIELD_KEYS_V2) ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    !isPlainRecordV2(value.value) ||
    !hasExactKeysV2(value.value, LOCAL_PROJECT_KEYS_V2)
  ) {
    throw contractErrorV2();
  }
  const project = value.value;
  if (
    project.id !== expectedScope.projectId ||
    project.tenantId !== expectedScope.tenantId ||
    !isCanonicalStringV2(project.name) ||
    !isNullableStringV2(project.description) ||
    !isCanonicalStringV2(project.agentConversationMode) ||
    !isCanonicalStringV2(project.createdAt)
  ) {
    throw contractErrorV2();
  }
  const projected: LocalProjectOverviewProject = Object.freeze({
    id: project.id,
    tenantId: project.tenantId,
    name: project.name,
    description: project.description,
    agentConversationMode: project.agentConversationMode,
    createdAt: project.createdAt,
  });
  return Object.freeze({
    availability: 'available',
    reasonCode: null,
    value: projected,
  });
}

function requireAvailableCountV2(
  value: unknown
): LocalProjectOverviewSnapshot['conversationCount'] {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, FIELD_KEYS_V2) ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    !isNonnegativeIntegerV2(value.value)
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    availability: 'available',
    reasonCode: null,
    value: value.value,
  });
}

function requireStatusSummaryFieldV2(
  value: unknown
): LocalProjectOverviewSnapshot['conversationStatusSummary'] {
  const status = isPlainRecordV2(value) && isPlainRecordV2(value.value) ? value.value : null;
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, FIELD_KEYS_V2) ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    status === null ||
    !hasExactKeysV2(status, STATUS_KEYS_V2) ||
    [...STATUS_KEYS_V2].some((key) => !isNonnegativeIntegerV2(status[key]))
  ) {
    throw contractErrorV2();
  }
  const source = status;
  const partition =
    Number(source.idle) +
    Number(source.queued) +
    Number(source.running) +
    Number(source.attention) +
    Number(source.completed) +
    Number(source.failed) +
    Number(source.cancelled);
  if (partition !== Number(source.total)) throw contractErrorV2();
  const summary: LocalConversationStatusSummary = Object.freeze({
    total: Number(source.total),
    idle: Number(source.idle),
    queued: Number(source.queued),
    running: Number(source.running),
    attention: Number(source.attention),
    completed: Number(source.completed),
    failed: Number(source.failed),
    cancelled: Number(source.cancelled),
  });
  return Object.freeze({
    availability: 'available',
    reasonCode: null,
    value: summary,
  });
}

function requireRecentKnowledgeV2(
  value: unknown
): LocalProjectOverviewSnapshot['recentKnowledgeItems'] {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, RECENT_FIELD_KEYS_V2) ||
    value.availability !== 'degraded' ||
    value.reasonCode !== 'local_project_overview_timeline_projection_only' ||
    value.source !== 'desktop_timeline' ||
    !isNonnegativeIntegerV2(value.total) ||
    !Array.isArray(value.value) ||
    value.value.length > 5 ||
    value.total < value.value.length
  ) {
    throw contractErrorV2();
  }
  const ids = new Set<string>();
  const items = value.value.map((item) => {
    const projected = requireKnowledgeItemV2(item);
    if (ids.has(projected.id)) throw contractErrorV2();
    ids.add(projected.id);
    return projected;
  });
  return Object.freeze({
    availability: 'degraded',
    reasonCode: 'local_project_overview_timeline_projection_only',
    source: 'desktop_timeline',
    total: value.total,
    value: Object.freeze(items),
  });
}

function requireKnowledgeItemV2(value: unknown): LocalProjectOverviewKnowledgeItem {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, KNOWLEDGE_KEYS_V2) ||
    !isCanonicalStringV2(value.id) ||
    !isCanonicalStringV2(value.conversationId) ||
    !isCanonicalStringV2(value.title) ||
    !isCanonicalStringV2(value.content) ||
    !isCanonicalStringV2(value.resultType) ||
    value.source !== 'desktop_timeline' ||
    !isNullableCanonicalStringV2(value.createdAt) ||
    !isCanonicalStringArrayV2(value.tags)
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({
    id: value.id,
    conversationId: value.conversationId,
    title: value.title,
    content: value.content,
    resultType: value.resultType,
    source: 'desktop_timeline',
    createdAt: value.createdAt,
    tags: Object.freeze([...value.tags]),
  });
}

function requireNullFieldV2<
  Availability extends 'unavailable' | 'not_applicable',
  Reason extends
    | 'local_project_graph_projection_unavailable'
    | 'local_project_storage_quota_not_applicable'
    | 'local_project_collaboration_governance_not_applicable',
>(
  value: unknown,
  availability: Availability,
  reasonCode: Reason
): Readonly<{ availability: Availability; reasonCode: Reason; value: null }> {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, FIELD_KEYS_V2) ||
    value.availability !== availability ||
    value.reasonCode !== reasonCode ||
    value.value !== null
  ) {
    throw contractErrorV2();
  }
  return Object.freeze({ availability, reasonCode, value: null });
}

function isProjectOverviewScopeV2(value: unknown, expectedScope: ProjectOverviewScope): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, new Set(['authority', 'tenantId', 'projectId'])) &&
    value.authority === expectedScope.authority &&
    value.tenantId === expectedScope.tenantId &&
    value.projectId === expectedScope.projectId
  );
}

function isProjectedCapabilityScopeV2(
  value: unknown,
  expectedScope: ProjectOverviewScope
): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, PROJECTED_SCOPE_KEYS_V2) &&
    value.tenant_id === expectedScope.tenantId &&
    value.project_id === expectedScope.projectId &&
    value.workspace_id === null &&
    value.instance_id === null
  );
}

function isOrderedActionsV2(value: unknown): value is string[] {
  if (!Array.isArray(value)) return false;
  const order = ['view', 'inspect-stats'];
  let previous = -1;
  for (const action of value) {
    const index = order.indexOf(action);
    if (index <= previous) return false;
    previous = index;
  }
  return true;
}

function isViewOnlyActionsV2(value: unknown): value is ['view'] {
  return Array.isArray(value) && value.length === 1 && value[0] === 'view';
}

function isAvailabilityV2(value: unknown): value is DesktopCapabilityAvailability['availability'] {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}

function contractErrorV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_overview_service_contract_invalid',
    'desktop project overview service result is invalid'
  );
}

function hasExactKeysV2(value: Record<string, unknown>, expected: ReadonlySet<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isNullableStringV2(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableCanonicalStringV2(value: unknown): value is string | null {
  return value === null || isCanonicalStringV2(value);
}

function isCanonicalStringArrayV2(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isCanonicalStringV2);
}

function isFiniteNonnegativeV2(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isNonnegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isNullableNonnegativeIntegerV2(value: unknown): value is number | null {
  return value === null || isNonnegativeIntegerV2(value);
}
