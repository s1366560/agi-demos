import type { AgentTimelineItem, DesktopToolInvocation } from '../../types';

export type ToolInvocationStatus =
  | 'prepared'
  | 'executing'
  | 'completed'
  | 'failed'
  | 'unknown_outcome';

export type InvocationIdentitySource = 'event' | 'timeline';
export type InvocationScopeSource = 'event' | 'session' | 'unavailable';

export type SessionInvocationLedgerEntry = {
  id: string;
  invocationId: string;
  invocationIdSource: InvocationIdentitySource;
  toolName: string;
  status: ToolInvocationStatus;
  runId: string | null;
  revision: number | null;
  scopeSource: InvocationScopeSource;
  authorizationId: string | null;
  sourceEventIds: string[];
  updatedAtUs: number;
};

export type SessionInvocationLedgerScope = {
  runId?: string | null;
  revision?: number | null;
};

export type SessionInvocationLedgerSummary = {
  total: number;
  prepared: number;
  executing: number;
  completed: number;
  failed: number;
  unknownOutcome: number;
  blocked: boolean;
};

type ParsedInvocationEvent = {
  item: AgentTimelineItem;
  invocationId: string | null;
  toolName: string;
  status: ToolInvocationStatus;
  runId: string | null;
  revision: number | null;
  authorizationId: string | null;
  inputFingerprint: string | null;
};

type PendingInvocation = {
  key: string;
  toolName: string;
  inputFingerprint: string | null;
};

const invocationStatuses = new Set<ToolInvocationStatus>([
  'prepared',
  'executing',
  'completed',
  'failed',
  'unknown_outcome',
]);

export function buildSessionInvocationLedger(
  items: readonly AgentTimelineItem[],
  scope: SessionInvocationLedgerScope = {},
  authoritativeInvocations: readonly DesktopToolInvocation[] = [],
): SessionInvocationLedgerEntry[] {
  const authoritativeEntries = authoritativeInvocations.map((invocation) => ({
        id: `invocation:${invocation.invocation_id}`,
        invocationId: invocation.invocation_id,
        invocationIdSource: 'event' as const,
        toolName: invocation.tool_name,
        status: invocation.status,
        runId: invocation.run_id,
        revision: invocation.run_revision,
        scopeSource: 'event' as const,
        authorizationId: invocation.grant_id ?? null,
        sourceEventIds: [],
        updatedAtUs:
          (invocation.finished_at_ms ??
            invocation.started_at_ms ??
            invocation.prepared_at_ms) * 1_000,
      }));
  const entries = new Map<string, SessionInvocationLedgerEntry>();
  const pending: PendingInvocation[] = [];
  const orderedItems = [...items].sort(compareTimelineItems);

  for (const item of orderedItems) {
    const parsed = parseInvocationEvent(item);
    if (!parsed) continue;

    const explicitKey = parsed.invocationId ? `invocation:${parsed.invocationId}` : null;
    const pendingIndex = isObservation(item)
      ? matchingPendingIndex(pending, parsed.toolName, parsed.inputFingerprint)
      : -1;
    const pendingKey = pendingIndex >= 0 ? pending[pendingIndex]?.key ?? null : null;
    const key =
      (explicitKey && entries.has(explicitKey) ? explicitKey : null) ??
      pendingKey ??
      explicitKey ??
      `timeline:${item.id}`;
    const existing = entries.get(key);
    const invocationId = parsed.invocationId ?? existing?.invocationId ?? item.id;
    const invocationIdSource: InvocationIdentitySource = parsed.invocationId
      ? 'event'
      : existing?.invocationIdSource ?? 'timeline';
    const explicitRunId = parsed.runId ?? (existing?.scopeSource === 'event' ? existing.runId : null);
    const runId = explicitRunId ?? scope.runId ?? existing?.runId ?? null;
    const scopeSource: InvocationScopeSource = explicitRunId
      ? 'event'
      : runId
        ? 'session'
        : 'unavailable';
    const revision =
      parsed.revision ??
      (existing?.scopeSource === 'event' ? existing.revision : null) ??
      (runId && runId === scope.runId ? scope.revision ?? null : null);

    entries.set(key, {
      id: key,
      invocationId,
      invocationIdSource,
      toolName: parsed.toolName || existing?.toolName || '',
      status: parsed.status,
      runId,
      revision,
      scopeSource,
      authorizationId: parsed.authorizationId ?? existing?.authorizationId ?? null,
      sourceEventIds: existing
        ? appendUnique(existing.sourceEventIds, item.id)
        : [item.id],
      updatedAtUs: item.eventTimeUs,
    });

    if (isTerminalInvocationStatus(parsed.status)) {
      if (pendingIndex >= 0) pending.splice(pendingIndex, 1);
      removePendingKey(pending, key);
    } else if (!pending.some((candidate) => candidate.key === key)) {
      pending.push({ key, toolName: parsed.toolName, inputFingerprint: parsed.inputFingerprint });
    }
  }
  const latestAuthoritativeTime = authoritativeEntries.reduce(
    (latest, entry) => Math.max(latest, entry.updatedAtUs),
    0,
  );
  const inferredEntries = [...entries.values()].filter(
    (entry) => !authoritativeEntries.length || entry.updatedAtUs > latestAuthoritativeTime,
  );
  return [...authoritativeEntries, ...inferredEntries].sort((left, right) => {
    if (left.updatedAtUs !== right.updatedAtUs) return right.updatedAtUs - left.updatedAtUs;
    return right.invocationId.localeCompare(left.invocationId);
  });
}

