import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import {
  ApprovalResolveRequest,
  DecisionRecord,
  TrustPolicy,
  TrustPolicyCreate,
  trustService,
} from '../services/trustService';

// Inline error message helper matching the audit store pattern
function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export interface TrustState {
  policies: TrustPolicy[];
  decisions: DecisionRecord[];
  isLoading: boolean;
  error: string | null;

  fetchPolicies: (
    tenantId: string,
    params: { workspace_id: string; agent_instance_id?: string }
  ) => Promise<void>;
  fetchDecisions: (
    tenantId: string,
    params: { workspace_id: string; agent_id?: string; decision_type?: string }
  ) => Promise<void>;
  createPolicy: (tenantId: string, data: TrustPolicyCreate) => Promise<void>;
  resolveApproval: (
    tenantId: string,
    recordId: string,
    data: ApprovalResolveRequest
  ) => Promise<void>;
  clearError: () => void;
  reset: () => void;
}

const initialState = {
  policies: [],
  decisions: [],
  isLoading: false,
  error: null,
};

export const useTrustStore = create<TrustState>()(
  devtools(
    (set) => ({
      ...initialState,

      fetchPolicies: async (tenantId, params) => {
        set({ isLoading: true, error: null });
        try {
          const response = await trustService.listPolicies(tenantId, params);
          set({ policies: response.items, isLoading: false });
        } catch (error) {
          set({ error: getErrorMessage(error), isLoading: false });
        }
      },

      fetchDecisions: async (tenantId, params) => {
        set({ isLoading: true, error: null });
        try {
          const response = await trustService.listDecisions(tenantId, params);
          set({ decisions: response.items, isLoading: false });
        } catch (error) {
          set({ error: getErrorMessage(error), isLoading: false });
        }
      },

      createPolicy: async (tenantId, data) => {
        set({ isLoading: true, error: null });
        try {
          await trustService.createPolicy(tenantId, data);
          // Auto refresh policies list after creation
          const response = await trustService.listPolicies(tenantId, {
            workspace_id: data.workspace_id,
          });
          set({ policies: response.items, isLoading: false });
        } catch (error) {
          set({ error: getErrorMessage(error), isLoading: false });
          throw error;
        }
      },

      resolveApproval: async (tenantId, recordId, data) => {
        set({ isLoading: true, error: null });
        try {
          await trustService.resolveApproval(tenantId, recordId, data);
          set({ isLoading: false });
        } catch (error) {
          set({ error: getErrorMessage(error), isLoading: false });
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
    { name: 'TrustStore', enabled: import.meta.env.DEV }
  )
);

export const useTrustPolicies = () => useTrustStore((s) => s.policies);
export const useTrustDecisions = () => useTrustStore((s) => s.decisions);
export const useTrustLoading = () => useTrustStore((s) => s.isLoading);
export const useTrustError = () => useTrustStore((s) => s.error);
export const useTrustActions = () =>
  useTrustStore(
    useShallow((s) => ({
      fetchPolicies: s.fetchPolicies,
      fetchDecisions: s.fetchDecisions,
      createPolicy: s.createPolicy,
      resolveApproval: s.resolveApproval,
      clearError: s.clearError,
      reset: s.reset,
    }))
  );
