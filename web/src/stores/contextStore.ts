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

/**
 * Type guard to check if a value is a number
 */
function isNumber(value: unknown): value is number {
  return typeof value === 'number';
}

/**
 * Type guard to check if a value is a string
 */
function isString(value: unknown): value is string {
  return typeof value === 'string';
}

/**
 * Type guard to check if a value is a boolean
 */
function isBoolean(value: unknown): value is boolean {
  return typeof value === 'boolean';
}

/**
 * Safely extract a number from unknown data with a default value
 */
function extractNumber(value: unknown, defaultValue: number): number {
  return isNumber(value) ? value : defaultValue;
}

/**
 * Safely extract a string from unknown data with a default value
 */
function extractString(value: unknown, defaultValue: string): string {
  return isString(value) ? value : defaultValue;
}

/**
 * Safely extract a boolean from unknown data with a default value
 */
function extractBoolean(value: unknown, defaultValue: boolean): boolean {
  return isBoolean(value) ? value : defaultValue;
}

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
        const hasHistory = incomingHistory !== undefined && incomingHistory.total_compressions > 0;
        const status: ContextStatus = {
          currentTokens: extractNumber(data.current_tokens, 0),
          tokenBudget: extractNumber(data.token_budget, 128000),
          occupancyPct: extractNumber(data.occupancy_pct, 0),
          compressionLevel: extractString(data.compression_level, 'none'),
          tokenDistribution:
            (data.token_distribution as TokenDistribution | undefined) ??
            defaultStatus.tokenDistribution,
          compressionHistory: hasHistory ? incomingHistory : prevHistory,
          fromCache: extractBoolean(data.from_cache, false),
          messagesInSummary: extractNumber(data.messages_in_summary, 0),
        };
        set({ status });
      },

      handleContextCompressed: (data) => {
        const prev = get().status ?? { ...defaultStatus };
        const incomingHistory = data.compression_history_summary as
          | CompressionHistorySummary
          | undefined;
        const hasHistory = incomingHistory !== undefined && incomingHistory.total_compressions > 0;

        set({
          status: {
            ...prev,
            currentTokens: extractNumber(data.estimated_tokens, prev.currentTokens),
            tokenBudget: extractNumber(data.token_budget, prev.tokenBudget),
            occupancyPct: extractNumber(data.budget_utilization_pct, prev.occupancyPct),
            compressionLevel: extractString(data.compression_level, prev.compressionLevel),
            tokenDistribution:
              (data.token_distribution as TokenDistribution | undefined) ?? prev.tokenDistribution,
            compressionHistory: hasHistory ? incomingHistory : prev.compressionHistory,
          },
        });
      },

      handleCostUpdate: (data) => {
        const prev = get().status ?? { ...defaultStatus };
        const inputTokens = extractNumber(data.input_tokens, 0);
        const outputTokens = extractNumber(data.output_tokens, 0);
        const totalTokens = inputTokens + outputTokens;
        set({
          status: {
            ...prev,
            currentTokens: totalTokens > 0 ? totalTokens : prev.currentTokens,
          },
        });
      },

      fetchContextStatus: async (conversationId, projectId) => {
        const data = await agentService.getContextStatus(conversationId, projectId);

        const prev = get().status;
        set({
          status: {
            ...(prev ?? { ...defaultStatus }),
            compressionLevel: data.compression_level,
            fromCache: data.from_cache ?? false,
            messagesInSummary: data.messages_in_summary ?? 0,
            // Preserve live token data if we have it, otherwise use summary tokens
            currentTokens: prev?.currentTokens ?? data.summary_tokens ?? 0,
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
