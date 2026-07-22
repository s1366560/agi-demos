import type { AgentTimelineItem } from '../../types';

export type SessionExecutionInsightStage = 'routing' | 'selection' | 'policy' | 'toolset';

export type SessionExecutionSelectionStage = {
  name: string;
  beforeCount: number;
  afterCount: number;
  removedCount: number;
  durationMs: number;
  explanation: Record<string, unknown> | null;
};

export type SessionExecutionInsightEntry = {
  id: string;
  stage: SessionExecutionInsightStage;
  traceId: string | null;
  routeId: string | null;
  domainLane: string | null;
  eventTimeUs: number;
  routing: {
    path: string;
    confidence: number;
    reason: string;
    target: string | null;
  } | null;
  selection: {
    initialCount: number;
    finalCount: number;
    removedTotal: number;
    toolBudget: number | null;
    budgetExceededStages: string[];
    stages: SessionExecutionSelectionStage[];
  } | null;
  policy: {
    removedTotal: number;
    stageCount: number;
    toolBudget: number | null;
    budgetExceededStages: string[];
  } | null;
  toolset: {
    updateKind: 'toolset_changed' | 'tools_updated';
    projectId: string | null;
    source: string | null;
    action: string | null;
    pluginName: string | null;
    refreshStatus: string | null;
    refreshedToolCount: number | null;
    mutationFingerprint: string | null;
    serverName: string | null;
    toolNames: string[];
    requiresRefresh: boolean | null;
  } | null;
};

export type SessionExecutionInsightTrace = {
  groupKey: string;
  traceId: string | null;
  routeId: string | null;
  domainLane: string | null;
  entries: SessionExecutionInsightEntry[];
  startedAtUs: number;
  updatedAtUs: number;
};

export type SessionExecutionInsightsModel = {
  traces: SessionExecutionInsightTrace[];
  activeTrace: SessionExecutionInsightTrace | null;
  summary: {
    traces: number;
    entries: number;
    routing: number;
    selection: number;
    policy: number;
    toolset: number;
    warnings: number;
  };
};

type MutableTrace = Omit<SessionExecutionInsightTrace, 'entries'> & {
  entries: SessionExecutionInsightEntry[];
};

const insightEventTypes = new Set([
  'execution_path_decided',
  'selection_trace',
  'policy_filtered',
  'toolset_changed',
  'tools_updated',
]);

const toolsetRefreshStatuses = new Set([
  'success',
  'failed',
  'skipped',
  'deferred',
  'not_applicable',
]);

export function isSessionExecutionInsightEvent(value: unknown): boolean {
  const root = recordValue(value);
  const type = stringValue(root?.type ?? root?.event_type);
  return Boolean(type && insightEventTypes.has(type));
}

export function buildSessionExecutionInsights(
  items: readonly AgentTimelineItem[],
): SessionExecutionInsightsModel {
  const traces = new Map<string, MutableTrace>();
  const seenEventIds = new Set<string>();

  for (const item of [...items].sort(compareTimelineItems)) {
    if (!isSessionExecutionInsightEvent(item) || seenEventIds.has(item.id)) continue;
    seenEventIds.add(item.id);
    const entry = readInsightEntry(item);
    if (!entry) continue;
    const groupKey = entry.traceId
      ? `trace:${entry.traceId}`
      : entry.routeId
        ? `route:${entry.routeId}`
        : entry.toolset?.projectId && entry.toolset.serverName
          ? [
              'tool-registry',
              encodeURIComponent(entry.toolset.projectId),
              encodeURIComponent(entry.toolset.serverName),
            ].join(':')
          : `event:${entry.id}`;
    const existing = traces.get(groupKey);
    if (existing) {
      existing.entries.push(entry);
      existing.traceId ||= entry.traceId;
      existing.routeId ||= entry.routeId;
      existing.domainLane ||= entry.domainLane;
      existing.updatedAtUs = entry.eventTimeUs;
      continue;
    }
    traces.set(groupKey, {
      groupKey,
      traceId: entry.traceId,
      routeId: entry.routeId,
      domainLane: entry.domainLane,
      entries: [entry],
      startedAtUs: entry.eventTimeUs,
      updatedAtUs: entry.eventTimeUs,
    });
  }

  const frozenTraces = [...traces.values()].sort(
    (left, right) =>
      right.updatedAtUs - left.updatedAtUs || left.groupKey.localeCompare(right.groupKey),
  );
  const activeTrace = frozenTraces[0] ?? null;
  const entries = activeTrace?.entries ?? [];
  const countStage = (stage: SessionExecutionInsightStage) =>
    entries.reduce((count, entry) => count + Number(entry.stage === stage), 0);

  return {
    traces: frozenTraces,
    activeTrace,
    summary: {
      traces: frozenTraces.length,
      entries: entries.length,
      routing: countStage('routing'),
      selection: countStage('selection'),
      policy: countStage('policy'),
      toolset: countStage('toolset'),
      warnings: entries.reduce((count, entry) => count + Number(entryHasWarning(entry)), 0),
    },
  };
}

