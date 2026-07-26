import type { WorkspaceMessage } from '../../types';

export type WorkspaceMessageIdentityLabels = {
  agent: string;
  system: string;
  you: string;
};

const WORKSPACE_MESSAGE_TIME_FORMAT = new Intl.DateTimeFormat([], {
  hour: '2-digit',
  minute: '2-digit',
});

export function workspaceMessageSenderLabel(
  message: WorkspaceMessage,
  labels: WorkspaceMessageIdentityLabels,
): string {
  const senderName = structuredSenderName(message.metadata);
  if (senderName) return senderName;

  const senderType = (message.sender_type ?? '').toLowerCase();
  if (senderType === 'human' || senderType === 'user') return labels.you;
  if (senderType === 'runtime' || senderType === 'system') return labels.system;
  return labels.agent;
}

export function formatWorkspaceMessageTime(value: string | undefined): string {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return WORKSPACE_MESSAGE_TIME_FORMAT.format(parsed);
}

function structuredSenderName(metadata: WorkspaceMessage['metadata']): string | null {
  if (!metadata) return null;
  const value = metadata.sender_name;
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized || null;
}
