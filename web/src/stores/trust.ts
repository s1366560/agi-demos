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

let latestFetchPoliciesRequest = 0;
let latestFetchDecisionsRequest = 0;

function invalidateTrustReadRequests(): void {
  latestFetchPoliciesRequest += 1;
  latestFetchDecisionsRequest += 1;
}

export const useTrustStore = create<TrustState>()(
  devtools(
    (set) => ({
      ...initialState,

      fetchPolicies: async (tenantId, params) => {
        const requestId = latestFetchPoliciesRequest + 1;
        latestFetchPoliciesRequest = requestId;
        set({ isLoading: true, error: null });
        try {
          const response = await trustService.listPolicies(tenantId, params);
          if (requestId !== latestFetchPoliciesRequest) return;
          set({ policies: response.items, isLoading: false });
        } catch (error) {
          if (requestId !== latestFetchPoliciesRequest) return;
          set({ error: getErrorMessage(error), isLoading: false });
          throw error;
        }
      },

      fetchDecisions: async (tenantId, params) => {
        const requestId = latestFetchDecisionsRequest + 1;
        latestFetchDecisionsRequest = requestId;
        set({ isLoading: true, error: null });
        try {
          const response = await trustService.listDecisions(tenantId, params);
          if (requestId !== latestFetchDecisionsRequest) return;
          set({ decisions: response.items, isLoading: false });
        } catch (error) {
          if (requestId !== latestFetchDecisionsRequest) return;
          set({ error: getErrorMessage(error), isLoading: false });
          throw error;
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
        invalidateTrustReadRequests();
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
