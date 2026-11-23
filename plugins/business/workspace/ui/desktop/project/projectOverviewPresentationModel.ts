import type { CloudProjectOverviewSnapshot } from './projectOverviewClient';
import type { LocalProjectOverviewSnapshot } from './projectOverviewLocalClient';

export type ProjectOverviewAuthority = 'cloud' | 'local';

export type ProjectOverviewAvailability =
  | 'available'
  | 'degraded'
  | 'unavailable'
  | 'not_applicable';

export type ProjectOverviewPresentationScope = Readonly<{
  authority: ProjectOverviewAuthority;
  tenantId: string;
  projectId: string;
}>;

export type ProjectOverviewPresentationInput =
  | Readonly<{
      kind: 'loading';
      scope: ProjectOverviewPresentationScope;
      scopeSwitch: boolean;
    }>
  | Readonly<{ kind: 'cloud-ready'; snapshot: CloudProjectOverviewSnapshot }>
  | Readonly<{ kind: 'local-ready'; snapshot: LocalProjectOverviewSnapshot }>
  | Readonly<{ kind: 'empty'; scope: ProjectOverviewPresentationScope }>
  | Readonly<{
      kind: 'error';
      scope: ProjectOverviewPresentationScope;
      reasonCode: string;
      detail: string | null;
      retryable: boolean;
    }>
  | Readonly<{
      kind: 'forbidden';
      scope: ProjectOverviewPresentationScope;
      reasonCode: string;
    }>
  | Readonly<{
      kind: 'unavailable';
      scope: ProjectOverviewPresentationScope;
      reasonCode: string;
      retryable: boolean;
    }>;

export type ProjectOverviewPresentationState =
  | 'loading'
  | 'scope_switch'
  | 'ready'
  | 'degraded'
  | 'empty'
  | 'error'
  | 'forbidden'
  | 'unavailable';

export type ProjectOverviewProjectPresentation = Readonly<{
  name: string;
  description: string | null;
  createdAt: string | null;
}>;

export type ProjectOverviewSummaryField = Readonly<{
  id:
    | 'memory_count'
    | 'storage'
    | 'active_nodes'
    | 'collaborators'
    | 'conversation_count'
    | 'storage_quota';
  labelKey: string;
  availability: ProjectOverviewAvailability;
  reasonCode: string | null;
  value: number | null;
  secondaryValue: number | null;
  valueKind: 'count' | 'bytes_pair';
}>;

export type ProjectOverviewRecentItem = Readonly<{
  id: string;
  title: string;
  content: string;
  createdAt: string | null;
  status: string | null;
  source: string | null;
  tags: readonly string[];
}>;

export type ProjectOverviewRecentPresentation = Readonly<{
  kind: 'memories' | 'knowledge_items' | 'none';
  availability: ProjectOverviewAvailability;
  reasonCode: string | null;
  total: number;
  items: readonly ProjectOverviewRecentItem[];
}>;

export type ProjectOverviewPresentationModel = Readonly<{
  state: ProjectOverviewPresentationState;
  authority: ProjectOverviewAuthority;
  scope: ProjectOverviewPresentationScope;
  reasonCode: string | null;
  detail: string | null;
  project: ProjectOverviewProjectPresentation | null;
  summaryFields: readonly ProjectOverviewSummaryField[];
  recent: ProjectOverviewRecentPresentation;
  retryVisible: boolean;
}>;

export function buildProjectOverviewPresentation(
  input: ProjectOverviewPresentationInput,
): ProjectOverviewPresentationModel {
  switch (input.kind) {
    case 'loading':
      return terminalModel({
        state: input.scopeSwitch ? 'scope_switch' : 'loading',
        scope: input.scope,
      });
    case 'empty':
      return terminalModel({
        state: 'empty',
        scope: input.scope,
        retryVisible: true,
      });
    case 'error':
      return terminalModel({
        state: 'error',
        scope: input.scope,
        reasonCode: input.reasonCode,
        detail: input.detail,
        retryVisible: input.retryable,
      });
    case 'forbidden':
      return terminalModel({
        state: 'forbidden',
        scope: input.scope,
        reasonCode: input.reasonCode,
      });
    case 'unavailable':
      return terminalModel({
        state: 'unavailable',
        scope: input.scope,
        reasonCode: input.reasonCode,
        retryVisible: input.retryable,
      });
    case 'cloud-ready':
      return cloudPresentation(input.snapshot);
    case 'local-ready':
      return localPresentation(input.snapshot);
  }
}

