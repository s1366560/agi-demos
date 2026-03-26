import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useActiveModelCapabilities } from '@/hooks/useActiveModelCapabilities';
import { useProviderStore } from '@/stores/provider';

import type { ModelCatalogEntry, ProviderConfig } from '@/types/memory';

const makeProvider = (overrides: Partial<ProviderConfig> = {}): ProviderConfig => ({
  id: 'provider-1',
  name: 'Default Provider',
  provider_type: 'openai',
  base_url: undefined,
  llm_model: 'openai/gpt-4o-mini',
  llm_small_model: undefined,
  embedding_model: undefined,
  embedding_config: undefined,
  reranker_model: undefined,
  config: {},
  is_active: true,
  is_enabled: true,
  is_default: true,
  api_key_masked: '********',
  allowed_models: [],
  blocked_models: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

const makeModel = (
  name: string,
  overrides: Partial<ModelCatalogEntry> = {}
): ModelCatalogEntry => ({
  name,
  provider: 'openai',
  family: 'test',
  context_length: 128000,
  max_output_tokens: 16384,
  capabilities: ['chat'],
  modalities: ['text'],
  variants: [],
  supports_streaming: true,
  supports_json_mode: true,
  reasoning: false,
  supports_temperature: true,
  supports_tool_call: true,
  supports_structured_output: true,
  supports_attachment: true,
  is_deprecated: false,
  open_weights: false,
  ...overrides,
});

describe('useActiveModelCapabilities', () => {
  beforeEach(() => {
    useProviderStore.setState({
      providers: [],
      loading: false,
      error: null,
      selectedProvider: null,
      modelCatalog: [],
      catalogLoading: false,
      modelSearchQuery: '',
      modelSearchResults: [],
    });
  });

  it('uses default provider model when no override is provided', () => {
    useProviderStore.setState({
      providers: [makeProvider()],
      modelCatalog: [makeModel('openai/gpt-4o-mini', { supports_attachment: false })],
      modelSearchResults: [],
    });

    const { result } = renderHook(() => useActiveModelCapabilities());
    expect(result.current.model?.name).toBe('openai/gpt-4o-mini');
    expect(result.current.supportsAttachment).toBe(false);
  });

  it('prioritizes same-provider model override over default provider model', () => {
    useProviderStore.setState({
      providers: [makeProvider({ llm_model: 'openai/gpt-4o-mini' })],
      modelCatalog: [
        makeModel('openai/gpt-4o-mini', { supports_attachment: true }),
        makeModel('openai/gpt-4.1-mini', {
          supports_attachment: false,
        }),
      ],
      modelSearchResults: [],
    });

    const { result } = renderHook(() => useActiveModelCapabilities('openai/gpt-4.1-mini'));
    expect(result.current.model?.name).toBe('openai/gpt-4.1-mini');
    expect(result.current.supportsAttachment).toBe(false);
  });

  it('ignores cross-provider override and falls back to default provider model', () => {
    useProviderStore.setState({
      providers: [makeProvider({ llm_model: 'openai/gpt-4o-mini' })],
      modelCatalog: [
        makeModel('openai/gpt-4o-mini', { supports_attachment: true }),
        makeModel('anthropic/claude-3-5-haiku', {
          provider: 'anthropic',
          supports_attachment: false,
        }),
      ],
      modelSearchResults: [],
    });

    const { result } = renderHook(() => useActiveModelCapabilities('anthropic/claude-3-5-haiku'));
    expect(result.current.model?.name).toBe('openai/gpt-4o-mini');
    expect(result.current.supportsAttachment).toBe(true);
  });

  it('derives provider hint from default model metadata for aliased provider types', () => {
    useProviderStore.setState({
      providers: [makeProvider({ provider_type: 'azure_openai', llm_model: 'gpt-4o-mini' })],
      modelCatalog: [
        makeModel('gpt-4o-mini', { provider: 'openai', supports_attachment: true }),
        makeModel('gpt-4.1-mini', { provider: 'openai', supports_attachment: false }),
      ],
      modelSearchResults: [],
    });

    const { result } = renderHook(() => useActiveModelCapabilities('openai/gpt-4.1-mini'));
    expect(result.current.model?.name).toBe('gpt-4.1-mini');
    expect(result.current.supportsAttachment).toBe(false);
  });

  it('supports provider types with _coding suffix when matching override provider', () => {
    useProviderStore.setState({
      providers: [makeProvider({ provider_type: 'dashscope_coding', llm_model: 'qwen-plus' })],
      modelCatalog: [
        makeModel('qwen-plus', { provider: 'dashscope', supports_attachment: true }),
        makeModel('qwen-max', { provider: 'dashscope', supports_attachment: false }),
      ],
      modelSearchResults: [],
    });

    const { result } = renderHook(() => useActiveModelCapabilities('qwen-max'));
    expect(result.current.model?.name).toBe('qwen-max');
    expect(result.current.supportsAttachment).toBe(false);
  });
});
