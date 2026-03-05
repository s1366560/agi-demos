import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { providerAPI } from '@/services/api';

import { getErrorMessage } from '@/types/common';
import type { 
  ProviderConfig, 
  ProviderCreate, 
  ProviderUpdate, 
  ModelCatalogEntry 
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

// Temporary mock catalog for models until backend has a full catalog endpoint
const MOCK_CATALOG: ModelCatalogEntry[] = [
  { name: 'gpt-4o', provider: 'openai', context_length: 128000, max_output_tokens: 4096, input_cost_per_1m: 5, output_cost_per_1m: 15, capabilities: ['chat', 'vision'], modalities: ['text', 'image'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'gpt-4-turbo', provider: 'openai', context_length: 128000, max_output_tokens: 4096, input_cost_per_1m: 10, output_cost_per_1m: 30, capabilities: ['chat', 'vision'], modalities: ['text', 'image'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'gpt-3.5-turbo', provider: 'openai', context_length: 16385, max_output_tokens: 4096, input_cost_per_1m: 0.5, output_cost_per_1m: 1.5, capabilities: ['chat'], modalities: ['text'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'claude-3-5-sonnet-20240620', provider: 'anthropic', context_length: 200000, max_output_tokens: 8192, input_cost_per_1m: 3, output_cost_per_1m: 15, capabilities: ['chat', 'vision'], modalities: ['text', 'image'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'claude-3-opus-20240229', provider: 'anthropic', context_length: 200000, max_output_tokens: 4096, input_cost_per_1m: 15, output_cost_per_1m: 75, capabilities: ['chat', 'vision'], modalities: ['text', 'image'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'claude-3-haiku-20240307', provider: 'anthropic', context_length: 200000, max_output_tokens: 4096, input_cost_per_1m: 0.25, output_cost_per_1m: 1.25, capabilities: ['chat', 'vision'], modalities: ['text', 'image'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'gemini-1.5-pro', provider: 'gemini', context_length: 2000000, max_output_tokens: 8192, input_cost_per_1m: 3.5, output_cost_per_1m: 10.5, capabilities: ['chat', 'vision', 'audio', 'video'], modalities: ['text', 'image', 'audio', 'video'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'gemini-1.5-flash', provider: 'gemini', context_length: 1000000, max_output_tokens: 8192, input_cost_per_1m: 0.075, output_cost_per_1m: 0.3, capabilities: ['chat', 'vision', 'audio', 'video'], modalities: ['text', 'image', 'audio', 'video'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'qwen-max', provider: 'dashscope', context_length: 8192, max_output_tokens: 2000, input_cost_per_1m: 1.5, output_cost_per_1m: 4.5, capabilities: ['chat'], modalities: ['text'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'qwen-plus', provider: 'dashscope', context_length: 32000, max_output_tokens: 2000, input_cost_per_1m: 0.4, output_cost_per_1m: 1.2, capabilities: ['chat'], modalities: ['text'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'qwen-turbo', provider: 'dashscope', context_length: 8192, max_output_tokens: 2000, input_cost_per_1m: 0.2, output_cost_per_1m: 0.6, capabilities: ['chat'], modalities: ['text'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'moonshot-v1-8k', provider: 'kimi', context_length: 8192, max_output_tokens: 4096, input_cost_per_1m: 1.2, output_cost_per_1m: 1.2, capabilities: ['chat'], modalities: ['text'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'moonshot-v1-32k', provider: 'kimi', context_length: 32768, max_output_tokens: 4096, input_cost_per_1m: 2.4, output_cost_per_1m: 2.4, capabilities: ['chat'], modalities: ['text'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'moonshot-v1-128k', provider: 'kimi', context_length: 128000, max_output_tokens: 4096, input_cost_per_1m: 6.0, output_cost_per_1m: 6.0, capabilities: ['chat'], modalities: ['text'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'deepseek-chat', provider: 'deepseek', context_length: 32768, max_output_tokens: 4096, input_cost_per_1m: 0.14, output_cost_per_1m: 0.28, capabilities: ['chat'], modalities: ['text'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'deepseek-coder', provider: 'deepseek', context_length: 32768, max_output_tokens: 4096, input_cost_per_1m: 0.14, output_cost_per_1m: 0.28, capabilities: ['chat'], modalities: ['text'], variants: [], supports_streaming: true, supports_json_mode: true, is_deprecated: false },
  { name: 'text-embedding-3-small', provider: 'openai', context_length: 8191, max_output_tokens: 0, input_cost_per_1m: 0.02, output_cost_per_1m: 0, capabilities: ['embedding'], modalities: ['text'], variants: [], supports_streaming: false, supports_json_mode: false, is_deprecated: false },
  { name: 'text-embedding-3-large', provider: 'openai', context_length: 8191, max_output_tokens: 0, input_cost_per_1m: 0.13, output_cost_per_1m: 0, capabilities: ['embedding'], modalities: ['text'], variants: [], supports_streaming: false, supports_json_mode: false, is_deprecated: false },
  { name: 'text-embedding-004', provider: 'gemini', context_length: 2048, max_output_tokens: 0, input_cost_per_1m: 0.01, output_cost_per_1m: 0, capabilities: ['embedding'], modalities: ['text'], variants: [], supports_streaming: false, supports_json_mode: false, is_deprecated: false },
];

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
          const providers = await providerAPI.list();
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
            loading: false 
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
            providers: currentProviders.map(p => p.id === id ? updatedProvider : p),
            loading: false 
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
            providers: currentProviders.filter(p => p.id !== id),
            loading: false 
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
          // If we had a real backend API:
          // const catalog = await providerAPI.getModelCatalog(provider);
          
          // For now, use mock catalog and filter if provider is specified
          await new Promise(resolve => setTimeout(resolve, 300)); // Simulate network
          
          const catalog = provider 
            ? MOCK_CATALOG.filter(m => m.provider === provider)
            : MOCK_CATALOG;
            
          set({ 
            modelCatalog: catalog,
            modelSearchResults: catalog, // Initialize search results with full catalog
            catalogLoading: false 
          });
        } catch (err) {
          set({ error: getErrorMessage(err), catalogLoading: false });
        }
      },

      searchModels: (query: string) => {
        const { modelCatalog } = get();
        const lowerQuery = query.toLowerCase().trim();
        
        if (!lowerQuery) {
          set({ 
            modelSearchQuery: query,
            modelSearchResults: modelCatalog 
          });
          return;
        }
        
        // Simple client-side fuzzy matching
        const results = modelCatalog.filter(model => {
          // Exact substring match
          if (model.name.toLowerCase().includes(lowerQuery)) return true;
          if (model.provider?.toLowerCase().includes(lowerQuery)) return true;
          
          // Split words match (all words must be present in name or provider)
          const words = lowerQuery.split(/\s+/);
          return words.every(word => 
            model.name.toLowerCase().includes(word) || 
            model.provider?.toLowerCase().includes(word)
          );
        });
        
        set({ 
          modelSearchQuery: query,
          modelSearchResults: results 
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
      }
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
  useProviderStore(useShallow((s) => ({
    fetchProviders: s.fetchProviders,
    createProvider: s.createProvider,
    updateProvider: s.updateProvider,
    deleteProvider: s.deleteProvider,
    setSelectedProvider: s.setSelectedProvider,
    fetchModelCatalog: s.fetchModelCatalog,
    searchModels: s.searchModels,
    testConnection: s.testConnection,
    reset: s.reset,
  })));
