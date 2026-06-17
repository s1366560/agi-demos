import { beforeEach, describe, expect, it, vi } from 'vitest';

import { instanceService } from '@/services/instanceService';
import { useInstanceStore } from '@/stores/instance';

import type {
  InstanceConfigResponse,
  InstanceListResponse,
  InstanceMemberListResponse,
  InstanceMemberResponse,
  InstanceResponse,
} from '@/services/instanceService';

vi.mock('@/services/instanceService', () => ({
  instanceService: {
    list: vi.fn(),
    create: vi.fn(),
    getById: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    scale: vi.fn(),
    restart: vi.fn(),
    getConfig: vi.fn(),
    updateConfig: vi.fn(),
    listMembers: vi.fn(),
    addMember: vi.fn(),
    removeMember: vi.fn(),
    updateMemberRole: vi.fn(),
    searchUsers: vi.fn(),
  },
}));

const deferred = <T>() => {
  let resolve: (value: T | PromiseLike<T>) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
};

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
  id: 'instance-1',
  image_version: 'latest',
  ingress_domain: null,
  llm_providers: {},
  mem_limit: '1Gi',
  mem_request: '256Mi',
  name: 'Instance 1',
  namespace: null,
  pending_config: null,
  proxy_token: null,
  quota_cpu: null,
  quota_max_pods: null,
  quota_memory: null,
  replicas: 1,
  runtime: 'docker',
  service_type: 'ClusterIP',
  slug: 'instance-1',
  status: 'running',
  storage_class: null,
  storage_size: null,
  tenant_id: 'tenant-1',
  theme_color: null,
  updated_at: null,
  workspace_id: null,
  ...overrides,
});

const listResponse = (instances: InstanceResponse[]): InstanceListResponse => ({
  instances,
  total: instances.length,
  page: 1,
  page_size: 20,
});

const member = (overrides: Partial<InstanceMemberResponse> = {}): InstanceMemberResponse => ({
  created_at: '2026-06-17T00:00:00Z',
  id: 'member-1',
  instance_id: 'instance-1',
  role: 'viewer',
  user_avatar_url: null,
  user_email: 'user@example.com',
  user_id: 'user-1',
  user_name: 'User 1',
  ...overrides,
});

const memberListResponse = (members: InstanceMemberResponse[]): InstanceMemberListResponse => ({
  has_more: false,
  limit: 25,
  members,
  offset: 0,
  total: members.length,
});

describe('instance store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useInstanceStore.getState().reset();
  });

  it('ignores stale list instance responses', async () => {
    const oldRequest = deferred<InstanceListResponse>();
    const newRequest = deferred<InstanceListResponse>();
    vi.mocked(instanceService.list)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);

    const firstLoad = useInstanceStore.getState().listInstances({ search: 'old' });
    const secondLoad = useInstanceStore.getState().listInstances({ search: 'new' });

    newRequest.resolve(listResponse([instance({ id: 'new', name: 'New Result' })]));
    await secondLoad;
    expect(useInstanceStore.getState().instances.map((item) => item.id)).toEqual(['new']);

    oldRequest.resolve(listResponse([instance({ id: 'old', name: 'Old Result' })]));
    await firstLoad;
    expect(useInstanceStore.getState().instances.map((item) => item.id)).toEqual(['new']);
    expect(useInstanceStore.getState().isLoading).toBe(false);
  });

  it('ignores stale instance detail responses', async () => {
    const oldRequest = deferred<InstanceResponse>();
    const newRequest = deferred<InstanceResponse>();
    vi.mocked(instanceService.getById)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);

    const firstLoad = useInstanceStore.getState().getInstance('old');
    const secondLoad = useInstanceStore.getState().getInstance('new');

    newRequest.resolve(instance({ id: 'new', name: 'New Detail' }));
    await secondLoad;
    expect(useInstanceStore.getState().currentInstance?.id).toBe('new');

    oldRequest.resolve(instance({ id: 'old', name: 'Old Detail' }));
    await firstLoad;
    expect(useInstanceStore.getState().currentInstance?.id).toBe('new');
    expect(useInstanceStore.getState().isLoading).toBe(false);
  });

  it('ignores stale instance config responses', async () => {
    const oldRequest = deferred<InstanceConfigResponse>();
    const newRequest = deferred<InstanceConfigResponse>();
    vi.mocked(instanceService.getConfig)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);

    const firstLoad = useInstanceStore.getState().getConfig('old');
    const secondLoad = useInstanceStore.getState().getConfig('new');

    newRequest.resolve({ advanced_config: { version: 'new' }, env_vars: {}, llm_providers: {} });
    await secondLoad;
    expect(useInstanceStore.getState().instanceConfig?.advanced_config).toEqual({
      version: 'new',
    });

    oldRequest.resolve({ advanced_config: { version: 'old' }, env_vars: {}, llm_providers: {} });
    await firstLoad;
    expect(useInstanceStore.getState().instanceConfig?.advanced_config).toEqual({
      version: 'new',
    });
  });

  it('ignores stale member list responses', async () => {
    const oldRequest = deferred<InstanceMemberListResponse>();
    const newRequest = deferred<InstanceMemberListResponse>();
    vi.mocked(instanceService.listMembers)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);

    const firstLoad = useInstanceStore.getState().listMembers('old');
    const secondLoad = useInstanceStore.getState().listMembers('new');

    newRequest.resolve(memberListResponse([member({ user_id: 'new-user' })]));
    await secondLoad;
    expect(useInstanceStore.getState().members.map((item) => item.user_id)).toEqual(['new-user']);

    oldRequest.resolve(memberListResponse([member({ user_id: 'old-user' })]));
    await firstLoad;
    expect(useInstanceStore.getState().members.map((item) => item.user_id)).toEqual(['new-user']);
  });
});
