import { readToolResultMediaResponseV2, type ReplMediaReferenceV2 } from '@agistack/plugin-slots';
import { apiFetch } from './client/urlUtils';

export interface ConversationToolMediaOwnerV2 {
  readonly tenantId: string;
  readonly projectId: string;
  readonly conversationId: string;
}
export function readConversationToolMediaV2(
  owner: ConversationToolMediaOwnerV2,
  reference: ReplMediaReferenceV2,
  signal: AbortSignal
): Promise<Blob> {
  if (
    reference.store !== 'conversation_tool_media' ||
    !owner.tenantId ||
    !owner.projectId ||
    !owner.conversationId
  )
    return Promise.reject(new Error('tool_media_owner_unavailable'));
  const query = new URLSearchParams({ tenant_id: owner.tenantId, project_id: owner.projectId });
  const path = `/agent/conversations/${encodeURIComponent(owner.conversationId)}/tool-media/${encodeURIComponent(reference.artifactId)}?${query}`;
  return apiFetch.get(
    path,
    async (response, operation) => {
      operation.check();
      const blob = await readToolResultMediaResponseV2(response, reference, operation.signal);
      operation.check();
      return blob;
    },
    { signal }
  );
}
