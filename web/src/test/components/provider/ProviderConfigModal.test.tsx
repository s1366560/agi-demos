import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProviderConfigModal } from '../../../components/provider/ProviderConfigModal';
import { providerAPI } from '../../../services/api';
import { fireEvent, render, screen, waitFor } from '../../utils';

const providerStore = vi.hoisted(() => ({
  searchModels: vi.fn(),
  fetchModelCatalog: vi.fn(),
  modelSearchResults: [],
  modelCatalog: [],
}));

vi.mock('../../../stores/provider', () => ({
  useProviderStore: (selector: (state: typeof providerStore) => unknown) => selector(providerStore),
}));

vi.mock('../../../services/api', () => ({
  providerAPI: {
    listModels: vi.fn(),
    detectEnvKeys: vi.fn(),
    testConnection: vi.fn(),
    checkHealth: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
  },
}));

describe('ProviderConfigModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    providerStore.fetchModelCatalog.mockResolvedValue(undefined);
    vi.mocked(providerAPI.detectEnvKeys).mockResolvedValue({ detected_providers: {} });
    vi.mocked(providerAPI.listModels).mockImplementation(async (providerType) => {
      if (providerType === 'deepseek') {
        return {
          provider_type: 'deepseek',
          models: {
            chat: ['deepseek-chat', 'deepseek-coder'],
            embedding: [],
            rerank: [],
          },
        };
      }

      return {
        provider_type: 'openai',
        models: {
          chat: ['gpt-4o'],
          embedding: ['text-embedding-3-small'],
          rerank: [],
        },
      };
    });
    vi.mocked(providerAPI.testConnection).mockResolvedValue({
      provider_id: 'draft-provider',
      status: 'healthy',
      last_check: '2026-05-16T00:00:00Z',
      error_message: null,
      response_time_ms: 123,
    });
  });

  it('calls onClose when Escape is pressed', async () => {
    const onClose = vi.fn();
    render(
      <ProviderConfigModal
        isOpen
        onClose={onClose}
        onSuccess={vi.fn()}
        initialProviderType="openai"
      />
    );

    await waitFor(() => {
      expect(providerAPI.detectEnvKeys).toHaveBeenCalled();
      expect(providerAPI.listModels).toHaveBeenCalledWith('openai');
    });

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('tests a new provider through the live connection API', async () => {
    const { container } = render(
      <ProviderConfigModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        initialProviderType="openai"
      />
    );

    const apiKeyInput = await waitFor(() => {
      const input = container.querySelector('input[type="password"]');
      expect(input).toBeTruthy();
      return input as HTMLInputElement;
    });
    fireEvent.change(apiKeyInput, { target: { value: 'sk-live-test' } });

    fireEvent.click(screen.getByRole('button', { name: 'Test' }));

    await waitFor(() => {
      expect(providerAPI.testConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'OpenAI',
          provider_type: 'openai',
          api_key: 'sk-live-test',
          llm_model: 'gpt-4o',
        })
      );
    });
    expect(providerAPI.checkHealth).not.toHaveBeenCalled();
    expect(await screen.findByText('Connection test passed (123 ms).')).toBeInTheDocument();
  });

  it('exposes DeepSeek in the provider picker and configures it as an LLM provider', async () => {
    const { container } = render(
      <ProviderConfigModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />
    );

    const deepseekButton = await screen.findByRole('button', { name: /DeepSeek/i });
    fireEvent.click(deepseekButton);

    await waitFor(() => {
      expect(providerAPI.listModels).toHaveBeenCalledWith('deepseek');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    const apiKeyInput = await waitFor(() => {
      const input = container.querySelector('input[type="password"]');
      expect(input).toBeTruthy();
      return input as HTMLInputElement;
    });
    fireEvent.change(apiKeyInput, { target: { value: 'sk-deepseek-test' } });

    fireEvent.click(screen.getByRole('button', { name: 'Test' }));

    await waitFor(() => {
      expect(providerAPI.testConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'DeepSeek',
          provider_type: 'deepseek',
          operation_type: 'llm',
          api_key: 'sk-deepseek-test',
          llm_model: 'deepseek-chat',
          llm_small_model: 'deepseek-coder',
        })
      );
    });
  });
});
