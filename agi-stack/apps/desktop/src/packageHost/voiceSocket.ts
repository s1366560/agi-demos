import type { OpenVoiceSocket, VoiceSocket } from '../../../../packages/plugin-slots/src/pageVoice';
import { desktopCloudSessionProjectionClient } from '../api/cloudSessionProjectionClient';
import { createCloudSocketBridge, desktopCloudSocketTransport } from '../api/cloudSocketBridge';

export const openVoiceSocket: OpenVoiceSocket = async (scope, signal) => {
  const session = await desktopCloudSessionProjectionClient()?.load(signal);
  const native = desktopCloudSocketTransport();
  if (
    !native ||
    !session ||
    session.user.userId !== scope.principalId ||
    session.workspaceContext.tenantId !== scope.tenantId ||
    session.workspaceContext.projectId !== scope.projectId
  )
    throw new Error('voice_scope_changed');
  const granted = await window.__MEMSTACK_DESKTOP__?.core?.invoke?.<boolean>(
    'request_microphone_access'
  );
  signal.throwIfAborted();
  if (granted !== true) throw new Error('microphone_permission_denied');
  const url = new URL('/api/v1/voice/chat', session.apiBaseUrl);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('project_id', scope.projectId);
  url.searchParams.set('conversation_id', scope.conversationId);
  url.searchParams.set('package_session', '1');
  return createCloudSocketBridge(
    {
      kind: 'voice',
      url: url.toString(),
      scope: {
        tenant_id: scope.tenantId,
        project_id: scope.projectId,
        workspace_id: null,
        conversation_id: scope.conversationId,
      },
    },
    native
  ) as unknown as VoiceSocket;
};
