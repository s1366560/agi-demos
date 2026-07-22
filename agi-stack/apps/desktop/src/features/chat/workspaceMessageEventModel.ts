import type { WorkspaceMessage } from '../../types';

export type WorkspaceMessageStreamResult = {
  handled: boolean;
  messages: WorkspaceMessage[];
};

export function applyWorkspaceMessageStreamEvent(
  existing: WorkspaceMessage[],
  event: unknown,
  workspaceId: string,
): WorkspaceMessageStreamResult {
  const root = recordValue(event);
  if (!root || stringValue(root.type ?? root.event_type) !== 'workspace_message_created') {
    return { handled: false, messages: existing };
  }
  const data = recordValue(root.data) ?? recordValue(root.payload);
  if (!data || !isHostedSensingEvent(data)) {
    return { handled: false, messages: existing };
  }
  const message = workspaceMessageValue(data.message);
  if (!message || !workspaceId || message.workspace_id !== workspaceId) {
    return { handled: false, messages: existing };
  }
  if (existing.some((candidate) => candidate.id === message.id)) {
    return { handled: true, messages: existing };
  }
  return { handled: true, messages: [...existing, message] };
}

function isHostedSensingEvent(data: Record<string, unknown>): boolean {
  const boundary = data.surface_boundary;
  const signalRole = data.signal_role;
  if (boundary === undefined && signalRole === undefined) return true;
  return boundary === 'hosted' && signalRole === 'sensing-capable';
}

function workspaceMessageValue(value: unknown): WorkspaceMessage | null {
  const message = recordValue(value);
  if (!message) return null;
  const id = stringValue(message.id);
  const workspaceId = stringValue(message.workspace_id);
  if (!id || !workspaceId || typeof message.content !== 'string') return null;

  const mentions = optionalStringArray(message.mentions);
  if (mentions === null) return null;
  const parentMessageId = optionalNullableString(message.parent_message_id);
  if (parentMessageId.invalid) return null;
  const senderType = optionalString(message.sender_type);
  const senderId = optionalNullableString(message.sender_id);
  const createdAt = optionalString(message.created_at);
  const metadata = optionalNullableRecord(message.metadata);
  if (senderType.invalid || senderId.invalid || createdAt.invalid || metadata.invalid) return null;

  return {
    id,
    workspace_id: workspaceId,
    content: message.content,
    ...(parentMessageId.value !== undefined
      ? { parent_message_id: parentMessageId.value }
      : {}),
    ...(senderType.value !== undefined ? { sender_type: senderType.value } : {}),
    ...(senderId.value !== undefined ? { sender_id: senderId.value } : {}),
    ...(mentions !== undefined ? { mentions } : {}),
    ...(createdAt.value !== undefined ? { created_at: createdAt.value } : {}),
    ...(metadata.value !== undefined ? { metadata: metadata.value } : {}),
  };
}

function optionalString(value: unknown): { invalid: boolean; value?: string } {
  if (value === undefined) return { invalid: false };
  return typeof value === 'string'
    ? { invalid: false, value }
    : { invalid: true };
}

function optionalNullableString(
  value: unknown,
): { invalid: boolean; value?: string | null } {
  if (value === undefined) return { invalid: false };
  return value === null || typeof value === 'string'
    ? { invalid: false, value }
    : { invalid: true };
}

function optionalStringArray(value: unknown): string[] | undefined | null {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || !value.every((entry) => typeof entry === 'string')) return null;
  return [...value];
}

function optionalNullableRecord(
  value: unknown,
): { invalid: boolean; value?: Record<string, unknown> | null } {
  if (value === undefined) return { invalid: false };
  if (value === null) return { invalid: false, value: null };
  const record = recordValue(value);
  return record ? { invalid: false, value: record } : { invalid: true };
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
