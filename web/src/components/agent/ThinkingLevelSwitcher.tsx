import React from 'react';

import { ThinkingLevelSwitcherView } from '@business/agent/ui/web/chat/ThinkingLevelSwitcherView';

import {
  thinkingLevelToEffort,
  useAgentThinkingLevelStore,
  type AgentThinkingLevel,
} from '@business/agent/ui/web/stores/agent/thinkingLevelStore';
import { useAgentV3Store } from '@business/agent/ui/web/stores/agentV3';

import { agentService } from '@/services/agentService';

export interface ThinkingLevelSwitcherProps {
  conversationId: string | null;
  projectId?: string | undefined;
  disabled?: boolean | undefined;
}

export const ThinkingLevelSwitcher: React.FC<ThinkingLevelSwitcherProps> = ({
  conversationId,
  projectId,
  disabled = false,
}) => {
  const level = useAgentThinkingLevelStore(
    (state) =>
      (conversationId ? state.levelsByConversation[conversationId] : undefined) ?? 'default'
  );
  const setThinkingLevel = useAgentThinkingLevelStore((state) => state.setThinkingLevel);

  const save = (nextLevel: AgentThinkingLevel) => {
    if (conversationId) {
      setThinkingLevel(conversationId, nextLevel);

      // Mirror into the wire payload (merged with other LLM overrides) and
      // persist server-side so the level survives reloads, mirroring the
      // model-switch behavior.
      const effort = thinkingLevelToEffort(nextLevel);
      useAgentV3Store.getState().setReasoningEffort(conversationId, effort ?? null);
      if (projectId) {
        const convState = useAgentV3Store.getState().conversationStates.get(conversationId);
        const ctx = convState?.appModelContext ?? null;
        const overrides = (ctx?.llm_overrides as Record<string, unknown> | null) ?? null;
        agentService
          .updateConversationConfig(conversationId, projectId, {
            llm_overrides: overrides,
          })
          .catch((err: unknown) => {
            console.error('ThinkingLevelSwitcher: persist config failed', err);
          });
      }
    }
  };
  return <ThinkingLevelSwitcherView level={level} disabled={disabled} save={save} />;
};
