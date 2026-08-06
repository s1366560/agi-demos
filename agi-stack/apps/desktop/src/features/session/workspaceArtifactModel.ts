import type {
  ReviewDecisionSummary,
  WorkspaceArtifact,
  WorkspaceArtifactKind,
} from '../../appShellTypes';
import type {
  AgentTimelineItem,
  DesktopApprovalRequest,
  PlanSnapshot,
} from '../../types';
import {
  arrayField,
  asRecordValue,
  compactArtifactValue,
  formatArtifactTime,
  formatBytes,
  isRecordValue,
  normalizeTimestamp,
  numberField,
  objectField,
  readStringField,
} from '../../utils/format';
import { timelineItemFromSocketEvent } from '../chat/appTimelineEventModel';
import { hasAuthoritativeChangeReview } from './sessionCanvasModel';

export function buildReviewDecisionSummary(
  approvalRequest: DesktopApprovalRequest | null,
): ReviewDecisionSummary {
  const decision = approvalRequest?.decision ?? null;
  const fileIds = decision?.scope.kind === 'files' ? decision.scope.ids : [];
  const risk =
    decision?.risk.level === 'high'
      ? 'High'
      : decision?.risk.level === 'medium'
        ? 'Medium'
        : decision?.risk.level === 'low'
          ? 'Low'
          : 'Unassessed';

  return {
    title: decision?.action.label ?? 'No review packet loaded',
    summary:
      decision?.data.summary ??
      'The backend has not supplied a complete structured approval packet.',
    reasoning:
      decision?.reason ??
      'No agent-authored rationale is available for this approval request.',
    risk,
    changeValue: '+0 / -0',
    filesChanged: fileIds.length,
    artifacts: (decision?.evidence ?? []).map((evidence) => ({
      id: evidence.id,
      name: evidence.label,
      path: evidence.uri ?? evidence.id,
      meta: [evidence.kind, evidence.digest].filter(Boolean).join(' · '),
      diff: '',
    })),
    checks: decision
      ? [
          {
            label: 'Target',
            value: `${decision.target.kind} · ${decision.target.id}`,
          },
          {
            label: 'Scope',
            value: `${decision.scope.kind} · ${decision.scope.ids.length}`,
          },
          {
            label: 'Reversibility',
            value: decision.reversibility.mode,
          },
        ]
      : [],
    canAct: hasAuthoritativeChangeReview({
      changedFileCount: 0,
      hasPendingHitlRequest: Boolean(approvalRequest),
    }),
  };
}

export function buildWorkspaceArtifacts(
  timelineItems: AgentTimelineItem[],
  socketEvents: unknown[],
  plan: PlanSnapshot | null,
): WorkspaceArtifact[] {
  const artifacts = [
    ...timelineItems.flatMap((item) => artifactsFromTimelineItem(item)),
    ...socketEvents.flatMap((event, index) =>
      artifactsFromSocketEvent(event, index),
    ),
    ...artifactsFromPlan(plan),
  ];
  const byKey = new Map<string, WorkspaceArtifact>();

  artifacts.forEach((artifact) => {
    const key = workspaceArtifactIdentity(artifact);
    const existing = byKey.get(key);
    if (!existing || shouldReplaceWorkspaceArtifact(existing, artifact)) {
      byKey.set(key, artifact);
    }
  });

  return [...byKey.values()].sort((left, right) => {
    if (left.sortTime !== right.sortTime) return right.sortTime - left.sortTime;
    return left.name.localeCompare(right.name);
  });
}

export function shouldReplaceWorkspaceArtifact(
  existing: WorkspaceArtifact,
  candidate: WorkspaceArtifact,
): boolean {
  const statusDelta =
    artifactStatusRank(candidate.status) - artifactStatusRank(existing.status);
  if (statusDelta !== 0) return statusDelta > 0;
  return candidate.sortTime >= existing.sortTime;
}

export function artifactStatusRank(status: string): number {
  const normalized = status.toLowerCase();
  if (normalized === 'error' || normalized === 'failed') return 5;
  if (normalized === 'ready' || normalized === 'indexed') return 4;
  if (normalized === 'observed') return 3;
  if (normalized === 'created') return 2;
  if (normalized === 'running') return 1;
  return 0;
}

export function workspaceArtifactIdentity(artifact: WorkspaceArtifact): string {
  const artifactId = artifactIdFromRaw(artifact.raw);
  if (artifactId) return `${artifact.kind}:id:${artifactId}`;
  if (artifact.source.startsWith('artifact_'))
    return `${artifact.kind}:name:${artifact.name}`;
  return `${artifact.kind}:${artifact.path || artifact.name || artifact.id}`;
}

