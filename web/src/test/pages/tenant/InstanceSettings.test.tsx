import type { ReactNode } from 'react';

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { InstanceSettings } from '@/pages/tenant/InstanceSettings';
import { providerAPI } from '@/services/api';
import { instanceService } from '@/services/instanceService';
import { useInstanceStore } from '@/stores/instance';

import type { InstanceLlmConfigResponse, InstanceResponse } from '@/services/instanceService';
import type { ProviderConfig, ProviderType } from '@/types/memory';

const routerState = vi.hoisted(() => ({
  instanceId: 'instance-old',
  navigate: vi.fn(),
}));

const lazyMessageMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => routerState.navigate,
    useParams: () => ({ instanceId: routerState.instanceId }),
  };
});

vi.mock('@/services/api', () => ({
  providerAPI: {
    list: vi.fn(),
    listModels: vi.fn(),
  },
}));

vi.mock('@/services/instanceService', () => ({
  instanceService: {
    getById: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    getLlmConfig: vi.fn(),
    updateLlmConfig: vi.fn(),
  },
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyButton: ({
    children,
    disabled,
    icon,
    onClick,
  }: {
    children?: ReactNode;
    disabled?: boolean;
    icon?: ReactNode;
    onClick?: () => void;
  }) => (
    <button disabled={disabled} onClick={onClick} type="button">
      {icon}
      {children}
    </button>
  ),
  LazyPopconfirm: ({ children }: { children?: ReactNode }) => <>{children}</>,
  LazySelect: ({
    disabled,
    id,
    onChange,
    options = [],
    value,
  }: {
    disabled?: boolean;
    id?: string;
    onChange?: (value: string | undefined) => void;
    options?: Array<{ label: ReactNode; value: string }>;
    value?: string | null;
  }) => (
    <select
      disabled={disabled}
      id={id}
      value={value ?? ''}
      onChange={(event) => {
        onChange?.(event.target.value || undefined);
      }}
    >
      <option value="">Clear</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
  LazySpin: () => <div role="status">loading</div>,
  useLazyMessage: () => lazyMessageMock,
}));

const mockProviderAPI = vi.mocked(providerAPI);
const mockInstanceService = vi.mocked(instanceService);

function deferred<T>() {
  let resolve: (value: T | PromiseLike<T>) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

async function resolveRequest<T>(request: ReturnType<typeof deferred<T>>, value: T): Promise<void> {
  await act(async () => {
    request.resolve(value);
    await request.promise;
  });
}

const instance = (overrides: Partial<InstanceResponse> = {}): InstanceResponse => ({
  advanced_config: {},
  agent_display_name: null,
  agent_label: null,
  available_replicas: null,
  cluster_id: null,
  compute_provider: null,
  cpu_limit: '1',
  cpu_request: '100m',
  created_at: '2026-06-17T00:00:00Z',
  created_by: null,
  current_revision: null,
  description: null,
  env_vars: {},
  health_status: null,
  hex_position_q: null,
  hex_position_r: null,
  id: 'instance-old',
  image_version: 'latest',
  ingress_domain: null,
  llm_providers: {},
  mem_limit: '1Gi',
  mem_request: '256Mi',
  name: 'Old Instance',
  namespace: null,
  pending_config: null,
  proxy_token: null,
  quota_cpu: null,
  quota_max_pods: null,
  quota_memory: null,
  replicas: 1,
  runtime: 'docker',
  service_type: 'ClusterIP',
  slug: 'instance-old',
  status: 'running',
  storage_class: null,
  storage_size: null,
  tenant_id: 'tenant-1',
  theme_color: null,
  updated_at: null,
  workspace_id: null,
  ...overrides,
});

const llmConfig = (
  overrides: Partial<InstanceLlmConfigResponse> = {}
): InstanceLlmConfigResponse => ({
  has_api_key_override: false,
  model_name: null,
  provider_id: null,
  ...overrides,
});

const provider = (
  overrides: Partial<ProviderConfig> & { provider_type?: ProviderType } = {}
): ProviderConfig => ({
  allowed_models: [],
  api_key_masked: 'sk-***',
  blocked_models: [],
  config: {},
  created_at: '2026-06-17T00:00:00Z',
  health_status: 'unknown',
  id: 'provider-openai',
  is_active: true,
  is_default: false,
  is_enabled: true,
  llm_model: 'gpt-4.1',
  name: 'OpenAI',
  operation_type: 'chat',
  provider_type: 'openai',
  response_time_ms: undefined,
  updated_at: '2026-06-17T00:00:00Z',
  ...overrides,
});

const models = (providerType: string, chat: string[]) => ({
  models: {
    chat,
    embedding: [],
    rerank: [],
  },
  provider_type: providerType,
});

describe('InstanceSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routerState.instanceId = 'instance-old';
    useInstanceStore.getState().reset();
    useInstanceStore.setState({ currentInstance: instance() });
    mockProviderAPI.list.mockResolvedValue([
      provider({ id: 'provider-openai', name: 'OpenAI', provider_type: 'openai' }),
      provider({ id: 'provider-gemini', name: 'Gemini', provider_type: 'gemini' }),
    ]);
    mockProviderAPI.listModels.mockResolvedValue(models('openai', []));
    mockInstanceService.getById.mockResolvedValue(instance());
    mockInstanceService.getLlmConfig.mockResolvedValue(llmConfig());
    mockInstanceService.update.mockResolvedValue(instance());
    mockInstanceService.delete.mockResolvedValue(undefined);
    mockInstanceService.updateLlmConfig.mockResolvedValue(llmConfig());
  });

  it('ignores stale instance detail and LLM config responses after route changes', async () => {
    const oldDetail = deferred<InstanceResponse>();
    const newDetail = deferred<InstanceResponse>();
    const oldConfig = deferred<InstanceLlmConfigResponse>();
    const newConfig = deferred<InstanceLlmConfigResponse>();
    mockInstanceService.getById
      .mockReturnValueOnce(oldDetail.promise)
      .mockReturnValueOnce(newDetail.promise);
    mockInstanceService.getLlmConfig
      .mockReturnValueOnce(oldConfig.promise)
      .mockReturnValueOnce(newConfig.promise);

    const view = render(<InstanceSettings />);

    await waitFor(() => {
      expect(mockInstanceService.getLlmConfig).toHaveBeenCalledWith('instance-old');
    });

    routerState.instanceId = 'instance-new';
    view.rerender(<InstanceSettings />);

    await waitFor(() => {
      expect(mockInstanceService.getLlmConfig).toHaveBeenCalledWith('instance-new');
    });

    await resolveRequest(
      newDetail,
      instance({
        id: 'instance-new',
        name: 'New Instance',
        slug: 'instance-new',
      })
    );
    await resolveRequest(
      newConfig,
      llmConfig({
        has_api_key_override: true,
        model_name: 'gemini-current',
        provider_id: 'provider-gemini',
      })
    );

    await waitFor(() => {
      expect(screen.getByDisplayValue('New Instance')).toBeInTheDocument();
      expect(screen.getByLabelText('tenant.instances.settings.llmProvider')).toHaveValue(
        'provider-gemini'
      );
    });

    await resolveRequest(
      oldDetail,
      instance({
        id: 'instance-old',
        name: 'Stale Instance',
        slug: 'instance-old',
      })
    );
    await resolveRequest(
      oldConfig,
      llmConfig({
        model_name: 'stale-model',
        provider_id: 'provider-openai',
      })
    );

    expect(screen.getByDisplayValue('New Instance')).toBeInTheDocument();
    expect(screen.getByLabelText('tenant.instances.settings.llmProvider')).toHaveValue(
      'provider-gemini'
    );
  });

  it('ignores stale model list responses after provider changes', async () => {
    const staleModels = deferred<ReturnType<typeof models>>();
    const latestModels = deferred<ReturnType<typeof models>>();
    mockInstanceService.getById.mockResolvedValue(instance());
    mockInstanceService.getLlmConfig.mockResolvedValue(
      llmConfig({ provider_id: 'provider-openai' })
    );
    mockProviderAPI.listModels
      .mockReturnValueOnce(staleModels.promise)
      .mockReturnValueOnce(latestModels.promise);

    render(<InstanceSettings />);

    await waitFor(() => {
      expect(mockProviderAPI.listModels).toHaveBeenCalledWith('openai');
    });

    fireEvent.change(screen.getByLabelText('tenant.instances.settings.llmProvider'), {
      target: { value: 'provider-gemini' },
    });

    await waitFor(() => {
      expect(mockProviderAPI.listModels).toHaveBeenCalledWith('gemini');
    });

    await resolveRequest(latestModels, models('gemini', ['gemini-current']));

    await waitFor(() => {
      expect(screen.getByText('gemini-current')).toBeInTheDocument();
    });

    await resolveRequest(staleModels, models('openai', ['gpt-stale']));

    expect(screen.getByText('gemini-current')).toBeInTheDocument();
    expect(screen.queryByText('gpt-stale')).not.toBeInTheDocument();
  });
});
