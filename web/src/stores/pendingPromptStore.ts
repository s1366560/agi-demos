/**
 * pendingPromptStore — frontend-only "compose ahead" queue.
 *
 * While the agent is streaming a response, the user can keep typing. Each
 * queued prompt is held here, scoped per conversation, and auto-dispatched
 * one-at-a-time once the stream completes (`isStreaming` → false).
 *
 * Distilled from Routa's HomeInput pending-prompt mode but trimmed:
 *   - text + optional skill / subagent override only (no file attachments
 *     in v1; uploads should happen at send-time, not in the queue)
 *   - immutable updates throughout
 */

import { create } from 'zustand';

export interface PendingPrompt {
  id: string;
  text: string;
  skillName?: string | undefined;
  subAgentName?: string | undefined;
  createdAt: number;
}

interface PendingPromptState {
  queues: Map<string, readonly PendingPrompt[]>;
  enqueue: (
    conversationId: string,
    prompt: Omit<PendingPrompt, 'id' | 'createdAt'>
  ) => PendingPrompt;
  remove: (conversationId: string, id: string) => void;
  shift: (conversationId: string) => PendingPrompt | undefined;
  clear: (conversationId: string) => void;
}

let counter = 0;
function nextId(): string {
  counter += 1;
  return `pp_${String(Date.now())}_${String(counter)}`;
}

export const usePendingPromptStore = create<PendingPromptState>((set, get) => ({
  queues: new Map(),
  enqueue: (conversationId, prompt) => {
    const entry: PendingPrompt = {
      id: nextId(),
      createdAt: Date.now(),
      text: prompt.text,
      skillName: prompt.skillName,
      subAgentName: prompt.subAgentName,
    };
    set((state) => {
      const queues = new Map(state.queues);
      const current = queues.get(conversationId) ?? [];
      queues.set(conversationId, [...current, entry]);
      return { queues };
    });
    return entry;
  },
  remove: (conversationId, id) => {
    set((state) => {
      const current = state.queues.get(conversationId);
      if (!current) return state;
      const filtered = current.filter((p) => p.id !== id);
      const queues = new Map(state.queues);
      if (filtered.length === 0) queues.delete(conversationId);
      else queues.set(conversationId, filtered);
      return { queues };
    });
  },
  shift: (conversationId) => {
    const current = get().queues.get(conversationId);
    if (!current || current.length === 0) return undefined;
    const [head, ...rest] = current;
    set((state) => {
      const queues = new Map(state.queues);
      if (rest.length === 0) queues.delete(conversationId);
      else queues.set(conversationId, rest);
      return { queues };
    });
    return head;
  },
  clear: (conversationId) => {
    set((state) => {
      if (!state.queues.has(conversationId)) return state;
      const queues = new Map(state.queues);
      queues.delete(conversationId);
      return { queues };
    });
  },
}));

/** Selector hook: returns the queue for a given conversation (stable empty array). */
const EMPTY: readonly PendingPrompt[] = Object.freeze([]);
export function usePendingPrompts(conversationId: string | undefined): readonly PendingPrompt[] {
  return usePendingPromptStore((state) =>
    conversationId ? (state.queues.get(conversationId) ?? EMPTY) : EMPTY
  );
}