export function artifactIdFromRaw(
  value: unknown,
  depth = 0,
): string | undefined {
  if (depth > 4) return undefined;
  const record = asRecordValue(value);
  if (!record) return undefined;
  const direct =
    readStringField(record, 'artifact_id') ??
    readStringField(record, 'artifactId');
  if (direct) return direct;
  for (const key of ['payload', 'data', 'artifact']) {
    const nested = artifactIdFromRaw(record[key], depth + 1);
    if (nested) return nested;
  }
  return undefined;
}

export function artifactsFromTimelineItem(
  item: AgentTimelineItem,
): WorkspaceArtifact[] {
  const metadata = artifactFileMetadata(item);
  const operation =
    readStringField(metadata ?? {}, 'operation') ?? item.toolName ?? item.type;
  const paths = arrayField(metadata ?? {}, 'paths').filter(isRecordValue);
  const isArtifactEvent =
    item.type.startsWith('artifact_') ||
    Boolean(item.filename || item.artifactId);
  const writesFiles = ['write', 'edit', 'patch', 'export_artifact'].includes(
    operation,
  );

  if (paths.length && (isArtifactEvent || writesFiles || item.toolName)) {
    return paths.map((path, index) =>
      artifactFromPathMetadata(path, {
        id: `${item.id}:path:${index}`,
        source: item.toolName || item.type,
        status: artifactStatus(item),
        sortTime: artifactSortTime(item),
        raw: item,
        fallbackPreview: timelineArtifactPreview(item),
        diff: diffStatLabel(metadata),
      }),
    );
  }

  if (!isArtifactEvent && !writesFiles) return [];

  const filename =
    item.filename ??
    readStringField(asRecordValue(item.payload) ?? {}, 'filename');
  const artifactId =
    item.artifactId ??
    readStringField(asRecordValue(item.payload) ?? {}, 'artifact_id');
  const name = filename || artifactId || item.toolName || item.type;
  const path =
    artifactPathFromRecord(asRecordValue(item.payload)) ||
    filename ||
    artifactId ||
    '';
  return [
    makeWorkspaceArtifact({
      id: item.id,
      name,
      path,
      kind: artifactKind(name, operation),
      source: item.toolName || item.type,
      status: artifactStatus(item),
      sortTime: artifactSortTime(item),
      size: artifactSize(asRecordValue(item.payload)),
      diff: diffStatLabel(metadata),
      preview: timelineArtifactPreview(item),
      raw: item,
    }),
  ];
}

export function artifactsFromSocketEvent(
  event: unknown,
  index: number,
): WorkspaceArtifact[] {
  const item = timelineItemFromSocketEvent(event);
  if (item) {
    const timelineArtifacts = artifactsFromTimelineItem(item);
    if (timelineArtifacts.length) return timelineArtifacts;
  }
  const record = asRecordValue(event);
  if (!record) return [];
  const candidate = socketArtifactCandidate(record);
  if (!candidate) return [];
  const { type, payload } = candidate;
  const name =
    readStringField(payload, 'filename') ??
    readStringField(payload, 'name') ??
    readStringField(payload, 'artifact_id') ??
    type;
  const eventTimeUs =
    numberField(record, 'time_us') ?? numberField(record, 'event_time_us');
  const timestamp = numberField(record, 'timestamp');
  const path = artifactPathFromRecord(payload);
  return [
    makeWorkspaceArtifact({
      id: `socket-artifact-${index}-${type}-${path || name}`,
      name,
      path,
      kind: artifactKind(name, type),
      source: type,
      status: socketArtifactStatus(type, payload),
      sortTime:
        typeof eventTimeUs === 'number'
          ? Math.floor(eventTimeUs / 1000)
          : normalizeTimestamp(timestamp),
      size: artifactSize(payload),
      diff: '',
      preview: compactArtifactValue(payload),
      raw: event,
    }),
  ];
}

