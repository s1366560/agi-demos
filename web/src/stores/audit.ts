import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { auditService } from '../services/auditService';

import type { AuditEntry, AuditListParams } from '../services/auditService';

interface UnknownError {
  response?: { data?: { detail?: string | Record<string, unknown> } };
  message?: string;
}

function getErrorMessage(error: unknown, fallback: string): string {
  const err = error as UnknownError;
  if (err.response?.data?.detail) {
    const detail = err.response.data.detail;
    return typeof detail === 'string' ? detail : JSON.stringify(detail);
  }
  if (err.message) return err.message;
  return fallback;
}

interface AuditState {
  logs: AuditEntry[];
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  error: string | null;

  fetchLogs: (tenantId: string, params?: AuditListParams) => Promise<void>;
  exportLogs: (tenantId: string, format: 'csv' | 'json', params?: AuditListParams) => Promise<void>;
  clearError: () => void;
  reset: () => void;
}

const initialState = {
  logs: [] as AuditEntry[],
  total: 0,
  page: 1,
  pageSize: 20,
  isLoading: false,
  error: null as string | null,
};

export const useAuditStore = create<AuditState>()(
  devtools(
    (set) => ({
      ...initialState,

      fetchLogs: async (tenantId: string, params?: AuditListParams) => {
        set({ isLoading: true, error: null });
        try {
          const response = await auditService.list(tenantId, params);
          set({
            logs: response.items,
            total: response.total,
            page: response.page,
            pageSize: response.page_size,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to fetch audit logs'), isLoading: false });
          throw error;
        }
      },

      exportLogs: async (tenantId: string, format: 'csv' | 'json', params?: AuditListParams) => {
        try {
          const blob = await auditService.exportLogs(tenantId, format, params);
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `audit-logs.${format}`;
          document.body.appendChild(a);
          a.click();
          window.URL.revokeObjectURL(url);
          document.body.removeChild(a);
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to export audit logs') });
          throw error;
        }
      },

      clearError: () => {
        set({ error: null });
      },
      reset: () => {
        set(initialState);
      },
    }),
    {
      name: 'AuditStore',
      enabled: import.meta.env.DEV,
    }
  )
);

export const useAuditLogs = () => useAuditStore((s) => s.logs);
export const useAuditTotal = () => useAuditStore((s) => s.total);
export const useAuditLoading = () => useAuditStore((s) => s.isLoading);
export const useAuditError = () => useAuditStore((s) => s.error);

export const useAuditActions = () =>
  useAuditStore(
    useShallow((s) => ({
      fetchLogs: s.fetchLogs,
      exportLogs: s.exportLogs,
      clearError: s.clearError,
      reset: s.reset,
    }))
  );
