import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { ProviderList } from '@/pages/tenant/ProviderList';
import { providerAPI } from '@/services/api';

import type { ProviderConfig, SystemResilienceStatus } from '@/types/memory';

const messageMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));

const providerStoreMock = vi.hoisted(() => ({
  deleteProvider: vi.fn(),
  error: null as string | null,
  fetchProviders: vi.fn(),
  loading: false,
  providers: [] as ProviderConfig[],
}));

const tenantStoreMock = vi.hoisted(() => ({
  currentTenant: { id: 'tenant-1', name: 'Tenant 1' },
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  return {
    ...actual,
    App: {
      ...actual.App,
      useApp: () => ({ message: messageMock }),
    },
  };
});

vi.mock('@/components/provider', () => ({
  AssignProviderModal: ({
    isOpen,
    provider,
    tenantId,
  }: {
    isOpen: boolean;
    provider: ProviderConfig;
    tenantId: string;
  }) =>
    isOpen ? (
      <div data-testid="assign-provider-modal" data-tenant-id={tenantId}>
        Assign {provider.name}
      </div>
    ) : null,
  ModelAssignment: ({ tenantId }: { tenantId: string }) => (
    <div data-testid="model-assignment" data-tenant-id={tenantId}>
      Assignments
    </div>
  ),
  ProviderConfigModal: () => null,
  ProviderHealthPanel: ({ systemStatus }: { systemStatus: SystemResilienceStatus | null }) => (
    <div data-testid="provider-health-panel">{systemStatus ? 'status loaded' : 'status missing'}</div>
  ),
  ProviderCard: ({
    onAssign,
    onCheckHealth,
    provider,
  }: {
    onAssign: (provider: ProviderConfig) => void;
    onCheckHealth: (providerId: string) => void;
    provider: ProviderConfig;
  }) => (
    <div>
      <span>{provider.name}</span>
      <button
        type="button"
        onClick={() => {
          onCheckHealth(provider.id);
        }}
      >
        Check {provider.name}
      </button>
      <button
        type="button"
        onClick={() => {
          onAssign(provider);
        }}
      >
        Assign {provider.name}
      </button>
    </div>
  ),
  ProviderUsageStats: () => null,
}));

vi.mock('@/services/api', () => ({
  providerAPI: {
    checkHealth: vi.fn(),
    getSystemStatus: vi.fn(),
    resetCircuitBreaker: vi.fn(),
  },
}));

vi.mock('@/stores/provider', () => ({
  useProviderStore: (selector: (state: typeof providerStoreMock) => unknown) =>
    selector(providerStoreMock),
}));

vi.mock('@/stores/tenant', () => ({
  useTenantStore: (selector: (state: typeof tenantStoreMock) => unknown) =>
    selector(tenantStoreMock),
}));

const systemStatus = (): SystemResilienceStatus => ({
  providers: {},
  summary: {
    healthy_count: 0,
    total_providers: 0,
  },
});

const provider = (overrides: Partial<ProviderConfig> = {}): ProviderConfig => ({
  allowed_models: [],
  api_key_masked: 'sk-***',
  blocked_models: [],
  config: {},
  created_at: '2026-06-17T00:00:00Z',
  health_status: 'unknown',
  id: 'provider-1',
  is_active: true,
  is_default: false,
  is_enabled: true,
  llm_model: 'gpt-4.1',
  name: 'OpenAI Primary',
  operation_type: 'chat',
  provider_type: 'openai',
  response_time_ms: undefined,
  updated_at: '2026-06-17T00:00:00Z',
  ...overrides,
});

function renderProviderList(route = '/tenant/tenant-1/providers') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/providers" element={<ProviderList />} />
        <Route path="/tenant/:tenantId/providers" element={<ProviderList />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('ProviderList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    providerStoreMock.deleteProvider.mockResolvedValue(undefined);
    providerStoreMock.error = null;
    providerStoreMock.fetchProviders.mockResolvedValue(undefined);
    providerStoreMock.loading = false;
    providerStoreMock.providers = [];
    tenantStoreMock.currentTenant = { id: 'tenant-1', name: 'Tenant 1' };
    vi.mocked(providerAPI.checkHealth).mockResolvedValue(undefined);
    vi.mocked(providerAPI.getSystemStatus).mockResolvedValue(systemStatus());
    vi.mocked(providerAPI.resetCircuitBreaker).mockResolvedValue(undefined);
  });

  it('surfaces provider system status load failures', async () => {
    vi.mocked(providerAPI.getSystemStatus).mockRejectedValueOnce(new Error('status unavailable'));

    renderProviderList();

    await waitFor(() => {
      expect(messageMock.error).toHaveBeenCalledWith('Failed to load provider system status');
    });
  });

  it('surfaces provider health check failures', async () => {
    providerStoreMock.providers = [provider()];
    vi.mocked(providerAPI.checkHealth).mockRejectedValueOnce(new Error('health unavailable'));

    renderProviderList();

    fireEvent.click(await screen.findByRole('button', { name: 'Check OpenAI Primary' }));

    await waitFor(() => {
      expect(providerAPI.checkHealth).toHaveBeenCalledWith('provider-1');
      expect(messageMock.error).toHaveBeenCalledWith('Failed to check provider health');
    });
  });

  it('uses the route tenant for assignment routing when the store tenant is stale', async () => {
    tenantStoreMock.currentTenant = { id: 'store-tenant', name: 'Store Tenant' };

    renderProviderList('/tenant/route-tenant/providers');

    fireEvent.click(await screen.findByRole('button', { name: 'Routing & Assignments' }));

    expect(await screen.findByTestId('model-assignment')).toHaveAttribute(
      'data-tenant-id',
      'route-tenant'
    );
  });

  it('opens tenant assignment modal with the route tenant when the store tenant is stale', async () => {
    tenantStoreMock.currentTenant = { id: 'store-tenant', name: 'Store Tenant' };
    providerStoreMock.providers = [provider()];

    renderProviderList('/tenant/route-tenant/providers');

    fireEvent.click(await screen.findByRole('button', { name: 'Assign OpenAI Primary' }));

    expect(await screen.findByTestId('assign-provider-modal')).toHaveAttribute(
      'data-tenant-id',
      'route-tenant'
    );
  });
});
