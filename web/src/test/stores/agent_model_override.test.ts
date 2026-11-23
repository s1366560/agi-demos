import { act } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useAgentV3Store } from '@business/agent/ui/web/stores/agentV3';

describe('AgentV3 store - model override', () => {
  beforeEach(() => {
    useAgentV3Store.setState({
      activeConversationId: null,
      conversationStates: new Map(),
    });
  });

  it('sets and clears llm_model_override while preserving existing llm_overrides', () => {
    const conversationId = 'conv-model-1';

    act(() => {
      useAgentV3Store.getState().updateConversationState(conversationId, {
        appModelContext: {
          llm_overrides: { temperature: 0.3 },
        },
      });
    });

    act(() => {
      useAgentV3Store.getState().setLlmModelOverride(conversationId, 'openai/gpt-4o-mini');
    });

    const afterSet = useAgentV3Store.getState().conversationStates.get(conversationId);
    const afterSetCtx = (afterSet?.appModelContext ?? {}) as Record<string, unknown>;
    expect(afterSetCtx.llm_model_override).toBe('openai/gpt-4o-mini');
    expect(afterSetCtx.llm_overrides).toEqual({ temperature: 0.3 });

    act(() => {
      useAgentV3Store.getState().setLlmModelOverride(conversationId, null);
    });

    const afterClear = useAgentV3Store.getState().conversationStates.get(conversationId);
    const afterClearCtx = (afterClear?.appModelContext ?? {}) as Record<string, unknown>;
    expect(afterClearCtx.llm_model_override).toBeUndefined();
    expect(afterClearCtx.llm_overrides).toEqual({ temperature: 0.3 });
  });
});
