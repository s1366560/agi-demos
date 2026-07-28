import type { AgentTimelineItem, HitlResponseSubmission } from '../../types';
import type { A2UIActionCommand, A2UIAllowedAction } from './a2uiSurfaceModel';

export type A2UISurfaceAuthority = {
  artifactId: string;
  requestId: string;
  authorityRevision: number | null;
  idempotencyKey: string;
  allowedActions: A2UIAllowedAction[];
  answered: boolean;
  canRespond: boolean;
};

export function resolveA2UISurfaceAuthority(
  artifactId: string,
  timeline: readonly AgentTimelineItem[],
  respondableRequestIds: readonly string[],
): A2UISurfaceAuthority | null {
  if (!artifactId.trim()) return null;
  const respondable = new Set(respondableRequestIds);
  const candidates = timeline
    .filter((item) => item.type === 'a2ui_action_asked')
    .filter((item) => payloadString(item, 'block_id', 'blockId') === artifactId)
    .sort(compareTimelineItems);
  const item = candidates.at(-1);
  if (!item) return null;
  const requestId =
    payloadString(item, 'request_id', 'requestId') ??
    stringValue(item.requestId) ??
    stringValue(item.request_id);
  if (!requestId) return null;
  const authorityRevision = payloadInteger(
    item,
    'authority_revision',
    'authorityRevision',
    'request_revision',
    'requestRevision',
  );
  const allowedActions = parseAllowedActions(
    payloadValue(item, 'allowed_actions', 'allowedActions'),
  );
  const status = payloadString(item, 'status', 'request_status', 'requestStatus');
  const answered =
    Boolean(item.answered) ||
    status === 'answered' ||
    status === 'expired' ||
    status === 'cancelled';
  return {
    artifactId,
    requestId,
    authorityRevision,
    idempotencyKey: [requestId, authorityRevision ?? 'unversioned', 'a2ui_action'].join(':'),
    allowedActions,
    answered,
    canRespond:
      !answered &&
      authorityRevision !== null &&
      allowedActions.length > 0 &&
      respondable.has(requestId),
  };
}

export function a2uiCommandToHitlSubmission(
  command: A2UIActionCommand,
): HitlResponseSubmission {
  return {
    requestId: command.request_id,
    hitlType: 'a2ui_action',
    expectedRevision: command.authority_revision,
    idempotencyKey: command.idempotency_key,
    responseData: {
      surface_id: command.surface_id,
      source_component_id: command.source_component_id,
      action_name: command.action_name,
      ...(command.context ? { context: command.context } : {}),
    },
  };
}

function parseAllowedActions(value: unknown): A2UIAllowedAction[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 32) return [];
  const actions: A2UIAllowedAction[] = [];
  const seen = new Set<string>();
  for (const candidate of value) {
    const record = asRecord(candidate);
    const sourceComponentId = stringValue(
      record?.source_component_id ?? record?.sourceComponentId,
    );
    const actionName = stringValue(record?.action_name ?? record?.actionName);
    if (!sourceComponentId || !actionName) return [];
    const key = `${sourceComponentId}\u0000${actionName}`;
    if (seen.has(key)) continue;
    seen.add(key);
    actions.push({
      source_component_id: sourceComponentId,
      action_name: actionName,
    });
  }
  return actions;
}

function compareTimelineItems(left: AgentTimelineItem, right: AgentTimelineItem): number {
  if (left.eventTimeUs !== right.eventTimeUs) return left.eventTimeUs - right.eventTimeUs;
  return left.eventCounter - right.eventCounter;
}

function payloadValue(item: AgentTimelineItem, ...keys: string[]): unknown {
  const payload = asRecord(item.payload);
  for (const source of [payload, item]) {
    if (!source) continue;
    for (const key of keys) {
      if (Object.prototype.hasOwnProperty.call(source, key)) return source[key];
    }
  }
  return undefined;
}

function payloadString(item: AgentTimelineItem, ...keys: string[]): string | null {
  return stringValue(payloadValue(item, ...keys));
}

function payloadInteger(item: AgentTimelineItem, ...keys: string[]): number | null {
  const value = payloadValue(item, ...keys);
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
