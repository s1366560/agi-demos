import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProviderModal } from '../../../components/tenant/ProviderModal';
import { providerAPI } from '../../../services/api';
import type { ProviderConfig, ProviderTypeDescriptor } from '../../../types/memory';
import { fireEvent, render, screen, waitFor } from '../../utils';

vi.mock('../../../services/api', () => ({
  providerAPI: {
    create: vi.fn(),
    detectEnvKeys: vi.fn(),
    listTypes: vi.fn(),
    update: vi.fn(),
  },
}));

const providerTypes: ProviderTypeDescriptor[] = [
  {
    provider_type: 'openai',
    auth_methods: ['api_key', 'environment'],
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
  embedding_model: 'text-embedding-3-small',
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
  revision: 77,
  created_at: '2026-05-16T00:00:00Z',
  updated_at: '2026-05-16T00:00:00Z',
};

describe('ProviderModal provider authentication contract', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(providerAPI.listTypes).mockResolvedValue(providerTypes);
    vi.mocked(providerAPI.detectEnvKeys).mockResolvedValue({ detected_providers: {} });
    vi.mocked(providerAPI.create).mockResolvedValue(savedProvider);
    vi.mocked(providerAPI.update).mockResolvedValue(savedProvider);
  });

  it('creates an environment-authenticated provider with only a variable reference', async () => {
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

    render(<ProviderModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByLabelText('Authentication')).toHaveValue('environment');
      expect(screen.getByLabelText('Environment variable *')).toHaveValue('OPENAI_API_KEY');
    });
    fireEvent.change(screen.getByLabelText(/labels\.providerName/i), {
      target: { value: 'Runtime OpenAI' },
    });

    fireEvent.click(screen.getByRole('button', { name: /createProvider/i }));

    await waitFor(() => {
      expect(providerAPI.create).toHaveBeenCalledWith(
        expect.objectContaining({
          auth_method: 'environment',
          environment_variable: 'OPENAI_API_KEY',
          name: 'Runtime OpenAI',
        })
      );
    });
    const payload = vi.mocked(providerAPI.create).mock.calls[0]?.[0];
    expect(payload).not.toHaveProperty('api_key');
  });

  it('updates with the exact revision and explicit null when base URL is cleared', async () => {
    render(<ProviderModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} provider={savedProvider} />);

    await waitFor(() => {
      expect(providerAPI.listTypes).toHaveBeenCalled();
      expect(providerAPI.detectEnvKeys).toHaveBeenCalled();
    });
    fireEvent.change(screen.getByLabelText(/labels\.apiKey/i), {
      target: { value: 'sk-replacement' },
    });
    fireEvent.click(screen.getByRole('button', { name: /tabs\.advanced/i }));
    fireEvent.change(screen.getByLabelText(/labels\.customBaseUrl/i), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: /updateProvider/i }));

    await waitFor(() => {
      expect(providerAPI.update).toHaveBeenCalledWith(
        'provider-1',
        expect.objectContaining({
          auth_method: 'api_key',
          api_key: 'sk-replacement',
          base_url: null,
          expected_revision: 77,
        })
      );
    });
    const payload = vi.mocked(providerAPI.update).mock.calls[0]?.[1];
    expect(payload).not.toHaveProperty('environment_variable');
  });

  it('does not reuse a configured API key after its endpoint binding changes', async () => {
    render(<ProviderModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} provider={savedProvider} />);

    await waitFor(() => {
      expect(providerAPI.listTypes).toHaveBeenCalled();
      expect(providerAPI.detectEnvKeys).toHaveBeenCalled();
    });
    fireEvent.click(screen.getByRole('button', { name: /tabs\.advanced/i }));
    fireEvent.change(screen.getByLabelText(/labels\.customBaseUrl/i), {
      target: { value: 'https://other.example.com/v1' },
    });

    expect(screen.getByRole('button', { name: /updateProvider/i })).toBeDisabled();
    expect(providerAPI.update).not.toHaveBeenCalled();
  });

  it('does not fall back to API key when the server declares no supported auth method', async () => {
    const { container } = render(<ProviderModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />);

    await waitFor(() => {
      expect(providerAPI.listTypes).toHaveBeenCalled();
    });
    fireEvent.change(screen.getByLabelText(/labels\.providerType/i), {
      target: { value: 'bedrock' },
    });

    await waitFor(() => {
      expect(screen.getByLabelText('Authentication')).toHaveValue('');
    });
    expect(screen.getByLabelText('Authentication')).toBeDisabled();
    expect(container.querySelector('input[type="password"]')).not.toBeInTheDocument();
    expect(
      screen.getByText(
        'This provider cannot be configured until secure credential storage is available.'
      )
    ).toBeInTheDocument();
  });

  it('keeps saving disabled when capability metadata cannot be loaded', async () => {
    vi.mocked(providerAPI.listTypes).mockRejectedValueOnce(new Error('capability service offline'));

    const { container } = render(<ProviderModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />);

    expect(
      await screen.findByText(
        'Authentication options could not be loaded. Reopen this dialog to try again.'
      )
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Authentication')).toBeDisabled();
    expect(container.querySelector('input[type="password"]')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /createProvider/i })).toBeDisabled();
    expect(providerAPI.create).not.toHaveBeenCalled();
  });
});