function readInsightEntry(item: AgentTimelineItem): SessionExecutionInsightEntry | null {
  const type = eventType(item);
  const traceId = fieldString(item, 'trace_id', 'traceId');
  const routeId = fieldString(item, 'route_id', 'routeId');
  const domainLane = readDomainLane(item);
  const base = {
    id: item.id,
    traceId,
    routeId,
    domainLane,
    eventTimeUs: timelineTimeUs(item),
  };

  if (type === 'execution_path_decided') {
    const path = fieldString(item, 'path');
    const confidence = fieldNonNegativeNumber(item, 'confidence');
    const reason = fieldString(item, 'reason');
    if (!path || confidence === null || confidence > 1 || !reason) return null;
    return {
      ...base,
      stage: 'routing',
      routing: {
        path,
        confidence,
        reason,
        target: fieldString(item, 'target'),
      },
      selection: null,
      policy: null,
      toolset: null,
    };
  }

  if (type === 'selection_trace') {
    const initialCount = fieldNonNegativeNumber(item, 'initial_count', 'initialCount');
    const finalCount = fieldNonNegativeNumber(item, 'final_count', 'finalCount');
    const removedTotal = fieldNonNegativeNumber(item, 'removed_total', 'removedTotal');
    const stages = readSelectionStages(item);
    if (initialCount === null || finalCount === null || removedTotal === null || !stages) return null;
    return {
      ...base,
      stage: 'selection',
      routing: null,
      selection: {
        initialCount,
        finalCount,
        removedTotal,
        toolBudget: fieldNonNegativeNumber(item, 'tool_budget', 'toolBudget'),
        budgetExceededStages:
          fieldStringList(item, 'budget_exceeded_stages', 'budgetExceededStages') ?? [],
        stages,
      },
      policy: null,
      toolset: null,
    };
  }

  if (type === 'policy_filtered') {
    const removedTotal = fieldNonNegativeNumber(item, 'removed_total', 'removedTotal');
    const stageCount = fieldNonNegativeNumber(item, 'stage_count', 'stageCount');
    if (removedTotal === null || stageCount === null) return null;
    return {
      ...base,
      stage: 'policy',
      routing: null,
      selection: null,
      policy: {
        removedTotal,
        stageCount,
        toolBudget: fieldNonNegativeNumber(item, 'tool_budget', 'toolBudget'),
        budgetExceededStages:
          fieldStringList(item, 'budget_exceeded_stages', 'budgetExceededStages') ?? [],
      },
      toolset: null,
    };
  }

  if (type === 'tools_updated') {
    const serverName = fieldString(item, 'server_name', 'serverName');
    const toolNames = fieldStringList(item, 'tool_names', 'toolNames');
    const requiresRefresh = fieldBoolean(item, 'requires_refresh', 'requiresRefresh');
    if (!serverName || !toolNames || requiresRefresh === null) return null;
    return {
      ...base,
      stage: 'toolset',
      routing: null,
      selection: null,
      policy: null,
      toolset: {
        updateKind: 'tools_updated',
        projectId: fieldString(item, 'project_id', 'projectId'),
        source: null,
        action: null,
        pluginName: null,
        refreshStatus: null,
        refreshedToolCount: null,
        mutationFingerprint: null,
        serverName,
        toolNames,
        requiresRefresh,
      },
    };
  }

  const source = fieldString(item, 'source');
  const refreshStatus = fieldString(item, 'refresh_status', 'refreshStatus');
  if (!source || (refreshStatus && !toolsetRefreshStatuses.has(refreshStatus))) return null;
  return {
    ...base,
    stage: 'toolset',
    routing: null,
    selection: null,
    policy: null,
    toolset: {
      updateKind: 'toolset_changed',
      projectId: fieldString(item, 'project_id', 'projectId'),
      source,
      action: fieldString(item, 'action'),
      pluginName: fieldString(item, 'plugin_name', 'pluginName'),
      refreshStatus,
      refreshedToolCount: fieldNonNegativeNumber(
        item,
        'refreshed_tool_count',
        'refreshedToolCount',
      ),
      mutationFingerprint: fieldString(
        item,
        'mutation_fingerprint',
        'mutationFingerprint',
      ),
      serverName: fieldString(item, 'server_name', 'serverName'),
      toolNames: fieldStringList(item, 'tool_names', 'toolNames') ?? [],
      requiresRefresh: null,
    },
  };
}

