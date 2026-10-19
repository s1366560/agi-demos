import { createElement, type ReactNode } from 'react';

import { useAgentV3Store } from '@/stores/agentV3';
import { useProjectStore } from '@/stores/project';

import {
  useWebToolResultSlotV2,
  useWebUiSlotAuthorityV2,
} from '@/routes/v2/webUiSlotAuthorityStateV2';

import { PluginSlotHost } from './PluginSlotHost';

import type { SlotContextV2 } from '@agistack/plugin-slots';

export interface PluginToolResultRendererProps {
  readonly toolName: string;
  readonly result: string;
  readonly fallback: ReactNode;
}

export function PluginToolResultRenderer({
  toolName,
  result,
  fallback,
}: PluginToolResultRendererProps) {
  const slot = useWebToolResultSlotV2(toolName);
  const authority = useWebUiSlotAuthorityV2();
  const project = useProjectStore((state) => state.currentProject);
  const conversationId = useAgentV3Store((state) => state.activeConversationId);
  if (!slot) return <>{fallback}</>;
  const context: SlotContextV2<'tool_result_renderer'> = {
    kind: 'tool-result',
    toolName,
    status: 'complete',
    presentation: { kind: 'text', text: result },
    conversationId,
    ...(project ? { tenantId: project.tenant_id, projectId: project.id } : {}),
  };
  const renderer = authority.renderers?.resolve(slot);
  const key = `${authority.generationId ?? 'standalone'}/${slot.pluginId}/${slot.id}`;
  if (renderer) return createElement(renderer, { key, slot, context });
  return (
    <PluginSlotHost
      key={key}
      slot={slot}
      generationId={authority.generationId}
      initPayload={context}
      fallback={fallback}
    />
  );
}
