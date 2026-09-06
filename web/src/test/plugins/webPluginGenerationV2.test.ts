import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { getDistributionMock } = vi.hoisted(() => ({
  getDistributionMock: vi.fn(),
}));

vi.mock('../../services/client/kernelHttpClient', () => ({
  kernelHttpClient: { get: getDistributionMock },
}));

import {
  RendererPluginRuntimeV2,
  digestV2,
  WEB_RENDERER_HOST_SERVICE_V2,
  webRendererDefinitionsV2,
} from '@agistack/plugin-runtime';

import {
  activateWebPluginGenerationRootV2,
  deactivateWebPluginGenerationRootV2,
  startWebPluginGenerationPollingV2,
  type WebPluginDistributionSourceV2,
  useWebPluginGenerationV2,
} from '../../plugins/webPluginGenerationV2';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import { runWebOperationV2 } from '../../plugins/webOperationAdmissionV2';
import { useAuthStore } from '../../stores/auth';
import { useTenantStore } from '../../stores/tenant';
import { useProjectStore } from '../../stores/project';

async function distribution() {
  const refs = new Set(webRendererDefinitionsV2.map((definition) => definition.moduleRef));
  const snapshot = structuredClone(bootstrapProfile);
  snapshot.profile_id = 'web-public-view-v2';
  snapshot.entries = snapshot.entries.filter((entry) => refs.has(entry.module_ref));
  snapshot.manifests = snapshot.manifests
    .map((manifest) => ({
      ...manifest,
      modules: manifest.modules.filter((module) => refs.has(module.module_ref)),
    }))
    .filter((manifest) => manifest.modules.length);
  const { digest: _digest, ...unsigned } = snapshot;
  snapshot.digest = await digestV2(unsigned);
  return { schema_version: 2, target: 'web', view_id: 'public-web-test', snapshot };
}

beforeEach(() => {
  useAuthStore.setState({ isAuthenticated: true, token: 'test-owner' });
});

afterEach(async () => {
  await deactivateWebPluginGenerationRootV2();
  getDistributionMock.mockReset();
  vi.useRealTimers();
});

describe('web plugin generation polling', () => {
  it('loads immediately, polls serially, and stops without discarding last-good', async () => {
    vi.useFakeTimers();
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const source: WebPluginDistributionSourceV2 = vi.fn(async () => distribution());

    const stop = startWebPluginGenerationPollingV2(runtime, source, 100);
    await vi.waitFor(() => {
      expect(runtime.getSnapshot()).toBeDefined();
    });
    await vi.advanceTimersByTimeAsync(100);

    expect(source).toHaveBeenCalledTimes(2);
    expect(runtime.getSnapshot()?.resolve(WEB_RENDERER_HOST_SERVICE_V2, { kind: 'root' })).toEqual({
      target: 'web',
      strategy: 'generation-renderer-host',
    });
    stop();
    await vi.advanceTimersByTimeAsync(200);
    expect(source).toHaveBeenCalledTimes(2);
    expect(runtime.getSnapshot()).toBeDefined();
    await runtime.close();
  });

  it('permits a replacement root while retired operations are still draining', async () => {
    getDistributionMock.mockResolvedValue(await distribution());
    activateWebPluginGenerationRootV2();
    const first = renderHook(() => useWebPluginGenerationV2(true));
    await waitFor(() => expect(first.result.current.status).toBe('ready'));
    let finish!: () => void;
    let started!: () => void;
    const ready = new Promise<void>((resolve) => {
      started = resolve;
    });
    const task = runWebOperationV2(async () => {
      started();
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
    });
    const rejected = expect(task).rejects.toMatchObject({ name: 'AbortError' });
    await ready;
    first.unmount();
    const closing = deactivateWebPluginGenerationRootV2();
    activateWebPluginGenerationRootV2();
    const second = renderHook(() => useWebPluginGenerationV2(true));
    await waitFor(() => expect(second.result.current.status).toBe('ready'));
    finish();
    await rejected;
    await closing;
    await expect(runWebOperationV2(async (operation) => operation.generation)).resolves.toBe(
      second.result.current.generation
    );
    second.unmount();
  });

  it('revokes in-flight work when the auth store logs out and isolates a replacement token', async () => {
    const original = useAuthStore.getState();
    useAuthStore.setState({ isAuthenticated: true, token: 'test-owner-one' });
    getDistributionMock.mockResolvedValue(await distribution());
    activateWebPluginGenerationRootV2();
    const rendered = renderHook(() => useWebPluginGenerationV2(true));
    try {
      await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
      const firstOwner = await runWebOperationV2(async (operation) => operation.owner);
      let finish!: () => void;
      let started!: () => void;
      const ready = new Promise<void>((resolve) => {
        started = resolve;
      });
      const task = runWebOperationV2(async () => {
        started();
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
      });
      const rejected = expect(task).rejects.toMatchObject({ name: 'AbortError' });
      await ready;
      useAuthStore.setState({ isAuthenticated: false, token: null });
      await expect(runWebOperationV2(async () => 'unexpected')).rejects.toThrow(
        'web_operation_generation_unavailable'
      );
      finish();
      await rejected;
      useAuthStore.setState({ isAuthenticated: true, token: 'test-owner-two' });
      await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
      expect(await runWebOperationV2(async (operation) => operation.owner)).not.toBe(firstOwner);
    } finally {
      rendered.unmount();
      useAuthStore.setState(original);
    }
  });

  it('releases last-good when the authenticated generation host becomes disabled', async () => {
    getDistributionMock.mockResolvedValue(await distribution());
    activateWebPluginGenerationRootV2();
    const rendered = renderHook(
      ({ enabled }: { enabled: boolean }) => useWebPluginGenerationV2(enabled),
      { initialProps: { enabled: true } }
    );
    await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
    const firstGeneration = rendered.result.current.generation;

    rendered.rerender({ enabled: false });

    await waitFor(() => expect(firstGeneration?.disposed).toBe(true));
    expect(rendered.result.current).toMatchObject({
      status: 'empty',
      generation: undefined,
      error: undefined,
    });

    rendered.rerender({ enabled: true });
    await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
    expect(rendered.result.current.generation).not.toBe(firstGeneration);
    rendered.unmount();
  });
});

