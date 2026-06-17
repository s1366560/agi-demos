import type { ReactNode } from 'react';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { InstanceOverview } from '@/pages/tenant/InstanceOverview';
import { instanceService } from '@/services/instanceService';
import { useInstanceStore } from '@/stores/instance';

import type { InstanceMemberResponse, InstanceResponse } from '@/services/instanceService';

const lazyMessageMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock('@/services/instanceService', () => ({
  instanceService: {
    getById: vi.fn(),
    listMembers: vi.fn(),
    restart: vi.fn(),
    scale: vi.fn(),
  },
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyAlert: ({
    action,
    description,
    message,
  }: {
    action?: ReactNode;
    description?: ReactNode;
    message?: ReactNode;
  }) => (
    <div role="alert">
      <div>{message}</div>
      <div>{description}</div>
      {action}
    </div>
  ),
  LazyButton: ({
    children,
    disabled,
    icon,
    loading,
    onClick,
  }: {
    children?: ReactNode;
    disabled?: boolean;
    icon?: ReactNode;
    loading?: boolean;
    onClick?: () => void;
  }) => (
    <button disabled={disabled || loading} onClick={onClick} type="button">
      {icon}
      {children}
    </button>
  ),
  useLazyMessage: () => lazyMessageMock,
}));

const mockService = vi.mocked(instanceService);

function makeInstance(overrides: Partial<InstanceResponse> = {}): InstanceResponse {
  return {
    advanced_config: {},
    agent_display_name: null,
    agent_label: null,
    available_replicas: 1,
    cluster_id: null,
    compute_provider: null,
    cpu_limit: '1',
    cpu_request: '500m',
    created_at: '2026-06-17T00:00:00Z',
    created_by: null,
    current_revision: null,
    description: null,
    env_vars: {},
    health_status: 'healthy',
    hex_position_q: null,
    hex_position_r: null,
    id: 'instance-1',
    image_version: 'latest',
    ingress_domain: null,
    llm_providers: {},
    mem_limit: '1Gi',
    mem_request: '512Mi',
    name: 'Instance One',
    namespace: null,
    pending_config: null,
    proxy_token: null,
    quota_cpu: null,
    quota_max_pods: null,
    quota_memory: null,
    replicas: 1,
    runtime: 'docker',
    service_type: 'ClusterIP',
    slug: 'instance-one',
    status: 'running',
    storage_class: null,
    storage_size: null,
    tenant_id: 'tenant-1',
    theme_color: null,
    updated_at: null,
    workspace_id: null,
    ...overrides,
  };
}

function makeMember(overrides: Partial<InstanceMemberResponse> = {}): InstanceMemberResponse {
  return {
    created_at: '2026-06-17T00:00:00Z',
    id: 'member-1',
    instance_id: 'instance-1',
    role: 'admin',
    user_avatar_url: null,
    user_email: 'member@example.com',
    user_id: 'user-1',
    user_name: 'Member One',
    ...overrides,
  };
}

describe('InstanceOverview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useInstanceStore.getState().reset();
    useInstanceStore.setState({ currentInstance: makeInstance() });
    mockService.getById.mockResolvedValue(makeInstance());
    mockService.listMembers.mockResolvedValue({
      has_more: false,
      limit: 25,
      members: [],
      offset: 0,
      total: 0,
    });
  });

  it('shows a retryable member-load error without an unhandled effect rejection', async () => {
    mockService.listMembers
      .mockRejectedValueOnce(new Error('members service unavailable'))
      .mockResolvedValueOnce({
        has_more: false,
        limit: 25,
        members: [makeMember()],
        offset: 0,
        total: 1,
      });

    render(<InstanceOverview />);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to load instance members');
    });
    expect(screen.getByRole('alert')).toHaveTextContent('members service unavailable');

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(screen.getByText('user-1')).toBeInTheDocument();
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
