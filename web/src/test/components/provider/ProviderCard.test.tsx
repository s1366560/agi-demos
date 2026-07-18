import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ProviderCard } from '@/components/provider/ProviderCard';

import type { ProviderConfig } from '@/types/memory';

const provider = (overrides: Partial<ProviderConfig> = {}): ProviderConfig => ({
  allowed_models: [],
  api_key_masked: 'sk-***',
  auth_method: 'api_key',
  blocked_models: [],
  config: {},
  created_at: '2026-06-17T00:00:00Z',
  credential_configured: true,
  environment_variable: null,
  id: 'provider-1',
  is_active: true,
  is_default: false,
  is_enabled: true,
  llm_model: 'gpt-4.1',
  name: 'OpenAI Primary',
  operation_type: 'llm',
  provider_type: 'openai',
  resilience: {
    can_execute: true,
    circuit_breaker_state: 'closed',
    failure_count: 0,
    rate_limit: {
      current_concurrent: 0,
      max_concurrent: 10,
      total_requests: 0,
      requests_per_minute: 0,
    },
    success_count: 0,
  },
  revision: 1,
  updated_at: '2026-06-17T00:00:00Z',
  ...overrides,
});

describe('ProviderCard', () => {
  it('renders configuration-only validation as validated instead of unknown', () => {
    render(
      <ProviderCard
        provider={provider({ health_status: 'configuration_valid' })}
        onAssign={vi.fn()}
        onCheckHealth={vi.fn()}
        onDelete={vi.fn()}
        onEdit={vi.fn()}
        onResetCircuitBreaker={vi.fn()}
      />
    );

    const status = screen.getByText('Configuration validated');
    expect(status).toHaveClass('text-emerald-600');
    expect(screen.queryByText('Unknown')).not.toBeInTheDocument();
  });
});
