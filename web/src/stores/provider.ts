import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { providerAPI } from '@/services/api';

import { getErrorMessage } from '@/types/common';
import type {
  ProviderConfig,
  ProviderCreate,
  ProviderUpdate,
  ModelCatalogEntry,
} from '@/types/memory';

interface ProviderState {
  // State
  providers: ProviderConfig[];
  loading: boolean;
  error: string | null;
  selectedProvider: ProviderConfig | null;
  modelCatalog: ModelCatalogEntry[];
  catalogLoading: boolean;
  modelSearchQuery: string;
  modelSearchResults: ModelCatalogEntry[];

  // Actions
  fetchProviders: () => Promise<void>;
  createProvider: (data: ProviderCreate) => Promise<ProviderConfig>;
  updateProvider: (id: string, data: ProviderUpdate) => Promise<ProviderConfig>;
  deleteProvider: (id: string) => Promise<void>;
  setSelectedProvider: (provider: ProviderConfig | null) => void;
  fetchModelCatalog: (provider?: string) => Promise<void>;
  searchModels: (query: string) => void;
  testConnection: (id: string) => Promise<boolean>;
  reset: () => void;
}

export const useProviderStore = create<ProviderState>()(
  devtools(
    (set, get) => ({
      providers: [],
      loading: false,
      error: null,
      selectedProvider: null,
      modelCatalog: [],
      catalogLoading: false,
      modelSearchQuery: '',
      modelSearchResults: [],

      fetchProviders: async () => {
        set({ loading: true, error: null });
        try {
          const providers = await providerAPI.list({ include_inactive: true });
          set({ providers, loading: false });
        } catch (err) {
          set({ error: getErrorMessage(err), loading: false });
        }
      },

      createProvider: async (data: ProviderCreate) => {
        set({ loading: true, error: null });
        try {
          const newProvider = await providerAPI.create(data);
          const currentProviders = get().providers;
          set({
            providers: [...currentProviders, newProvider],
            loading: false,
          });
          return newProvider;
        } catch (err) {
          const errorMsg = getErrorMessage(err);
          set({ error: errorMsg, loading: false });
          throw new Error(errorMsg);
        }
      },

      updateProvider: async (id: string, data: ProviderUpdate) => {
        set({ loading: true, error: null });
        try {
          const updatedProvider = await providerAPI.update(id, data);
          const currentProviders = get().providers;
          set({
            providers: currentProviders.map((p) => (p.id === id ? updatedProvider : p)),
            loading: false,
          });
          return updatedProvider;
        } catch (err) {
          const errorMsg = getErrorMessage(err);
          set({ error: errorMsg, loading: false });
          throw new Error(errorMsg);
        }
      },

      deleteProvider: async (id: string) => {
        set({ loading: true, error: null });
        try {
          await providerAPI.delete(id);
          const currentProviders = get().providers;
          set({
            providers: currentProviders.filter((p) => p.id !== id),
            loading: false,
          });
        } catch (err) {
          const errorMsg = getErrorMessage(err);
          set({ error: errorMsg, loading: false });
          throw new Error(errorMsg);
        }
      },

      setSelectedProvider: (provider) => {
        set({ selectedProvider: provider });
      },

      fetchModelCatalog: async (provider?: string) => {
        set({ catalogLoading: true, error: null });
        try {
          const response = await providerAPI.getModelCatalog(provider);
          const catalog = response.models ?? [];
          set({
            modelCatalog: catalog,
            modelSearchResults: catalog,
            catalogLoading: false,
          });
        } catch (err) {
          set({
            error: getErrorMessage(err),
            catalogLoading: false,
            modelSearchResults: [],
            modelCatalog: [],
          });
        }
      },

      searchModels: (query: string) => {
        const { modelCatalog } = get();
        const lowerQuery = query.toLowerCase().trim();

        if (!lowerQuery) {
          set({
            modelSearchQuery: query,
            modelSearchResults: Array.isArray(modelCatalog) ? modelCatalog : [],
          });
          return;
        }

        // Simple client-side fuzzy matching
        const results = (Array.isArray(modelCatalog) ? modelCatalog : []).filter((model) => {
          // Exact substring match
          if (model.name.toLowerCase().includes(lowerQuery)) return true;
          if (model.provider?.toLowerCase().includes(lowerQuery)) return true;

          // Split words match (all words must be present in name or provider)
          const words = lowerQuery.split(/\s+/);
          return words.every(
            (word) =>
              model.name.toLowerCase().includes(word) ||
              model.provider?.toLowerCase().includes(word)
          );
        });

        set({
          modelSearchQuery: query,
          modelSearchResults: results,
        });
      },

      testConnection: async (id: string) => {
        set({ loading: true, error: null });
        try {
          await providerAPI.checkHealth(id);
          set({ loading: false });
          return true;
        } catch (err) {
          set({ error: getErrorMessage(err), loading: false });
          return false;
        }
      },

      reset: () => {
        set({
          providers: [],
          loading: false,
          error: null,
          selectedProvider: null,
          modelCatalog: [],
          catalogLoading: false,
          modelSearchQuery: '',
          modelSearchResults: [],
        });
      },
    }),
    { name: 'provider-store' }
  )
);

// Single value selectors
export const useProviders = () => useProviderStore((s) => s.providers);
export const useProviderLoading = () => useProviderStore((s) => s.loading);
export const useProviderError = () => useProviderStore((s) => s.error);
export const useSelectedProvider = () => useProviderStore((s) => s.selectedProvider);
export const useModelCatalog = () => useProviderStore((s) => s.modelCatalog);
export const useModelSearchResults = () => useProviderStore((s) => s.modelSearchResults);

// Object selectors (MUST use useShallow)
export const useProviderActions = () =>
  useProviderStore(
    useShallow((s) => ({
      fetchProviders: s.fetchProviders,
      createProvider: s.createProvider,
      updateProvider: s.updateProvider,
      deleteProvider: s.deleteProvider,
      setSelectedProvider: s.setSelectedProvider,
      fetchModelCatalog: s.fetchModelCatalog,
      searchModels: s.searchModels,
      testConnection: s.testConnection,
      reset: s.reset,
    }))
  );
