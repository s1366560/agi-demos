import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProviderConfigModal } from '../../../components/provider/ProviderConfigModal';
import { providerAPI } from '../../../services/api';
import type { ProviderConfig, ProviderTypeDescriptor } from '../../../types/memory';
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
    listTypes: vi.fn(),
    detectEnvKeys: vi.fn(),
    testConnection: vi.fn(),
    checkHealth: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
  },
}));

describe('ProviderConfigModal', () => {
  const providerTypes: ProviderTypeDescriptor[] = [
    {
      provider_type: 'openai',
      auth_methods: ['api_key', 'environment'],
      unavailable_auth_methods: ['oauth'],
    },
    {
      provider_type: 'deepseek',
      auth_methods: ['api_key'],
      unavailable_auth_methods: [],
    },
    {
      provider_type: 'volcengine',
      auth_methods: ['api_key', 'environment'],
      unavailable_auth_methods: [],
    },
    {
      provider_type: 'azure_openai',
      probe_supported: false,
      auth_methods: ['api_key'],
      unavailable_auth_methods: ['oauth'],
    },
    {
      provider_type: 'bedrock',
      probe_supported: false,
      auth_methods: [],
      unavailable_auth_methods: ['api_key', 'environment', 'oauth'],
    },
  ];

  const savedProvider: ProviderConfig = {
    id: 'provider-1',
    name: 'OpenAI',
    provider_type: 'openai',
    operation_type: 'llm',
    base_url: 'https://gateway.example.com/v1',
    llm_model: 'gpt-4o',
    llm_small_model: 'gpt-4o-mini',
    config: {},
    is_active: true,
    is_enabled: true,
    is_default: false,
    auth_method: 'api_key',
    environment_variable: null,
    credential_configured: true,
    api_key_masked: 'sk-***',
    allowed_models: [],
    blocked_models: [],
    revision: 42,
    created_at: '2026-05-16T00:00:00Z',
    updated_at: '2026-05-16T00:00:00Z',
  };

  beforeEach(() => {
    vi.clearAllMocks();
    providerStore.fetchModelCatalog.mockResolvedValue(undefined);
    vi.mocked(providerAPI.listTypes).mockResolvedValue(providerTypes);
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
          auth_method: 'api_key',
          api_key: 'sk-live-test',
        })
      );
    });
    const probe = vi.mocked(providerAPI.testConnection).mock.calls[0]?.[0];
    expect(probe).not.toHaveProperty('environment_variable');
    expect(probe).not.toHaveProperty('llm_model');
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
          auth_method: 'api_key',
          api_key: 'sk-deepseek-test',
        })
      );
    });
  });

  it('uses a detected environment variable reference without copying a secret into api_key', async () => {
    vi.mocked(providerAPI.detectEnvKeys).mockResolvedValue({
      detected_providers: {
        openai: {
          provider_type: 'openai',
          operation_type: 'llm',
          credential_source: 'environment',
          credential_configured: true,
          environment_variable: 'OPENAI_API_KEY',
          base_url: 'https://api.openai.com/v1',
          llm_model: 'gpt-4o',
          llm_small_model: 'gpt-4o-mini',
          embedding_model: 'text-embedding-3-small',
          reranker_model: null,
        },
      },
    });

    render(
      <ProviderConfigModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        initialProviderType="openai"
      />
    );

    await waitFor(() => {
      expect(screen.getByLabelText('Authentication')).toHaveValue('environment');
      expect(screen.getByLabelText('Environment variable')).toHaveValue('OPENAI_API_KEY');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Save Provider' }));

    await waitFor(() => {
      expect(providerAPI.create).toHaveBeenCalledWith(
        expect.objectContaining({
          auth_method: 'environment',
          environment_variable: 'OPENAI_API_KEY',
          provider_type: 'openai',
        })
      );
    });
    const payload = vi.mocked(providerAPI.create).mock.calls[0]?.[0];
    expect(payload).not.toHaveProperty('api_key');
  });

  it('does not infer or copy a secret when legacy environment detection omits the variable name', async () => {
    vi.mocked(providerAPI.detectEnvKeys).mockResolvedValue({
      detected_providers: {
        openai: {
          provider_type: 'openai',
          operation_type: 'llm',
          credential_source: 'environment',
          credential_configured: true,
          base_url: 'https://api.openai.com/v1',
          llm_model: 'gpt-4o',
          llm_small_model: 'gpt-4o-mini',
          embedding_model: null,
          reranker_model: null,
          api_key: 'must-not-enter-the-form',
        },
      },
    } as never);

    const { container } = render(
      <ProviderConfigModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        initialProviderType="openai"
      />
    );

    await screen.findByText(/No credential was auto-filled/i);
    expect(screen.getByLabelText('Authentication')).toHaveValue('api_key');
    expect(container.querySelector('input[type="password"]')).toHaveValue('');
    expect(screen.queryByDisplayValue('must-not-enter-the-form')).not.toBeInTheDocument();
  });

  it('accepts configuration-only validation without claiming a network connection', async () => {
    vi.mocked(providerAPI.testConnection).mockResolvedValue({
      provider_id: 'draft-provider',
      status: 'configuration_valid',
      probed: false,
      detail: 'Connection probing is not supported for this provider type',
      last_check: '2026-05-16T00:00:00Z',
      error_message: null,
      response_time_ms: null,
    });

    const { container } = render(
      <ProviderConfigModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        initialProviderType="azure_openai"
      />
    );

    const apiKeyInput = await waitFor(() => {
      const input = container.querySelector('input[type="password"]');
      expect(input).toBeTruthy();
      return input as HTMLInputElement;
    });
    fireEvent.change(apiKeyInput, { target: { value: 'azure-test-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Test' }));

    expect(
      await screen.findByText(
        'Configuration validated. Network probing is not supported for this provider.'
      )
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
  });

  it('keeps authentication fail-closed while capability metadata is loading', async () => {
    vi.mocked(providerAPI.listTypes).mockImplementationOnce(
      () => new Promise<ProviderTypeDescriptor[]>(() => undefined)
    );

    const { container } = render(
      <ProviderConfigModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        initialProviderType="openai"
      />
    );

    expect(
      await screen.findByText(
        'Authentication options are loading. Saving stays disabled until the server confirms them.'
      )
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Authentication')).toBeDisabled();
    expect(container.querySelector('input[type="password"]')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('shows configuration-only validation for a saved provider without claiming a probe', async () => {
    vi.mocked(providerAPI.checkHealth).mockResolvedValue({
      provider_id: 'provider-1',
      status: 'configuration_valid',
      probed: false,
      detail: 'Connection probing is not supported for this provider type',
      last_check: '2026-05-16T00:00:00Z',
      error_message: null,
      response_time_ms: null,
    });
    const savedNoProbeProvider: ProviderConfig = {
      ...savedProvider,
      provider_type: 'azure_openai',
      name: 'Azure OpenAI',
      base_url: 'https://example.openai.azure.com',
    };

    render(
      <ProviderConfigModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        provider={savedNoProbeProvider}
      />
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Test' }));

    await waitFor(() => {
      expect(providerAPI.checkHealth).toHaveBeenCalledWith('provider-1');
    });
    expect(providerAPI.testConnection).not.toHaveBeenCalled();
    expect(
      await screen.findByText(
        'Configuration validated. Network probing is not supported for this provider.'
      )
    ).toBeInTheDocument();
  });

  it('keeps providers with no secure authentication capability unavailable', async () => {
    const { container } = render(
      <ProviderConfigModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        initialProviderType="bedrock"
      />
    );

    await waitFor(() => {
      expect(screen.getByLabelText('Authentication')).toHaveValue('');
    });
    expect(screen.getByLabelText('Authentication')).toBeDisabled();
    expect(
      screen.getByText(
        'This provider cannot be configured until secure credential storage is available.'
      )
    ).toBeInTheDocument();
    expect(container.querySelector('input[type="password"]')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('sends null when an edited provider clears its custom base URL', async () => {
    const { container } = render(
      <ProviderConfigModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} provider={savedProvider} />
    );

    const apiKeyInput = await waitFor(() => {
      const input = container.querySelector('input[type="password"]');
      expect(input).toBeTruthy();
      return input as HTMLInputElement;
    });
    fireEvent.change(apiKeyInput, {
      target: { value: 'sk-replacement' },
    });
    const baseUrl = await screen.findByDisplayValue('https://gateway.example.com/v1');
    fireEvent.change(baseUrl, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Save Provider' }));

    await waitFor(() => {
      expect(providerAPI.update).toHaveBeenCalledWith(
        'provider-1',
        expect.objectContaining({
          auth_method: 'api_key',
          api_key: 'sk-replacement',
          base_url: null,
          expected_revision: 42,
        })
      );
    });
    const payload = vi.mocked(providerAPI.update).mock.calls[0]?.[1];
    expect(payload).not.toHaveProperty('environment_variable');
  });

  it('does not render or submit legacy plaintext provider credentials', async () => {
    const providerWithLegacySecrets: ProviderConfig = {
      ...savedProvider,
      name: 'Volcengine',
      provider_type: 'volcengine',
      base_url: null,
      config: {
        temperature: 0.4,
        rtc_app_key: 'legacy-rtc-secret',
        volc_ak: 'legacy-access-key',
        volc_sk: 'legacy-secret-key',
        speech_access_token: 'legacy-speech-secret',
        provider_options: { token: 'legacy-option-secret' },
      },
    };

    render(
      <ProviderConfigModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        provider={providerWithLegacySecrets}
      />
    );

    expect(await screen.findByText('Secure RTC credentials')).toBeInTheDocument();
    expect(screen.queryByText('Provider Configuration (JSON)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('RTC App Key')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Volcengine Access Key (AK)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Volcengine Secret Key (SK)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Speech Access Token')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Save Provider' }));

    await waitFor(() => {
      expect(providerAPI.update).toHaveBeenCalledWith(
        'provider-1',
        expect.objectContaining({ config: { temperature: 0.4 } })
      );
    });
    const payload = vi.mocked(providerAPI.update).mock.calls[0]?.[1];
    expect(JSON.stringify(payload)).not.toContain('legacy-');
    expect(payload?.config).not.toHaveProperty('provider_options');
  });

  it('does not render or submit free-form embedding provider options', async () => {
    const embeddingProvider: ProviderConfig = {
      ...savedProvider,
      operation_type: 'embedding',
      llm_model: undefined,
      llm_small_model: undefined,
      embedding_model: 'text-embedding-3-small',
      embedding_config: {
        model: 'text-embedding-3-small',
        dimensions: 1536,
        provider_options: { batch_size: 32, api_key: 'legacy-option-secret' },
      },
      config: {
        embedding: {
          model: 'text-embedding-3-small',
          dimensions: 1536,
          provider_options: { batch_size: 32, api_key: 'legacy-option-secret' },
        },
      },
    };

    render(
      <ProviderConfigModal
        isOpen
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        provider={embeddingProvider}
      />
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    fireEvent.click(screen.getByRole('button', { name: 'Advanced Embedding Settings' }));
    expect(screen.queryByText('Provider Options (JSON)')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Save Provider' }));

    await waitFor(() => {
      expect(providerAPI.update).toHaveBeenCalled();
    });
    const payload = vi.mocked(providerAPI.update).mock.calls[0]?.[1];
    expect(payload?.embedding_config).toEqual({
      model: 'text-embedding-3-small',
      dimensions: 1536,
      provider_options: { batch_size: 32 },
    });
    expect(JSON.stringify(payload)).not.toContain('legacy-option-secret');
  });
});
