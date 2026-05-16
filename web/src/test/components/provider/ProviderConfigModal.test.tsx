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
    vi.mocked(providerAPI.listModels).mockResolvedValue({
      provider_type: 'openai',
      models: {
        chat: ['gpt-4o'],
        embedding: ['text-embedding-3-small'],
        rerank: [],
      },
    });
    vi.mocked(providerAPI.testConnection).mockResolvedValue({
      provider_id: 'draft-provider',
      status: 'healthy',
      last_check: '2026-05-16T00:00:00Z',
      error_message: null,
      response_time_ms: 123,
    });
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
});