export function sessionInvocationLedgerSummary(
  entries: readonly SessionInvocationLedgerEntry[],
): SessionInvocationLedgerSummary {
  const summary: SessionInvocationLedgerSummary = {
    total: entries.length,
    prepared: 0,
    executing: 0,
    completed: 0,
    failed: 0,
    unknownOutcome: 0,
    blocked: false,
  };
  for (const entry of entries) {
    if (entry.status === 'unknown_outcome') summary.unknownOutcome += 1;
    else summary[entry.status] += 1;
  }
  summary.blocked = summary.unknownOutcome > 0;
  return summary;
}

function parseInvocationEvent(item: AgentTimelineItem): ParsedInvocationEvent | null {
  const records = invocationRecords(item);
  const invocationRecordsOnly = nestedRecords(records, ['invocation', 'tool_invocation']);
  const runRecords = nestedRecords(records, ['run']);
  const authorizationRecords = nestedRecords(records, ['authorization', 'grant', 'decision']);
  const toolRecords = nestedRecords(records, ['tool']);
  const status = explicitInvocationStatus(item, records, invocationRecordsOnly);
  const structuralStatus = structuralInvocationStatus(item);
  const resolvedStatus = status ?? structuralStatus;
  const toolName =
    item.toolName?.trim() ||
    readString(records, ['tool_name', 'toolName']) ||
    readString(toolRecords, ['name', 'id']) ||
    '';
  const invocationId =
    readString(records, [
      'invocation_id',
      'invocationId',
      'tool_call_id',
      'toolCallId',
      'call_id',
      'callId',
    ]) ||
    readString(invocationRecordsOnly, ['id', 'invocation_id', 'invocationId']) ||
    item.requestId?.trim() ||
    null;

  if (!resolvedStatus || (!toolName && !invocationId)) return null;

  return {
    item,
    invocationId,
    toolName,
    status: resolvedStatus,
    runId:
      readString(records, ['run_id', 'runId']) ||
      readString(runRecords, ['id', 'run_id', 'runId']) ||
      null,
    revision:
      readNumber(records, ['run_revision', 'runRevision']) ??
      readNumber(invocationRecordsOnly, ['run_revision', 'runRevision', 'revision']) ??
      readNumber(runRecords, ['revision']) ??
      null,
    authorizationId:
      readString(records, ['authorization_id', 'authorizationId', 'grant_id', 'grantId']) ||
      readString(authorizationRecords, ['id', 'authorization_id', 'grant_id']) ||
      null,
    inputFingerprint: fingerprint(
      item.toolInput ?? readValue(records, ['tool_input', 'toolInput', 'arguments']),
    ),
  };
}