export function socketArtifactCandidate(
  record: Record<string, unknown>,
): { type: string; payload: Record<string, unknown> } | null {
  const topType =
    readStringField(record, 'type') ??
    readStringField(record, 'event_type') ??
    'event';
  const topPayload =
    objectField(record, 'payload') ?? objectField(record, 'data') ?? record;
  const candidates: Array<{ type: string; payload: Record<string, unknown> }> =
    [{ type: topType, payload: topPayload }];
  const payloadType = readStringField(topPayload, 'type');
  if (payloadType) {
    candidates.push({
      type: payloadType,
      payload: objectField(topPayload, 'data') ?? topPayload,
    });
  }
  const nestedData = objectField(topPayload, 'data');
  const nestedDataType = nestedData
    ? readStringField(nestedData, 'type')
    : undefined;
  if (nestedData && nestedDataType) {
    candidates.push({
      type: nestedDataType,
      payload: objectField(nestedData, 'data') ?? nestedData,
    });
  }
  const nestedPayload = objectField(topPayload, 'payload');
  const nestedPayloadType = nestedPayload
    ? readStringField(nestedPayload, 'type')
    : undefined;
  if (nestedPayload && nestedPayloadType) {
    candidates.push({
      type: nestedPayloadType,
      payload: objectField(nestedPayload, 'data') ?? nestedPayload,
    });
  }

  return (
    candidates.find(({ type, payload }) => {
      const normalizedType = type.toLowerCase();
      const typeHasArtifact = normalizedType.includes('artifact');
      const hasArtifactId = Boolean(readStringField(payload, 'artifact_id'));
      const hasFileSignal = Boolean(
        readStringField(payload, 'filename') ??
        readStringField(payload, 'relativePath') ??
        readStringField(payload, 'relative_path') ??
        readStringField(payload, 'path'),
      );
      return (
        typeHasArtifact ||
        hasArtifactId ||
        (hasFileSignal && normalizedType.includes('file'))
      );
    }) ?? null
  );
}

export function socketArtifactStatus(
  type: string,
  payload: Record<string, unknown>,
): string {
  const direct =
    readStringField(payload, 'status') ?? readStringField(payload, 'state');
  if (direct) return direct;
  if (type === 'artifact_ready') return 'ready';
  if (type === 'artifact_created') return 'created';
  return 'event';
}

export function artifactsFromPlan(plan: PlanSnapshot | null): WorkspaceArtifact[] {
  if (!plan) return [];
  const index = plan.artifact_index ?? plan.artifacts;
  if (!index) return [];
  if (Array.isArray(index)) {
    return index.flatMap((entry, position) =>
      artifactFromPlanEntry(entry, String(position)),
    );
  }
  const record = asRecordValue(index);
  if (!record) return [];
  return Object.entries(record).flatMap(([key, value]) =>
    artifactFromPlanEntry(value, key),
  );
}

export function artifactFromPlanEntry(
  entry: unknown,
  key: string,
): WorkspaceArtifact[] {
  const record = asRecordValue(entry);
  const name =
    (record &&
      (readStringField(record, 'name') ??
        readStringField(record, 'filename') ??
        readStringField(record, 'id'))) ??
    key;
  const path = record ? artifactPathFromRecord(record) : '';
  return [
    makeWorkspaceArtifact({
      id: `plan-artifact-${key}`,
      name,
      path,
      kind: artifactKind(
        name,
        record ? readStringField(record, 'type') : undefined,
      ),
      source: 'plan',
      status: record
        ? (readStringField(record, 'status') ?? 'indexed')
        : 'indexed',
      sortTime: Date.now() - 1,
      size: record ? artifactSize(record) : '',
      diff: record ? (readStringField(record, 'diff') ?? '') : '',
      preview: record ? compactArtifactValue(record) : String(entry),
      raw: entry,
    }),
  ];
}

export function artifactFromPathMetadata(
  path: Record<string, unknown>,
  base: {
    id: string;
    source: string;
    status: string;
    sortTime: number;
    raw: unknown;
    fallbackPreview: string;
    diff: string;
  },
): WorkspaceArtifact {
  const pathValue =
    readStringField(path, 'relativePath') ??
    readStringField(path, 'relative_path') ??
    readStringField(path, 'path') ??
    'file';
  const name = pathValue.split('/').filter(Boolean).pop() ?? pathValue;
  return makeWorkspaceArtifact({
    id: base.id,
    name,
    path: pathValue,
    kind: artifactKind(pathValue, base.source),
    source: base.source,
    status: pathStatus(path, base.status),
    sortTime: base.sortTime,
    size: artifactSize(path),
    diff: pathDiffStatLabel(path, base.diff),
    preview: readStringField(path, 'preview') ?? base.fallbackPreview,
    raw: base.raw,
  });
}

