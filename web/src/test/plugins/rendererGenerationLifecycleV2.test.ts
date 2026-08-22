import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  digestV2,
  projectRendererPluginGenerationStateV2,
  RendererGenerationStatusStoreV2,
  RendererPluginRuntimeV2,
  startRendererGenerationPollingV2,
  webRendererDefinitionsV2,
} from '@agistack/plugin-runtime';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

async function distributionAt(generation: number, version: number) {
  const snapshot = structuredClone(bootstrapProfile);
  snapshot.generation = generation;
  const { digest: _digest, ...unsigned } = snapshot;
  snapshot.digest = await digestV2(unsigned);
  return {
    schema_version: 2,
    descriptor: {
      profile_id: snapshot.profile_id,
      generation: snapshot.generation,
      digest: snapshot.digest,
    },
    snapshot,
    envelope: {
      version,
      nonce: `renderer-lifecycle-${version}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('renderer generation lifecycle', () => {
  it('projects loading, empty, ready, degraded, and error without dropping last-good', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const statusStore = new RendererGenerationStatusStoreV2();

    expect(
      projectRendererPluginGenerationStateV2(true, runtime.getSnapshot(), statusStore.getSnapshot())
    ).toMatchObject({ status: 'loading', generation: undefined, error: undefined });

    statusStore.settle(false);
    expect(
      projectRendererPluginGenerationStateV2(true, runtime.getSnapshot(), statusStore.getSnapshot())
    ).toMatchObject({ status: 'empty', generation: undefined, error: undefined });

    await runtime.apply(await distributionAt(1, 1));
    statusStore.settle(true);
    const ready = projectRendererPluginGenerationStateV2(
      true,
      runtime.getSnapshot(),
      statusStore.getSnapshot()
    );
    expect(ready).toMatchObject({ status: 'ready', error: undefined });

    const refreshError = new Error('refresh failed');
    statusStore.fail(refreshError, true);
    const degraded = projectRendererPluginGenerationStateV2(
      true,
      runtime.getSnapshot(),
      statusStore.getSnapshot()
    );
    expect(degraded).toMatchObject({
      status: 'degraded',
      generation: ready.generation,
      error: refreshError,
    });
    expect(
      projectRendererPluginGenerationStateV2(
        false,
        runtime.getSnapshot(),
        statusStore.getSnapshot()
      )
    ).toMatchObject({ status: 'empty', generation: undefined, error: undefined });

    await runtime.close();
    expect(
      projectRendererPluginGenerationStateV2(true, runtime.getSnapshot(), statusStore.getSnapshot())
    ).toMatchObject({ status: 'error', generation: undefined, error: refreshError });
  });

  it('moves from ready to degraded and back to ready across polling attempts', async () => {
    vi.useFakeTimers();
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const statusStore = new RendererGenerationStatusStoreV2();
    const publication = await distributionAt(1, 1);
    const refreshError = new Error('network unavailable');
    const source = vi
      .fn<(signal: AbortSignal) => Promise<unknown | null>>()
      .mockResolvedValueOnce(publication)
      .mockRejectedValueOnce(refreshError)
      .mockResolvedValueOnce(null);

    const stop = startRendererGenerationPollingV2({
      runtime,
      source,
      statusStore,
      pollIntervalMs: 10_000,
    });

    await vi.waitFor(() => expect(statusStore.getSnapshot().status).toBe('ready'));
    const lastGood = runtime.getSnapshot();

    await vi.advanceTimersByTimeAsync(10_000);
    await vi.waitFor(() =>
      expect(statusStore.getSnapshot()).toMatchObject({
        status: 'degraded',
        error: refreshError,
      })
    );
    expect(runtime.getSnapshot()).toBe(lastGood);

    await vi.advanceTimersByTimeAsync(10_000);
    await vi.waitFor(() =>
      expect(statusStore.getSnapshot()).toMatchObject({ status: 'ready', error: undefined })
    );
    expect(runtime.getSnapshot()).toBe(lastGood);

    stop();
    await runtime.close();
  });

  it('reports empty and error when no generation has ever published', async () => {
    const emptyRuntime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const emptyStatus = new RendererGenerationStatusStoreV2();
    const stopEmpty = startRendererGenerationPollingV2({
      runtime: emptyRuntime,
      source: async () => null,
      statusStore: emptyStatus,
      pollIntervalMs: 60_000,
    });
    await vi.waitFor(() => expect(emptyStatus.getSnapshot().status).toBe('empty'));
    stopEmpty();

    const errorRuntime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const errorStatus = new RendererGenerationStatusStoreV2();
    const failure = new Error('initial load failed');
    const stopError = startRendererGenerationPollingV2({
      runtime: errorRuntime,
      source: async () => {
        throw failure;
      },
      statusStore: errorStatus,
      pollIntervalMs: 60_000,
    });
    await vi.waitFor(() =>
      expect(errorStatus.getSnapshot()).toMatchObject({ status: 'error', error: failure })
    );
    stopError();
  });

  it('projects a structured nack as degraded while retaining last-good', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const statusStore = new RendererGenerationStatusStoreV2();
    const first = await distributionAt(1, 2);
    const stale = await distributionAt(2, 1);
    await runtime.apply(first);
    const lastGood = runtime.getSnapshot();

    const stop = startRendererGenerationPollingV2({
      runtime,
      source: async () => stale,
      statusStore,
      pollIntervalMs: 60_000,
    });

    await vi.waitFor(() => expect(statusStore.getSnapshot().status).toBe('degraded'));
    expect(statusStore.getSnapshot().error).toMatchObject({
      name: 'RuntimeV2Error',
      code: 'stale_version',
    });
    expect(runtime.getSnapshot()).toBe(lastGood);

    stop();
    await runtime.close();
  });

  it('does not report an aborted stopped request as an error', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const statusStore = new RendererGenerationStatusStoreV2();
    const source = vi.fn(
      (signal: AbortSignal) =>
        new Promise<unknown | null>((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
        })
    );
    const stop = startRendererGenerationPollingV2({
      runtime,
      source,
      statusStore,
      pollIntervalMs: 60_000,
    });

    await vi.waitFor(() => expect(source).toHaveBeenCalledOnce());
    stop();
    await Promise.resolve();

    expect(statusStore.getSnapshot()).toMatchObject({ status: 'loading', error: undefined });
  });
});
