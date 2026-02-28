import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { agentService } from '@/services/agentService';

/**
 * Token distribution by message category
 */
export interface TokenDistribution {
  system: number;
  user: number;
  assistant: number;
  tool: number;
  summary: number;
}

/**
 * Individual compression event record
 */
export interface CompressionRecord {
  timestamp: string;
  level: string;
  tokens_before: number;
  tokens_after: number;
  tokens_saved: number;
  compression_ratio: number;
  savings_pct: number;
  messages_before: number;
  messages_after: number;
  duration_ms: number;
}

/**
 * Compression history summary from backend
 */
export interface CompressionHistorySummary {
  total_compressions: number;
  total_tokens_saved: number;
  average_compression_ratio: number;
  average_savings_pct: number;
  recent_records: CompressionRecord[];
}

/**
 * Context status data (from context_status SSE event)
 */
export interface ContextStatus {
  currentTokens: number;
  tokenBudget: number;
  occupancyPct: number;
  compressionLevel: string;
  tokenDistribution: TokenDistribution;
  compressionHistory: CompressionHistorySummary;
  fromCache: boolean;
  messagesInSummary: number;
}

interface ContextState {
  // Current context status
  status: ContextStatus | null;

  // Whether the detail panel is expanded
  detailExpanded: boolean;

  // Actions
  handleContextStatus: (data: Record<string, unknown>) => void;
  handleContextCompressed: (data: Record<string, unknown>) => void;
  handleCostUpdate: (data: Record<string, unknown>) => void;
  fetchContextStatus: (conversationId: string, projectId: string) => Promise<void>;
  setDetailExpanded: (expanded: boolean) => void;
  reset: () => void;
}

const defaultStatus: ContextStatus = {
  currentTokens: 0,
  tokenBudget: 128000,
  occupancyPct: 0,
  compressionLevel: 'none',
  tokenDistribution: { system: 0, user: 0, assistant: 0, tool: 0, summary: 0 },
  compressionHistory: {
    total_compressions: 0,
    total_tokens_saved: 0,
    average_compression_ratio: 0,
    average_savings_pct: 0,
    recent_records: [],
  },
  fromCache: false,
  messagesInSummary: 0,
};

export const useContextStore = create<ContextState>()(
  devtools(
    (set, get) => ({
      status: null,
      detailExpanded: false,

      handleContextStatus: (data) => {
        const prevHistory = get().status?.compressionHistory ?? defaultStatus.compressionHistory;
        const incomingHistory = data.compression_history_summary as
          | CompressionHistorySummary
          | undefined;
        const hasHistory = incomingHistory && (incomingHistory.total_compressions ?? 0) > 0;
        const status: ContextStatus = {
          currentTokens: (data.current_tokens as number) ?? 0,
          tokenBudget: (data.token_budget as number) ?? 128000,
          occupancyPct: (data.occupancy_pct as number) ?? 0,
          compressionLevel: (data.compression_level as string) ?? 'none',
          tokenDistribution:
            (data.token_distribution as TokenDistribution) ?? defaultStatus.tokenDistribution,
          compressionHistory: hasHistory ? incomingHistory : prevHistory,
          fromCache: (data.from_cache as boolean) ?? false,
          messagesInSummary: (data.messages_in_summary as number) ?? 0,
        };
        set({ status });
      },

      handleContextCompressed: (data) => {
        const prev = get().status ?? { ...defaultStatus };
        const incomingHistory = data.compression_history_summary as
          | CompressionHistorySummary
          | undefined;
        const hasHistory = incomingHistory && (incomingHistory.total_compressions ?? 0) > 0;

        set({
          status: {
            ...prev,
            currentTokens: (data.estimated_tokens as number) ?? prev.currentTokens,
            tokenBudget: (data.token_budget as number) ?? prev.tokenBudget,
            occupancyPct: (data.budget_utilization_pct as number) ?? prev.occupancyPct,
            compressionLevel: (data.compression_level as string) ?? prev.compressionLevel,
            tokenDistribution:
              (data.token_distribution as TokenDistribution) ?? prev.tokenDistribution,
            compressionHistory: hasHistory ? incomingHistory : prev.compressionHistory,
          },
        });
      },

      handleCostUpdate: (data) => {
        const prev = get().status ?? { ...defaultStatus };
        const totalTokens =
          ((data.input_tokens as number) ?? 0) + ((data.output_tokens as number) ?? 0);
        set({
          status: {
            ...prev,
            currentTokens: totalTokens > 0 ? totalTokens : prev.currentTokens,
          },
        });
      },

      fetchContextStatus: async (conversationId, projectId) => {
        const data = await agentService.getContextStatus(conversationId, projectId);
        if (!data) return;

        const prev = get().status;
        set({
          status: {
            ...(prev ?? { ...defaultStatus }),
            compressionLevel: data.compression_level,
            fromCache: data.from_cache,
            messagesInSummary: data.messages_in_summary,
            // Preserve live token data if we have it, otherwise use summary tokens
            currentTokens: prev?.currentTokens ?? data.summary_tokens,
          },
        });
      },

      setDetailExpanded: (expanded) => {
        set({ detailExpanded: expanded });
      },

      reset: () => {
        set({ status: null, detailExpanded: false });
      },
    }),
    { name: 'context-store' }
  )
);

// Selectors - single values
export const useContextStatus = () => useContextStore((state) => state.status);
export const useContextDetailExpanded = () => useContextStore((state) => state.detailExpanded);

// Action selectors - use useShallow for object returns
export const useContextActions = () =>
  useContextStore(
    useShallow((state) => ({
      handleContextStatus: state.handleContextStatus,
      handleContextCompressed: state.handleContextCompressed,
      handleCostUpdate: state.handleCostUpdate,
      fetchContextStatus: state.fetchContextStatus,
      setDetailExpanded: state.setDetailExpanded,
      reset: state.reset,
    }))
  );
