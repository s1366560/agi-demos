/**
 * Zustand store for tracking background SubAgent executions.
 * Updated reactively via SSE events (background_launched, subagent_completed/failed).
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

export interface BackgroundSubAgent {
  executionId: string;
  subagentName: string;
  task: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  startedAt: number;
  completedAt?: number | undefined;
  summary?: string | undefined;
  error?: string | undefined;
  tokensUsed?: number | undefined;
  executionTimeMs?: number | undefined;
}

interface BackgroundState {
  executions: Map<string, BackgroundSubAgent>;
  panelOpen: boolean;

  // Actions
  launch: (executionId: string, subagentName: string, task: string) => void;
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
}

export const useBackgroundStore = create<BackgroundState>()(
  devtools(
    (set) => ({
      executions: new Map(),
      panelOpen: false,

      launch: (executionId, subagentName, task) => {
        set((state) => {
          const next = new Map(state.executions);
          next.set(executionId, {
            executionId,
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
          if (existing) {
            next.set(executionId, {
              ...existing,
              status: 'completed',
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
          if (existing) {
            next.set(executionId, {
              ...existing,
              status: 'failed',
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
          if (existing) {
            next.set(executionId, {
              ...existing,
              status: 'cancelled',
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
    }))
  );