export function makeWorkspaceArtifact(
  input: Omit<WorkspaceArtifact, 'searchableText' | 'time'>,
): WorkspaceArtifact {
  return {
    ...input,
    time: formatArtifactTime(input.sortTime),
    searchableText: [
      input.name,
      input.path,
      input.kind,
      input.source,
      input.status,
      input.size,
      input.diff,
      input.preview,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase(),
  };
}

export function artifactFileMetadata(
  item: AgentTimelineItem,
): Record<string, unknown> | null {
  const direct = asRecordValue(item.fileMetadata);
  if (direct) return direct;
  const output = asRecordValue(item.toolOutput);
  if (!output) return null;
  return (
    objectField(output, 'fileMetadata') ?? objectField(output, 'file_metadata')
  );
}

export function artifactKind(name: string, hint?: string): WorkspaceArtifactKind {
  const value = `${name} ${hint ?? ''}`.toLowerCase();
  if (
    value.includes('patch') ||
    value.endsWith('.diff') ||
    value.endsWith('.patch')
  )
    return 'Patches';
  if (
    value.includes('report') ||
    value.endsWith('.md') ||
    value.endsWith('.pdf')
  )
    return 'Reports';
  if (value.includes('log') || value.endsWith('.log')) return 'Logs';
  if (value.includes('event') || value.includes('artifact_')) return 'Events';
  return 'Files';
}

export function artifactStatus(item: AgentTimelineItem): string {
  if (item.isError || item.error || item.type === 'artifact_error')
    return 'error';
  if (item.type === 'artifact_ready') return 'ready';
  if (item.type === 'artifact_created') return 'created';
  if (item.type === 'observe') return 'observed';
  if (item.type === 'act') return 'running';
  return item.type;
}

export function artifactSortTime(item: AgentTimelineItem): number {
  return item.eventTimeUs
    ? Math.floor(item.eventTimeUs / 1000)
    : normalizeTimestamp(item.timestamp);
}

export function pathStatus(path: Record<string, unknown>, fallback: string): string {
  if (path.deleted === true) return 'deleted';
  if (path.created === true) return 'created';
  if (path.changed === true) return 'changed';
  return fallback;
}

export function artifactPathFromRecord(
  record: Record<string, unknown> | null,
): string {
  if (!record) return '';
  return (
    readStringField(record, 'path') ??
    readStringField(record, 'relativePath') ??
    readStringField(record, 'relative_path') ??
    readStringField(record, 'url') ??
    ''
  );
}

export function artifactSize(record: Record<string, unknown> | null): string {
  if (!record) return '';
  const size =
    numberField(record, 'bytesWritten') ??
    numberField(record, 'bytes_written') ??
    numberField(record, 'bytesRead') ??
    numberField(record, 'bytes_read') ??
    numberField(record, 'size') ??
    numberField(record, 'size_bytes');
  return typeof size === 'number' ? formatBytes(size) : '';
}

export function diffStatLabel(metadata: Record<string, unknown> | null): string {
  const diffStat = metadata
    ? (objectField(metadata, 'diffStat') ?? objectField(metadata, 'diff_stat'))
    : null;
  if (!diffStat) return '';
  const files =
    numberField(diffStat, 'filesChanged') ??
    numberField(diffStat, 'files_changed');
  const additions = numberField(diffStat, 'additions');
  const deletions = numberField(diffStat, 'deletions');
  const parts = [];
  if (typeof files === 'number') parts.push(`${files} files`);
  if (typeof additions === 'number') parts.push(`+${additions}`);
  if (typeof deletions === 'number') parts.push(`-${deletions}`);
  return parts.join(' / ');
}

export function pathDiffStatLabel(
  path: Record<string, unknown>,
  fallback: string,
): string {
  const direct =
    readStringField(path, 'diff') ?? readStringField(path, 'diffStatLabel');
  if (direct) return direct;
  const diffStat =
    objectField(path, 'diffStat') ?? objectField(path, 'diff_stat');
  if (!diffStat) return fallback;
  const additions = numberField(diffStat, 'additions');
  const deletions = numberField(diffStat, 'deletions');
  const parts = [];
  if (typeof additions === 'number') parts.push(`+${additions}`);
  if (typeof deletions === 'number') parts.push(`-${deletions}`);
  return parts.length ? parts.join(' / ') : fallback;
}

export function timelineArtifactPreview(item: AgentTimelineItem): string {
  if (item.error) return item.error;
  if (item.content) return item.content;
  const display = asRecordValue(item.display);
  const summary = display
    ? (readStringField(display, 'summary') ?? readStringField(display, 'title'))
    : undefined;
  if (summary) return summary;
  if (item.payload !== undefined) return compactArtifactValue(item.payload);
  if (item.toolOutput !== undefined)
    return compactArtifactValue(item.toolOutput);
  return item.toolName || item.type;
}
