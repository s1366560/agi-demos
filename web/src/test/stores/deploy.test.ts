import { beforeEach, describe, expect, it, vi } from 'vitest';

import { deployService } from '@/services/deployService';
import { useDeployStore } from '@/stores/deploy';

import type { DeployResponse } from '@/services/deployService';

vi.mock('@/services/deployService', () => ({
  deployService: {
    list: vi.fn(),
    getById: vi.fn(),
    create: vi.fn(),
    markSuccess: vi.fn(),
    markFailed: vi.fn(),
    cancel: vi.fn(),
    getLatestForInstance: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

const deploy = (id: string): DeployResponse => ({
  id,
  instance_id: 'instance-1',
  image_version: 'v1',
  config_snapshot: {},
  status: 'running',
  triggered_by: 'user-1',
  description: null,
  error_message: null,
  started_at: '2026-06-18T00:00:00Z',
  completed_at: null,
  created_at: '2026-06-18T00:00:00Z',
});

describe('deploy store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDeployStore.getState().reset();
  });

  it('ignores list responses that resolve after reset', async () => {
    const request = deferred<Awaited<ReturnType<typeof deployService.list>>>();
    vi.mocked(deployService.list).mockReturnValueOnce(request.promise);

    const load = useDeployStore.getState().listDeploys({ instance_id: 'instance-1' });
    useDeployStore.getState().reset();

    request.resolve({
      deployments: [deploy('stale-deploy')],
      total: 1,
      page: 1,
      page_size: 20,
    });
    await load;

    const state = useDeployStore.getState();
    expect(state.deploys).toEqual([]);
    expect(state.total).toBe(0);
    expect(state.isLoading).toBe(false);
  });

  it('ignores detail responses that resolve after reset', async () => {
    const request = deferred<DeployResponse>();
    vi.mocked(deployService.getById).mockReturnValueOnce(request.promise);

    const load = useDeployStore.getState().getDeploy('stale-deploy');
    useDeployStore.getState().reset();

    request.resolve(deploy('stale-deploy'));
    await load;

    expect(useDeployStore.getState().currentDeploy).toBeNull();
    expect(useDeployStore.getState().isLoading).toBe(false);
  });

  it('does not restore an error when latest deploy lookup rejects after reset', async () => {
    const request = deferred<DeployResponse>();
    vi.mocked(deployService.getLatestForInstance).mockReturnValueOnce(request.promise);

    const load = useDeployStore.getState().getLatestDeploy('instance-1');
    useDeployStore.getState().reset();

    request.reject(new Error('stale failure'));
    await expect(load).rejects.toThrow('stale failure');

    expect(useDeployStore.getState().error).toBeNull();
    expect(useDeployStore.getState().isLoading).toBe(false);
  });
});
