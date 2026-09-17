/**
 * Unit tests for the settingsActions.setReasoningEffort merge semantics.
 *
 * The thinking-level switcher merges reasoning_effort into the existing
 * llm_overrides map instead of replacing it, so temperature and friends must
 * survive a level change and a "default" reset must not drop them.
 */

import { describe, it, expect, vi } from 'vitest';

import { createSettingsActions } from '../../../stores/agent/settingsActions';

import type { ConversationState } from '../../../types/conversationState';

function makeDeps(initial: Record<string, ConversationState>) {
  const conversationStates = new Map<string, ConversationState>(Object.entries(initial));
  const updateConversationState = vi.fn(
    (conversationId: string, updates: Partial<ConversationState>) => {
      const current = conversationStates.get(conversationId) ?? ({} as ConversationState);
      conversationStates.set(conversationId, { ...current, ...updates });
    }
  );
  const actions = createSettingsActions({
    get: () => ({ conversationStates, updateConversationState }),
    set: vi.fn(),
  });
  return { conversationStates, updateConversationState, actions };
}

describe('setReasoningEffort', () => {
  it('should create llm_overrides with only reasoning_effort when none exist', () => {
    const { conversationStates, actions } = makeDeps({ 'conv-1': {} as ConversationState });

    actions.setReasoningEffort('conv-1', 'high');

    expect(conversationStates.get('conv-1')?.appModelContext).toEqual({
      llm_overrides: { reasoning_effort: 'high' },
    });
  });

  it('should merge into existing llm_overrides without dropping parameters', () => {
    const { conversationStates, actions } = makeDeps({
      'conv-1': {
        appModelContext: { llm_overrides: { temperature: 0.3, max_tokens: 2048 } },
      } as ConversationState,
    });

    actions.setReasoningEffort('conv-1', 'medium');

    expect(conversationStates.get('conv-1')?.appModelContext).toEqual({
      llm_overrides: { temperature: 0.3, max_tokens: 2048, reasoning_effort: 'medium' },
    });
  });

  it('should remove only reasoning_effort when resetting to default', () => {
    const { conversationStates, actions } = makeDeps({
      'conv-1': {
        appModelContext: {
          llm_overrides: { temperature: 0.3, reasoning_effort: 'high' },
        },
      } as ConversationState,
    });

    actions.setReasoningEffort('conv-1', null);

    expect(conversationStates.get('conv-1')?.appModelContext).toEqual({
      llm_overrides: { temperature: 0.3 },
    });
  });

  it('should drop the whole llm_overrides map when it becomes empty', () => {
    const { conversationStates, actions } = makeDeps({
      'conv-1': {
        appModelContext: { llm_overrides: { reasoning_effort: 'low' } },
      } as ConversationState,
    });

    actions.setReasoningEffort('conv-1', null);

    expect(conversationStates.get('conv-1')?.appModelContext).toBeNull();
  });

  it('should be a no-op when clearing without any overrides present', () => {
    const { conversationStates, updateConversationState, actions } = makeDeps({
      'conv-1': {} as ConversationState,
    });

    actions.setReasoningEffort('conv-1', null);

    expect(updateConversationState).not.toHaveBeenCalled();
    expect(conversationStates.get('conv-1')?.appModelContext).toBeUndefined();
  });
});
