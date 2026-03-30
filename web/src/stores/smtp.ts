import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { smtpService } from '@/services/smtpService';
import type { SmtpConfigResponse } from '@/services/smtpService';

import { getErrorMessage } from '@/types/common';

interface SmtpState {
  config: SmtpConfigResponse | null;
  loading: boolean;
  saving: boolean;
  testing: boolean;
  error: string | null;
  fetchConfig: (tenantId: string) => Promise<void>;
  reset: () => void;
}

const initialState = {
  config: null as SmtpConfigResponse | null,
  loading: false,
  saving: false,
  testing: false,
  error: null as string | null,
};

export const useSmtpStore = create<SmtpState>()(
  devtools(
    (set) => ({
      ...initialState,

      fetchConfig: async (tenantId: string) => {
        set({ loading: true, error: null });
        try {
          const res = await smtpService.getConfig(tenantId);
          set({ config: res, loading: false });
        } catch (err: unknown) {
          set({ error: getErrorMessage(err), loading: false });
        }
      },

      reset: () => {
        set(initialState);
      },
    }),
    { name: 'smtp-store', enabled: import.meta.env.DEV }
  )
);

export const useSmtpConfig = () => useSmtpStore((s) => s.config);
export const useSmtpLoading = () => useSmtpStore((s) => s.loading);
export const useSmtpActions = () =>
  useSmtpStore(useShallow((s) => ({ fetchConfig: s.fetchConfig, reset: s.reset })));
