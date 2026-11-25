import { memo } from 'react';
import { useAgentV3Store } from '@business/agent/ui/web/stores/agentV3';
import {
  LlmOverrideView,
  type LlmOverrideViewProps,
} from '@business/agent/ui/web/chat/LlmOverrideView';
import type { LLMConfigOverrides } from '@/types/memory';
type Props = Omit<LlmOverrideViewProps, 'readOverrides' | 'onChange'> & {
  conversationId: string | null;
};

export const LlmOverridePopover = memo<Props>(({ conversationId, ...props }) => (
  <LlmOverrideView
    {...props}
    readOverrides={() => {
      if (!conversationId) return undefined;
      return useAgentV3Store.getState().conversationStates.get(conversationId)?.appModelContext
        ?.llm_overrides as LLMConfigOverrides | undefined;
    }}
    onChange={(value) => {
      if (conversationId)
        useAgentV3Store
          .getState()
          .setLlmOverrides(conversationId, Object.keys(value).length ? value : null);
    }}
  />
));
LlmOverridePopover.displayName = 'LlmOverridePopover';
