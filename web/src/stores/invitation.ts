import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { invitationService } from '../services/invitationService';

import type { CreateInvitationParams, Invitation } from '../services/invitationService';

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

interface InvitationState {
  invitations: Invitation[];
  total: number;
  pendingCount: number;
  isLoading: boolean;
  error: string | null;

  fetchPending: (tenantId: string) => Promise<void>;
  createInvitation: (tenantId: string, params: CreateInvitationParams) => Promise<Invitation>;
  cancelInvitation: (tenantId: string, invitationId: string) => Promise<void>;
  reset: () => void;
}

const initialState = {
  invitations: [] as Invitation[],
  total: 0,
  pendingCount: 0,
  isLoading: false,
  error: null as string | null,
};

export const useInvitationStore = create<InvitationState>()(
  devtools(
    (set) => ({
      ...initialState,

      fetchPending: async (tenantId: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await invitationService.listPending(tenantId);
          set({
            invitations: response.items,
            total: response.total,
            pendingCount: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to fetch invitations'),
            isLoading: false,
          });
        }
      },

      createInvitation: async (tenantId: string, params: CreateInvitationParams) => {
        set({ error: null });
        try {
          const invitation = await invitationService.create(tenantId, params);
          set((state) => ({
            invitations: [invitation, ...state.invitations],
            total: state.total + 1,
            pendingCount: state.pendingCount + 1,
          }));
          return invitation;
        } catch (error: unknown) {
          const message = getErrorMessage(error, 'Failed to create invitation');
          set({ error: message });
          throw error;
        }
      },

      cancelInvitation: async (tenantId: string, invitationId: string) => {
        set({ error: null });
        try {
          await invitationService.cancel(tenantId, invitationId);
          set((state) => ({
            invitations: state.invitations.filter((inv) => inv.id !== invitationId),
            total: Math.max(0, state.total - 1),
            pendingCount: Math.max(0, state.pendingCount - 1),
          }));
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to cancel invitation') });
          throw error;
        }
      },

      reset: () => {
        set(initialState);
      },
    }),
    {
      name: 'InvitationStore',
      enabled: import.meta.env.DEV,
    }
  )
);

export const useInvitations = () => useInvitationStore((s) => s.invitations);
export const usePendingCount = () => useInvitationStore((s) => s.pendingCount);
export const useInvitationLoading = () => useInvitationStore((s) => s.isLoading);
export const useInvitationError = () => useInvitationStore((s) => s.error);

export const useInvitationActions = () =>
  useInvitationStore(
    useShallow((s) => ({
      fetchPending: s.fetchPending,
      createInvitation: s.createInvitation,
      cancelInvitation: s.cancelInvitation,
      reset: s.reset,
    }))
  );
