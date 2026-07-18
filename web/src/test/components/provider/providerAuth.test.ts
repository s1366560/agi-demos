import { describe, expect, it } from 'vitest';

import {
  getProviderAuthMethods,
  isProviderCredentialReady,
} from '../../../components/provider/providerAuth';
import type { ProviderConfig, ProviderTypeDescriptor } from '../../../types/memory';

const provider = (overrides: Partial<ProviderConfig> = {}): ProviderConfig => ({
  id: 'provider-1',
  name: 'OpenAI',
  provider_type: 'openai',
  operation_type: 'llm',
  base_url: 'https://api.openai.com/v1',
  llm_model: 'gpt-4o',
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
  revision: 10,
  created_at: '2026-05-16T00:00:00Z',
  updated_at: '2026-05-16T00:00:00Z',
  ...overrides,
});

describe('provider credential binding', () => {
  it('keeps missing capability metadata fail-closed', () => {
    expect(getProviderAuthMethods({}, 'openai')).toEqual([]);
    expect(getProviderAuthMethods({}, 'bedrock', 'api_key')).toEqual([]);
  });

  it('keeps an explicitly empty server capability fail-closed', () => {
    const capabilities: Partial<Record<'bedrock', ProviderTypeDescriptor>> = {
      bedrock: {
        provider_type: 'bedrock',
        probe_supported: false,
        auth_methods: [],
        unavailable_auth_methods: ['api_key', 'environment', 'oauth'],
      },
    };

    expect(getProviderAuthMethods(capabilities, 'bedrock')).toEqual([]);
    expect(getProviderAuthMethods(capabilities, 'bedrock', 'api_key')).toEqual([]);
  });

  it('only reuses a configured API key for the same provider endpoint', () => {
    const saved = provider();

    expect(
      isProviderCredentialReady(
        {
          auth_method: 'api_key',
          api_key: '',
          base_url: 'https://api.openai.com/v1',
          environment_variable: '',
        },
        saved,
        'openai'
      )
    ).toBe(true);
    expect(
      isProviderCredentialReady(
        {
          auth_method: 'api_key',
          api_key: '',
          base_url: 'https://gateway.example.com/v1',
          environment_variable: '',
        },
        saved,
        'openai'
      )
    ).toBe(false);
  });

  it('only reuses an environment credential for the same endpoint and variable reference', () => {
    const saved = provider({
      auth_method: 'environment',
      environment_variable: 'OPENAI_API_KEY',
      api_key_masked: '',
    });

    expect(
      isProviderCredentialReady(
        {
          auth_method: 'environment',
          api_key: '',
          base_url: 'https://api.openai.com/v1',
          environment_variable: 'OPENAI_API_KEY',
        },
        saved,
        'openai'
      )
    ).toBe(true);
    expect(
      isProviderCredentialReady(
        {
          auth_method: 'environment',
          api_key: '',
          base_url: 'https://api.openai.com/v1',
          environment_variable: 'OTHER_API_KEY',
        },
        saved,
        'openai'
      )
    ).toBe(false);
    expect(
      isProviderCredentialReady(
        {
          auth_method: 'environment',
          api_key: '',
          base_url: 'https://gateway.example.com/v1',
          environment_variable: 'OPENAI_API_KEY',
        },
        saved,
        'openai'
      )
    ).toBe(false);
  });
});
