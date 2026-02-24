import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { channelService } from '@/services/channelService';

import type { ChannelConfig, CreateChannelConfig, UpdateChannelConfig } from '@/types/channel';

interface ChannelState {
  configs: ChannelConfig[];
  loading: boolean;
  error: string | null;

  // Actions
  fetchConfigs: (projectId: string) => Promise<void>;
  createConfig: (projectId: string, data: CreateChannelConfig) => Promise<void>;
  updateConfig: (configId: string, data: UpdateChannelConfig) => Promise<void>;
  deleteConfig: (configId: string) => Promise<void>;
  testConfig: (configId: string) => Promise<{ success: boolean; message: string }>;
  reset: () => void;
}

export const useChannelStore = create<ChannelState>()(
  devtools(
    (set, get) => ({
      configs: [],
      loading: false,
      error: null,

      fetchConfigs: async (projectId: string) => {
        set({ loading: true, error: null });
        try {
          const configs = await channelService.listConfigs(projectId);
          set({ configs, loading: false });
        } catch (error) {
          set({
            error: error instanceof Error ? error.message : 'Failed to fetch configs',
            loading: false,
          });
        }
      },

      createConfig: async (projectId: string, data: CreateChannelConfig) => {
        set({ loading: true });
        try {
          await channelService.createConfig(projectId, data);
          await get().fetchConfigs(projectId);
          set({ loading: false });
        } catch (error) {
          set({
            error: error instanceof Error ? error.message : 'Failed to create config',
            loading: false,
          });
          throw error;
        }
      },

      updateConfig: async (configId: string, data: UpdateChannelConfig) => {
        set({ loading: true });
        try {
          await channelService.updateConfig(configId, data);
          // Refresh configs
          const currentConfigs = get().configs;
          const config = currentConfigs.find((c) => c.id === configId);
          if (config) {
            await get().fetchConfigs(config.project_id);
          }
          set({ loading: false });
        } catch (error) {
          set({
            error: error instanceof Error ? error.message : 'Failed to update config',
            loading: false,
          });
          throw error;
        }
      },

      deleteConfig: async (configId: string) => {
        set({ loading: true });
        try {
          await channelService.deleteConfig(configId);
          set({
            configs: get().configs.filter((c) => c.id !== configId),
            loading: false,
          });
        } catch (error) {
          set({
            error: error instanceof Error ? error.message : 'Failed to delete config',
            loading: false,
          });
          throw error;
        }
      },

      testConfig: async (configId: string) => {
        const result = await channelService.testConfig(configId);
        // Refresh configs to get updated status
        const config = get().configs.find((c) => c.id === configId);
        if (config) {
          await get().fetchConfigs(config.project_id);
        }
        return result;
      },

      reset: () => { set({ configs: [], loading: false, error: null }); },
    }),
    { name: 'channel-store' }
  )
);

// Selectors - single values don't need useShallow
export const useChannelConfigs = () => useChannelStore((state) => state.configs);
export const useChannelLoading = () => useChannelStore((state) => state.loading);
export const useChannelError = () => useChannelStore((state) => state.error);

// Action selectors - MUST use useShallow for object returns
export const useChannelActions = () =>
  useChannelStore(
    useShallow((state) => ({
      fetchConfigs: state.fetchConfigs,
      createConfig: state.createConfig,
      updateConfig: state.updateConfig,
      deleteConfig: state.deleteConfig,
      testConfig: state.testConfig,
      reset: state.reset,
    }))
  );
