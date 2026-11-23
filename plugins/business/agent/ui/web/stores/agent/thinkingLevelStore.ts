/**
 * Per-conversation agent thinking level.
 *
 * Controls the reasoning effort requested from the model for a conversation.
 * The level is mirrored into `appModelContext.llm_overrides.reasoning_effort`
 * (agentV3 store) so it travels with every turn to the backend, which maps it
 * onto provider-specific reasoning options via `build_reasoning_config`.
 * `default` removes the override and keeps the model-side default.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

export type AgentThinkingLevel = 'default' | 'low' | 'medium' | 'high';

export const THINKING_LEVELS: readonly AgentThinkingLevel[] = [
  'default',
  'low',
  'medium',
  'high',
] as const;

/** Wire value for a level; `undefined` means "remove the override". */
export function thinkingLevelToEffort(
  level: AgentThinkingLevel
): 'low' | 'medium' | 'high' | undefined {
  return level === 'default' ? undefined : level;
}

export function isAgentThinkingLevel(value: unknown): value is AgentThinkingLevel {
  return typeof value === 'string' && THINKING_LEVELS.includes(value as AgentThinkingLevel);
}

interface ThinkingLevelState {
  levelsByConversation: Record<string, AgentThinkingLevel>;
  setThinkingLevel: (conversationId: string, level: AgentThinkingLevel) => void;
  clearConversation: (conversationId: string) => void;
  getThinkingLevel: (conversationId: string) => AgentThinkingLevel;
}

export const useAgentThinkingLevelStore = create<ThinkingLevelState>()(
  devtools(
    persist(
      (set, get) => ({
        levelsByConversation: {},

        setThinkingLevel: (conversationId, level) =>
          set(
            (state) => ({
              levelsByConversation: { ...state.levelsByConversation, [conversationId]: level },
            }),
            false,
            'thinkingLevel/set'
          ),

        clearConversation: (conversationId) =>
          set((state) => {
            if (!(conversationId in state.levelsByConversation)) return state;
            const { [conversationId]: _removed, ...rest } = state.levelsByConversation;
            return { levelsByConversation: rest };
          }),

        getThinkingLevel: (conversationId) =>
          get().levelsByConversation[conversationId] ?? 'default',
      }),
      {
        name: 'agent-thinking-level',
        merge: (persisted, current) => {
          const merged = { ...current };
          if (persisted && typeof persisted === 'object') {
            const stored = persisted as { levelsByConversation?: unknown };
            if (stored.levelsByConversation && typeof stored.levelsByConversation === 'object') {
              const sanitized: Record<string, AgentThinkingLevel> = {};
              for (const [conversationId, level] of Object.entries(
                stored.levelsByConversation as Record<string, unknown>
              )) {
                if (isAgentThinkingLevel(level)) {
                  sanitized[conversationId] = level;
                }
              }
              merged.levelsByConversation = sanitized;
            }
          }
          return merged;
        },
      }
    ),
    { name: 'agent-thinking-level-store' }
  )
);