function cloudPresentation(
  snapshot: CloudProjectOverviewSnapshot,
): ProjectOverviewPresentationModel {
  const scope: ProjectOverviewPresentationScope = snapshot.scope;
  return {
    state: 'ready',
    authority: 'cloud',
    scope,
    reasonCode: null,
    detail: null,
    project: {
      name: snapshot.project.name,
      description: snapshot.project.description,
      createdAt: snapshot.project.created_at,
    },
    summaryFields: [
      availableCount('memory_count', 'projectOverview.cloud.memoryCount', snapshot.stats.memory_count),
      {
        id: 'storage',
        labelKey: 'projectOverview.cloud.storage',
        availability: 'available',
        reasonCode: null,
        value: snapshot.stats.storage_used,
        secondaryValue: snapshot.stats.storage_limit,
        valueKind: 'bytes_pair',
      },
      availableCount('active_nodes', 'projectOverview.cloud.activeNodes', snapshot.stats.active_nodes),
      availableCount(
        'collaborators',
        'projectOverview.cloud.collaborators',
        snapshot.stats.collaborators,
      ),
    ],
    recent: {
      kind: 'memories',
      availability: 'available',
      reasonCode: null,
      total: snapshot.latestMemoriesTotal,
      items: snapshot.latestMemories.map((memory) => ({
        id: memory.id,
        title: memory.title,
        content: memory.content,
        createdAt: memory.created_at,
        status: memory.status,
        source: null,
        tags: [],
      })),
    },
    retryVisible: false,
  };
}

function localPresentation(
  snapshot: LocalProjectOverviewSnapshot,
): ProjectOverviewPresentationModel {
  const project =
    snapshot.project.availability === 'available' && snapshot.project.value
      ? {
          name: snapshot.project.value.name,
          description: snapshot.project.value.description,
          createdAt: snapshot.project.value.createdAt,
        }
      : null;

  return {
    state: snapshot.capability.availability === 'degraded' ? 'degraded' : 'ready',
    authority: 'local',
    scope: snapshot.scope,
    reasonCode: snapshot.capability.reasonCode,
    detail: null,
    project,
    summaryFields: [
      localCount(
        'conversation_count',
        'projectOverview.local.conversationCount',
        snapshot.conversationCount,
      ),
      localCount('active_nodes', 'projectOverview.local.activeNodes', snapshot.activeNodes),
      localCount('storage_quota', 'projectOverview.local.storageQuota', snapshot.storageQuota),
      localCount('collaborators', 'projectOverview.local.collaborators', snapshot.collaborators),
    ],
    recent: {
      kind: 'knowledge_items',
      availability: snapshot.recentKnowledgeItems.availability,
      reasonCode: snapshot.recentKnowledgeItems.reasonCode,
      total: snapshot.recentKnowledgeItems.total,
      items: snapshot.recentKnowledgeItems.value.map((item) => ({
        id: item.id,
        title: item.title,
        content: item.content,
        createdAt: item.createdAt,
        status: item.resultType,
        source: item.source,
        tags: item.tags,
      })),
    },
    retryVisible: false,
  };
}

function availableCount(
  id: ProjectOverviewSummaryField['id'],
  labelKey: string,
  value: number,
): ProjectOverviewSummaryField {
  return {
    id,
    labelKey,
    availability: 'available',
    reasonCode: null,
    value,
    secondaryValue: null,
    valueKind: 'count',
  };
}

function localCount(
  id: ProjectOverviewSummaryField['id'],
  labelKey: string,
  field: Readonly<{
    availability: ProjectOverviewAvailability;
    reasonCode: string | null;
    value: number | null;
  }>,
): ProjectOverviewSummaryField {
  return {
    id,
    labelKey,
    availability: field.availability,
    reasonCode: field.reasonCode,
    value: field.availability === 'available' ? field.value : null,
    secondaryValue: null,
    valueKind: 'count',
  };
}

function terminalModel({
  state,
  scope,
  reasonCode = null,
  detail = null,
  retryVisible = false,
}: Readonly<{
  state: Exclude<ProjectOverviewPresentationState, 'ready' | 'degraded'>;
  scope: ProjectOverviewPresentationScope;
  reasonCode?: string | null;
  detail?: string | null;
  retryVisible?: boolean;
}>): ProjectOverviewPresentationModel {
  return {
    state,
    authority: scope.authority,
    scope,
    reasonCode,
    detail,
    project: null,
    summaryFields: [],
    recent: {
      kind: 'none',
      availability: 'unavailable',
      reasonCode: null,
      total: 0,
      items: [],
    },
    retryVisible,
  };
}
