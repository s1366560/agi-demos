import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const { getDistributionMock } = vi.hoisted(() => ({
  getDistributionMock: vi.fn(),
}));

vi.mock('../../services/client/kernelHttpClient', () => ({
  kernelHttpClient: { get: getDistributionMock },
}));

import {
  RendererPluginRuntimeV2,
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

function distribution() {
  return {
    schema_version: 2,
    descriptor: {
      profile_id: bootstrapProfile.profile_id,
      generation: bootstrapProfile.generation,
      digest: bootstrapProfile.digest,
    },
    snapshot: bootstrapProfile,
    envelope: {
      version: 1,
      nonce: 'web-renderer-publication-v2',
      snapshot_digest: bootstrapProfile.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

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
    getDistributionMock.mockResolvedValue(distribution());
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
    getDistributionMock.mockResolvedValue(distribution());
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
      expect(await runWebOperationV2(async (operation) => operation.owner)).not.toBe(firstOwner);
    } finally {
      rendered.unmount();
      useAuthStore.setState(original);
    }
  });

  it('releases last-good when the authenticated generation host becomes disabled', async () => {
    getDistributionMock.mockResolvedValue(distribution());
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
