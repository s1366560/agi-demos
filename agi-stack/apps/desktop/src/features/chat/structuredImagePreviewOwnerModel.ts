import type { StructuredImagePreviewClientV2 } from '../../plugins/desktopStructuredImagePreviewAuthorityModuleV2';
import type { WorkspaceMessage } from '../../types';

export function conversationImagePreviewClient(
  client: StructuredImagePreviewClientV2 | null,
  conversationId: string | null,
): StructuredImagePreviewClientV2 | null {
  return client?.owner.kind === 'conversation' &&
    conversationId &&
    client.owner.id === conversationId
    ? client
    : null;
}

export function workspaceImagePreviewClient(
  client: StructuredImagePreviewClientV2 | null,
  message: WorkspaceMessage,
): StructuredImagePreviewClientV2 | null {
  if (client?.owner.kind !== 'workspace') return null;
  if (message.workspace_id !== undefined && message.workspace_id !== client.owner.id) return null;
  return client;
}
