import { memo } from 'react';
import { useAgentV3Store } from '@business/agent/ui/web/stores/agentV3';
import { useCanvasStore } from '@/stores/canvasStore';
import { agentService } from '@/services/agentService';
import { A2UISurfaceRenderer as Surface, type A2UISurfaceRendererProps } from '@business/agent/ui/web/canvas/A2UISurfaceRenderer';
export type { A2UISurfaceRendererProps };
function useAuthority(surfaceId: string) {
  const conversationId = useAgentV3Store((s) => s.activeConversationId);
  const hitlRequestId = useCanvasStore((s) => s.tabs.find((tab) => tab.a2uiSurfaceId === surfaceId)?.a2uiHitlRequestId);
  return { conversationId, hitlRequestId, respondToA2UIAction: agentService.respondToA2UIAction.bind(agentService) };
}
export const A2UISurfaceRenderer = memo((props: A2UISurfaceRendererProps) => <Surface {...props} useAuthority={useAuthority} />);