it.each(['token', 'user', 'tenant', 'project'] as const)(
  'synchronously revokes %s identity and ignores its late HTTP response',
  async (field) => {
    const originalAuth = useAuthStore.getState();
    const originalTenant = useTenantStore.getState();
    const originalProject = useProjectStore.getState();
    const requests: Array<{ signal: AbortSignal; resolve: (value: unknown) => void }> = [];
    getDistributionMock.mockImplementation(
      (_path, { signal }) =>
        new Promise((resolve) => {
          requests.push({ signal, resolve });
        })
    );
    const payload = await distribution();
    activateWebPluginGenerationRootV2();
    const rendered = renderHook(() => useWebPluginGenerationV2(true));
    try {
      await waitFor(() => expect(requests).toHaveLength(1));
      await act(async () => requests[0]!.resolve(payload));
      await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
      const oldGeneration = rendered.result.current.generation;
      // Force another request to remain unresolved before the next identity arrives.
      await act(async () => useAuthStore.setState({ token: 'owner-pending' }));
      await waitFor(() => expect(requests).toHaveLength(2));
      act(() => {
        if (field === 'token') useAuthStore.setState({ token: 'owner-next' });
        if (field === 'user')
          useAuthStore.setState({
            user: { ...originalAuth.user, id: 'next-user' } as typeof originalAuth.user,
          });
        if (field === 'tenant')
          useTenantStore.setState({
            currentTenant: {
              ...originalTenant.currentTenant,
              id: 'next-tenant',
            } as typeof originalTenant.currentTenant,
          });
        if (field === 'project')
          useProjectStore.setState({
            currentProject: {
              ...originalProject.currentProject,
              id: 'next-project',
            } as typeof originalProject.currentProject,
          });
      });
      expect(requests[1]!.signal.aborted).toBe(true);
      expect(rendered.result.current.generation).toBeUndefined();
      await expect(runWebOperationV2(async () => 'unexpected')).rejects.toThrow(
        'web_operation_generation_unavailable'
      );
      await waitFor(() => expect(requests).toHaveLength(3));
      await act(async () => requests[2]!.resolve(payload));
      await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
      const nextGeneration = rendered.result.current.generation;
      expect(nextGeneration).not.toBe(oldGeneration);
      await act(async () => requests[1]!.resolve(payload));
      expect(rendered.result.current.generation).toBe(nextGeneration);
      await expect(runWebOperationV2(async (operation) => operation.generation)).resolves.toBe(
        nextGeneration
      );
      expect(
        getDistributionMock.mock.calls.every(([path]) => path === '/platform-plugins/v2/web-view')
      ).toBe(true);
    } finally {
      rendered.unmount();
      useAuthStore.setState(originalAuth);
      useTenantStore.setState(originalTenant);
      useProjectStore.setState(originalProject);
    }
  }
);

it('drains an accepted real candidate before starting the replacement identity source', async () => {
  const { WebPublicViewIdentityV2 } = await import('../../plugins/webPublicViewIdentityV2');
  const { RendererGenerationStatusStoreV2 } = await import('@agistack/plugin-runtime');
  let release!: () => void;
  let entered!: () => void;
  const started = new Promise<void>((resolve) => {
    entered = resolve;
  });
  const blocked = new Promise<void>((resolve) => {
    release = resolve;
  });
  let first = true;
  let cleaned = false;
  const runtime = new RendererPluginRuntimeV2(
    'web',
    webRendererDefinitionsV2.map((definition) => ({
      ...definition,
      async apply(context, config) {
        if (first) {
          first = false;
          await context.effect(async () => {
            entered();
            await blocked;
            return () => {
              cleaned = true;
            };
          });
        }
        return definition.apply(context, config);
      },
    }))
  );
  const admitted: boolean[] = [];
  const lifecycle = new WebPublicViewIdentityV2(
    runtime,
    new RendererGenerationStatusStoreV2(),
    (ready) => admitted.push(ready),
    (error) => {
      throw error;
    }
  );
  const payload = await distribution();
  await lifecycle.replace(async () => payload);
  await started;
  const nextSource = vi.fn(async () => {
    expect(cleaned).toBe(true);
    expect(runtime.getSnapshot()).toBeUndefined();
    return payload;
  });
  const handoff = lifecycle.replace(nextSource);
  expect(lifecycle.getSnapshot()).toBe(false);
  expect(nextSource).not.toHaveBeenCalled();
  release();
  await handoff;
  await waitFor(() => expect(lifecycle.getSnapshot()).toBe(true));
  expect(admitted.filter(Boolean)).toHaveLength(1);
  expect(nextSource).toHaveBeenCalledTimes(1);
  await lifecycle.replace();
  expect(runtime.getSnapshot()).toBeUndefined();
});
