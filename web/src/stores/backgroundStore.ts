/**
 * Zustand store for tracking background SubAgent executions.
 * Updated reactively via SSE events (background_launched, subagent_completed/failed).
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { subagentAPI } from '../services/subagentService';

export interface BackgroundSubAgent {
  executionId: string;
  conversationId: string;
  cancellation?: { status: 'pending' | 'failed'; error?: string } | undefined;
  subagentName: string;
  task: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled' | 'queued' | 'retrying' | 'killed';
  startedAt: number;
  completedAt?: number | undefined;
  summary?: string | undefined;
  error?: string | undefined;
  tokensUsed?: number | undefined;
  executionTimeMs?: number | undefined;
  progress?: number | undefined;
  progressMessage?: string | undefined;
  killReason?: string | undefined;
}

interface BackgroundState {
  executions: Map<string, BackgroundSubAgent>;
  panelOpen: boolean;

  // Actions
  launch: (executionId: string, subagentName: string, task: string, conversationId: string) => void;
  complete: (
    executionId: string,
    summary: string,
    tokensUsed?: number,
    executionTimeMs?: number
  ) => void;
  fail: (executionId: string, error: string) => void;
  cancel: (executionId: string) => void;
  clear: (executionId: string) => void;
  clearAll: () => void;
  togglePanel: () => void;
  setPanel: (open: boolean) => void;
  updateProgress: (executionId: string, progress: number, message?: string) => void;
  kill: (executionId: string, reason?: string) => Promise<void>;
}

export const useBackgroundStore = create<BackgroundState>()(
  devtools(
    (set, get) => ({
      executions: new Map(),
      panelOpen: false,

      launch: (executionId, subagentName, task, conversationId) => {
        if (!executionId || !conversationId) return;
        if (get().executions.has(executionId)) return;
        set((state) => {
          const next = new Map(state.executions);
          next.set(executionId, {
            executionId,
            conversationId,
            subagentName,
            task,
            status: 'running',
            startedAt: Date.now(),
          });
          return { executions: next };
        });
      },

      complete: (executionId, summary, tokensUsed, executionTimeMs) => {
        set((state) => {
          const next = new Map(state.executions);
          const existing = next.get(executionId);
          if (existing && ['running', 'queued', 'retrying'].includes(existing.status)) {
            next.set(executionId, {
              ...existing,
              status: 'completed',
              cancellation: undefined,
              completedAt: Date.now(),
              summary,
              tokensUsed,
              executionTimeMs,
            });
          }
          return { executions: next };
        });
      },

      fail: (executionId, error) => {
        set((state) => {
          const next = new Map(state.executions);
          const existing = next.get(executionId);
          if (existing && ['running', 'queued', 'retrying'].includes(existing.status)) {
            next.set(executionId, {
              ...existing,
              status: 'failed',
              cancellation: undefined,
              completedAt: Date.now(),
              error,
            });
          }
          return { executions: next };
        });
      },

      cancel: (executionId) => {
        set((state) => {
          const next = new Map(state.executions);
          const existing = next.get(executionId);
          if (existing && ['running', 'queued', 'retrying'].includes(existing.status)) {
            next.set(executionId, {
              ...existing,
              status: 'cancelled',
              cancellation: undefined,
              completedAt: Date.now(),
            });
          }
          return { executions: next };
        });
      },

      clear: (executionId) => {
        set((state) => {
          const next = new Map(state.executions);
          next.delete(executionId);
          return { executions: next };
        });
      },

      clearAll: () => {
        set({ executions: new Map() });
      },

      togglePanel: () => {
        set((state) => ({ panelOpen: !state.panelOpen }));
      },

      setPanel: (open) => {
        set({ panelOpen: open });
      },

      updateProgress: (executionId, progress, message) => {
        set((state) => {
          const next = new Map(state.executions);
          const existing = next.get(executionId);
          if (existing) {
            next.set(executionId, {
              ...existing,
              progress,
              progressMessage: message,
            });
          }
          return { executions: next };
        });
      },

      kill: async (executionId, reason) => {
        const execution = get().executions.get(executionId);
        if (
          !execution ||
          !['running', 'queued', 'retrying'].includes(execution.status) ||
          execution.cancellation?.status === 'pending'
        )
          return;
        const request = { status: 'pending' as const };
        set((state) => ({
          executions: new Map(state.executions).set(executionId, {
            ...execution,
            cancellation: request,
            killReason: reason,
          }),
        }));
        const updateRequest = (
          cancellation: BackgroundSubAgent['cancellation'],
          cancelled = false
        ) => {
          set((state) => {
            const current = state.executions.get(executionId);
            if (!current || current.cancellation !== request) return state;
            return {
              executions: new Map(state.executions).set(executionId, {
                ...current,
                cancellation,
                ...(cancelled ? { status: 'cancelled' as const, completedAt: Date.now() } : {}),
              }),
            };
          });
        };
        if (!execution.conversationId) {
          updateRequest({ status: 'failed' });
          return;
        }
        try {
          const response = await subagentAPI.cancelExecution(
            executionId,
            execution.conversationId,
            reason
          );
          if (response.execution_id !== executionId) {
            updateRequest({ status: 'failed' });
            // Runtime receipt must contain a boolean, not a truthy malformed payload.
            // eslint-disable-next-line @typescript-eslint/no-unnecessary-boolean-literal-compare
          } else if (response.cancelled === true) {
            updateRequest(undefined, true);
          } else if (response.cancel_requested !== true) {
            updateRequest({ status: 'failed', error: response.message });
          }
        } catch (error) {
          updateRequest({
            status: 'failed',
            ...(error instanceof Error ? { error: error.message } : {}),
          });
        }
      },
    }),
    { name: 'background-store' }
  )
);

// Selectors
export const useBackgroundExecutions = () =>
  useBackgroundStore(useShallow((state) => Array.from(state.executions.values())));

export const useRunningCount = () =>
  useBackgroundStore(
    (state) => Array.from(state.executions.values()).filter((e) => e.status === 'running').length
  );

export const useBackgroundPanel = () => useBackgroundStore((state) => state.panelOpen);
export const useBackgroundKill = () => useBackgroundStore((state) => state.kill);

export const useBackgroundActions = () =>
  useBackgroundStore(
    useShallow((state) => ({
      launch: state.launch,
      complete: state.complete,
      fail: state.fail,
      cancel: state.cancel,
      clear: state.clear,
      clearAll: state.clearAll,
      togglePanel: state.togglePanel,
      setPanel: state.setPanel,
      updateProgress: state.updateProgress,
      kill: state.kill,
    }))
  );