function explicitInvocationStatus(
  item: AgentTimelineItem,
  records: Record<string, unknown>[],
  invocationRecordsOnly: Record<string, unknown>[],
): ToolInvocationStatus | null {
  const candidates = [
    readString(invocationRecordsOnly, ['status', 'state']),
    readString(records, ['invocation_status', 'invocationStatus', 'tool_status', 'toolStatus']),
    readString(records, ['status', 'state']),
    statusFromEventType(item.type),
  ];
  for (const candidate of candidates) {
    const normalized = normalizeInvocationStatus(candidate);
    if (normalized) return normalized;
  }
  return null;
}

function structuralInvocationStatus(item: AgentTimelineItem): ToolInvocationStatus | null {
  if (item.type === 'observe') return item.isError || item.error ? 'failed' : 'completed';
  if (item.type === 'act' || item.type === 'act_delta') return 'executing';
  return null;
}

function normalizeInvocationStatus(value: string | null): ToolInvocationStatus | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase().replace(/[\s-]+/g, '_');
  return invocationStatuses.has(normalized as ToolInvocationStatus)
    ? (normalized as ToolInvocationStatus)
    : null;
}

function statusFromEventType(type: string): string | null {
  const normalized = type.trim().toLowerCase().replace(/[\s-]+/g, '_');
  const prefix = 'tool_invocation_';
  return normalized.startsWith(prefix) ? normalized.slice(prefix.length) : null;
}

function invocationRecords(item: AgentTimelineItem): Record<string, unknown>[] {
  return [
    item,
    asRecord(item.payload),
    asRecord(item.metadata),
    asRecord(item.display),
    asRecord(item.toolInput),
    asRecord(item.toolOutput),
  ].filter((value): value is Record<string, unknown> => value !== null);
}

function nestedRecords(
  records: readonly Record<string, unknown>[],
  keys: readonly string[],
): Record<string, unknown>[] {
  const nested: Record<string, unknown>[] = [];
  for (const record of records) {
    for (const key of keys) {
      const value = asRecord(record[key]);
      if (value) nested.push(value);
    }
  }
  return nested;
}

function readString(
  records: readonly Record<string, unknown>[],
  keys: readonly string[],
): string | null {
  for (const record of records) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === 'string' && value.trim()) return value.trim();
    }
  }
  return null;
}

function readNumber(
  records: readonly Record<string, unknown>[],
  keys: readonly string[],
): number | null {
  for (const record of records) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === 'number' && Number.isFinite(value)) return value;
    }
  }
  return null;
}

function readValue(
  records: readonly Record<string, unknown>[],
  keys: readonly string[],
): unknown {
  for (const record of records) {
    for (const key of keys) {
      if (record[key] !== undefined) return record[key];
    }
  }
  return undefined;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function fingerprint(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value === 'string') return value.trim() || null;
  try {
    return JSON.stringify(sortRecordKeys(value));
  } catch {
    return null;
  }
}

function sortRecordKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortRecordKeys);
  const record = asRecord(value);
  if (!record) return value;
  return Object.fromEntries(
    Object.keys(record)
      .sort()
      .map((key) => [key, sortRecordKeys(record[key])]),
  );
}

function compareTimelineItems(left: AgentTimelineItem, right: AgentTimelineItem): number {
  if (left.eventTimeUs !== right.eventTimeUs) return left.eventTimeUs - right.eventTimeUs;
  return left.eventCounter - right.eventCounter;
}

function matchingPendingIndex(
  pending: readonly PendingInvocation[],
  toolName: string,
  inputFingerprint: string | null,
): number {
  for (let index = pending.length - 1; index >= 0; index -= 1) {
    const candidate = pending[index];
    if (!candidate) continue;
    if (toolName && candidate.toolName && candidate.toolName !== toolName) continue;
    if (
      inputFingerprint &&
      candidate.inputFingerprint &&
      candidate.inputFingerprint !== inputFingerprint
    ) {
      continue;
    }
    return index;
  }
  return -1;
}

function removePendingKey(pending: PendingInvocation[], key: string): void {
  for (let index = pending.length - 1; index >= 0; index -= 1) {
    if (pending[index]?.key === key) pending.splice(index, 1);
  }
}

function appendUnique(values: readonly string[], value: string): string[] {
  return values.includes(value) ? [...values] : [...values, value];
}

function isObservation(item: AgentTimelineItem): boolean {
  return item.type === 'observe';
}

function isTerminalInvocationStatus(status: ToolInvocationStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'unknown_outcome';
}