function readSelectionStages(item: AgentTimelineItem): SessionExecutionSelectionStage[] | null {
  const source = fieldValue(item, 'stages');
  if (!Array.isArray(source)) return null;
  const stages: SessionExecutionSelectionStage[] = [];
  for (const value of source) {
    const stage = recordValue(value);
    const name = stringValue(stage?.stage);
    const beforeCount = nonNegativeNumberValue(stage?.before_count ?? stage?.beforeCount);
    const afterCount = nonNegativeNumberValue(stage?.after_count ?? stage?.afterCount);
    const removedCount = nonNegativeNumberValue(stage?.removed_count ?? stage?.removedCount);
    const durationMs = nonNegativeNumberValue(stage?.duration_ms ?? stage?.durationMs);
    if (
      !name ||
      beforeCount === null ||
      afterCount === null ||
      removedCount === null ||
      durationMs === null
    ) {
      return null;
    }
    stages.push({
      name,
      beforeCount,
      afterCount,
      removedCount,
      durationMs,
      explanation: recordValue(stage?.explain) ?? null,
    });
  }
  return stages;
}

function readDomainLane(item: AgentTimelineItem): string | null {
  const explicit = fieldString(item, 'domain_lane', 'domainLane');
  if (explicit) return explicit;
  const metadata = recordValue(fieldValue(item, 'metadata'));
  return stringValue(metadata?.domain_lane ?? metadata?.domainLane);
}

function entryHasWarning(entry: SessionExecutionInsightEntry): boolean {
  if (entry.selection?.budgetExceededStages.length) return true;
  if (entry.policy?.budgetExceededStages.length) return true;
  return entry.toolset?.refreshStatus === 'failed';
}

function eventType(item: AgentTimelineItem): string {
  return stringValue(item.type) ?? '';
}

function fieldValue(item: AgentTimelineItem, ...keys: string[]): unknown {
  const itemRecord = item as unknown as Record<string, unknown>;
  const payload = recordValue(itemRecord.payload) ?? recordValue(itemRecord.data);
  for (const key of keys) {
    if (payload && key in payload) return payload[key];
    if (key in itemRecord) return itemRecord[key];
  }
  return undefined;
}

function fieldString(item: AgentTimelineItem, ...keys: string[]): string | null {
  return stringValue(fieldValue(item, ...keys));
}

function fieldNonNegativeNumber(item: AgentTimelineItem, ...keys: string[]): number | null {
  return nonNegativeNumberValue(fieldValue(item, ...keys));
}

function fieldBoolean(item: AgentTimelineItem, ...keys: string[]): boolean | null {
  const value = fieldValue(item, ...keys);
  return typeof value === 'boolean' ? value : null;
}

function fieldStringList(item: AgentTimelineItem, ...keys: string[]): string[] | null {
  const value = fieldValue(item, ...keys);
  if (!Array.isArray(value)) return null;
  const result = value.map(stringValue);
  return result.every((candidate): candidate is string => candidate !== null) ? result : null;
}

function timelineTimeUs(item: AgentTimelineItem): number {
  const record = item as unknown as Record<string, unknown>;
  return (
    numberValue(record.eventTimeUs ?? record.event_time_us) ??
    (numberValue(item.timestamp) ?? 0) * 1000
  );
}

function compareTimelineItems(left: AgentTimelineItem, right: AgentTimelineItem): number {
  const timeDifference = timelineTimeUs(left) - timelineTimeUs(right);
  if (timeDifference) return timeDifference;
  const leftRecord = left as unknown as Record<string, unknown>;
  const rightRecord = right as unknown as Record<string, unknown>;
  const counterDifference =
    (numberValue(leftRecord.eventCounter ?? leftRecord.event_counter) ?? 0) -
    (numberValue(rightRecord.eventCounter ?? rightRecord.event_counter) ?? 0);
  return counterDifference || left.id.localeCompare(right.id);
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function nonNegativeNumberValue(value: unknown): number | null {
  const number = numberValue(value);
  return number !== null && number >= 0 ? number : null;
}
