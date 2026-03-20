import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import { traceAPI } from '../services/traceService';

import type { ListRunsParams } from '../services/traceService';
import type { UnknownError } from '../types/common';
import type {
  SubAgentRunDTO,
  SubAgentRunListDTO,
  TraceChainDTO,
  DescendantTreeDTO,
  ActiveRunCountDTO,
} from '../types/multiAgent';

function getErrorMessage(error: unknown, fallback: string): string {
  const err = error as UnknownError;
  if (err.response?.data?.detail) {
    const detail = err.response.data.detail;
    return typeof detail === 'string' ? detail : JSON.stringify(detail);
  }
  if (err.message) {
    return err.message;
  }
  return fallback;
}

// ---------------------------------------------------------------------------
// STATE INTERFACE
// ---------------------------------------------------------------------------

interface TraceState {
  // Data
  runs: SubAgentRunDTO[];
  currentRun: SubAgentRunDTO | null;
  traceChain: TraceChainDTO | null;
  descendants: DescendantTreeDTO | null;
  activeRunCount: number;
  total: number;

  // Current context
  conversationId: string | null;

  // Loading states
  isLoading: boolean;
  isChainLoading: boolean;
  isDescendantsLoading: boolean;

  // Error state
  error: string | null;

  // Actions - Run queries
  listRuns: (conversationId: string, params?: ListRunsParams) => Promise<void>;
  getRun: (conversationId: string, runId: string) => Promise<SubAgentRunDTO>;
  getTraceChain: (conversationId: string, traceId: string) => Promise<void>;
  getDescendants: (conversationId: string, runId: string) => Promise<void>;
  fetchActiveRunCount: (conversationId?: string) => Promise<void>;

  // Actions - Selection
  setCurrentRun: (run: SubAgentRunDTO | null) => void;
  setConversationId: (conversationId: string | null) => void;

  // Actions - Utility
  clearError: () => void;
  reset: () => void;
}

// ---------------------------------------------------------------------------
// INITIAL STATE
// ---------------------------------------------------------------------------

const initialState = {
  runs: [],
  currentRun: null,
  traceChain: null,
  descendants: null,
  activeRunCount: 0,
  total: 0,
  conversationId: null,
  isLoading: false,
  isChainLoading: false,
  isDescendantsLoading: false,
  error: null,
};

// ---------------------------------------------------------------------------
// STORE CREATION
// ---------------------------------------------------------------------------

export const useTraceStore = create<TraceState>()(
  devtools(
    (set) => ({
      ...initialState,

      // ========== Run queries ==========

      listRuns: async (conversationId: string, params?: ListRunsParams) => {
        set({ isLoading: true, error: null, conversationId });
        try {
          const response: SubAgentRunListDTO = await traceAPI.listRuns(
            conversationId,
            params,
          );
          set({
            runs: response.runs,
            total: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to list runs');
          set({ error: msg, isLoading: false });
          throw error;
        }
      },

      getRun: async (conversationId: string, runId: string) => {
        set({ isLoading: true, error: null });
        try {
          const run: SubAgentRunDTO = await traceAPI.getRun(conversationId, runId);
          set({ currentRun: run, isLoading: false });
          return run;
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to get run');
          set({ error: msg, isLoading: false });
          throw error;
        }
      },

      getTraceChain: async (conversationId: string, traceId: string) => {
        set({ isChainLoading: true, error: null });
        try {
          const chain: TraceChainDTO = await traceAPI.getTraceChain(
            conversationId,
            traceId,
          );
          set({ traceChain: chain, isChainLoading: false });
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to get trace chain');
          set({ error: msg, isChainLoading: false });
          throw error;
        }
      },

      getDescendants: async (conversationId: string, runId: string) => {
        set({ isDescendantsLoading: true, error: null });
        try {
          const tree: DescendantTreeDTO = await traceAPI.getDescendants(
            conversationId,
            runId,
          );
          set({ descendants: tree, isDescendantsLoading: false });
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to get descendants');
          set({ error: msg, isDescendantsLoading: false });
          throw error;
        }
      },

      fetchActiveRunCount: async (conversationId?: string) => {
        try {
          const response: ActiveRunCountDTO =
            await traceAPI.getActiveRunCount(conversationId);
          set({ activeRunCount: response.active_count });
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to fetch active run count');
          set({ error: msg });
          throw error;
        }
      },

      // ========== Selection ==========

      setCurrentRun: (run: SubAgentRunDTO | null) => {
        set({ currentRun: run });
      },

      setConversationId: (conversationId: string | null) => {
        set({ conversationId });
      },

      // ========== Utility ==========

      clearError: () => {
        set({ error: null });
      },

      reset: () => {
        set(initialState);
      },
    }),
    {
      name: 'TraceStore',
      enabled: import.meta.env.DEV,
    },
  ),
);

// ---------------------------------------------------------------------------
// SELECTORS - Fine-grained subscriptions for performance
// ---------------------------------------------------------------------------

// Data selectors
export const useTraceRuns = () => useTraceStore((state) => state.runs);
export const useCurrentTraceRun = () => useTraceStore((state) => state.currentRun);
export const useTraceChain = () => useTraceStore((state) => state.traceChain);
export const useTraceDescendants = () => useTraceStore((state) => state.descendants);
export const useActiveRunCount = () => useTraceStore((state) => state.activeRunCount);
export const useTraceTotal = () => useTraceStore((state) => state.total);
export const useTraceConversationId = () =>
  useTraceStore((state) => state.conversationId);

// Loading selectors
export const useTraceLoading = () => useTraceStore((state) => state.isLoading);
export const useTraceChainLoading = () => useTraceStore((state) => state.isChainLoading);
export const useTraceDescendantsLoading = () =>
  useTraceStore((state) => state.isDescendantsLoading);

// Error selector
export const useTraceError = () => useTraceStore((state) => state.error);

// Action selectors - each returns a stable function reference
export const useListTraceRuns = () => useTraceStore((state) => state.listRuns);
export const useGetTraceRun = () => useTraceStore((state) => state.getRun);
export const useGetTraceChain = () => useTraceStore((state) => state.getTraceChain);
export const useGetTraceDescendants = () =>
  useTraceStore((state) => state.getDescendants);
export const useFetchActiveRunCount = () =>
  useTraceStore((state) => state.fetchActiveRunCount);
export const useSetCurrentTraceRun = () =>
  useTraceStore((state) => state.setCurrentRun);
export const useSetTraceConversationId = () =>
  useTraceStore((state) => state.setConversationId);
export const useClearTraceError = () => useTraceStore((state) => state.clearError);
export const useResetTraceStore = () => useTraceStore((state) => state.reset);

// Computed selectors
export const useRunsByTraceId = () =>
  useTraceStore((state) => {
    const grouped = new Map<string, SubAgentRunDTO[]>();
    for (const run of state.runs) {
      const key = run.trace_id ?? 'no-trace';
      const list = grouped.get(key);
      if (list) {
        list.push(run);
      } else {
        grouped.set(key, [run]);
      }
    }
    return grouped;
  });

export const useRunningRunsCount = () =>
  useTraceStore(
    (state) => state.runs.filter((r) => r.status === 'running').length,
  );
