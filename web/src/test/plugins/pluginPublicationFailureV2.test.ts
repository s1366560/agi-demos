import { describe, expect, it } from 'vitest';

import {
  DesktopRendererDistributionReconcilerV2,
  LoaderV2,
  GenerationManagerV2,
  PluginSnapshotReconcilerV2,
  RendererPluginRuntimeV2,
  digestV2,
  parseProfileSnapshotV2,
  webRendererDefinitionsV2,
  type ControlPlaneDistributionV2,
  type PluginDefinitionV2,
  type ProfileSnapshotV2,
} from '@agistack/plugin-runtime';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

async function snapshotAt(generation: number): Promise<ProfileSnapshotV2> {
  const base = structuredClone(bootstrapProfile);
  const { digest: _digest, ...unsigned } = { ...base, generation };
  return parseProfileSnapshotV2({ ...unsigned, digest: await digestV2(unsigned) });
}

function distribution(snapshot: ProfileSnapshotV2): ControlPlaneDistributionV2 {
  return {
    schema_version: 2,
    descriptor: {
      profile_id: snapshot.profile_id,
      generation: snapshot.generation,
      digest: snapshot.digest,
    },
    snapshot,
    envelope: {
      version: snapshot.generation,
      nonce: `publication-${snapshot.generation}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

function containsError(value: unknown, expected: Error): boolean {
  if (value === expected) return true;
  if (
    value instanceof AggregateError &&
    value.errors.some((error) => containsError(error, expected))
  ) {
    return true;
  }
  return value instanceof Error && containsError(value.cause, expected);
}

function instrumentedDefinitions(state: {
  cleanupError?: Error;
  activationError?: Error;
  disposed: string[];
}): PluginDefinitionV2[] {
  return webRendererDefinitionsV2.map((definition) => ({
    ...definition,
    async apply(context, config) {
      const cleanupError = state.cleanupError;
      await context.effect(
        () => () => {
          state.disposed.push(context.entryId);
          if (cleanupError) throw cleanupError;
        },
        'publication-test-cleanup'
      );
      const result = await definition.apply(context, config);
      if (state.activationError) throw state.activationError;
      return result;
    },
  }));
}

async function expectCleanupFailure(operation: Promise<unknown>, error: Error): Promise<void> {
  const result = await operation.then(
    () => undefined,
    (failure) => failure
  );
  expect(containsError(result, error)).toBe(true);
}

describe('generation publication commit and cleanup failures', () => {
  it('ACKs the committed identity, notifies every observer and retires the previous generation', async () => {
    const reconciler = new PluginSnapshotReconcilerV2(
      new LoaderV2(webRendererDefinitionsV2, 'web')
    );
    await reconciler.apply(distribution(await snapshotAt(101)));
    const previous = reconciler.manager.current!;
    const observerError = new Error('observer rejected publication');
    let notified = 0;
    const stopFailure = reconciler.manager.subscribe(() => {
      throw observerError;
    });
    const stopNext = reconciler.manager.subscribe(() => {
      notified += 1;
    });
    const snapshot = await snapshotAt(102);
    const receipt = await reconciler.apply(distribution(snapshot));
    expect(receipt).toMatchObject({
      status: 'ack',
      applied_version: 102,
      applied_digest: snapshot.digest,
    });
    expect(notified).toBe(1);
    expect(previous.retired).toBe(true);
    expect(previous.disposed).toBe(true);
    expect(reconciler.manager.current?.snapshot.digest).toBe(snapshot.digest);
    expect(reconciler.manager.lastPublication?.diagnostics).toEqual(
      expect.arrayContaining([expect.objectContaining({ phase: 'observer', error: observerError })])
    );
    expect(await reconciler.apply(distribution(snapshot))).toEqual(receipt);
    expect(notified).toBe(1);
    stopFailure();
    stopNext();
    await reconciler.close();
  });

  it('keeps a bootstrap generation usable when its publication observer throws', async () => {
    const reconciler = new PluginSnapshotReconcilerV2(
      new LoaderV2(webRendererDefinitionsV2, 'web')
    );
    const stop = reconciler.manager.subscribe(() => {
      throw new Error('bootstrap observer');
    });
    await reconciler.bootstrap(await snapshotAt(103));
    const lease = reconciler.manager.acquire();
    expect(lease.generation.disposed).toBe(false);
    expect(lease.generation.fibers.every((fiber) => fiber.phase === 'active')).toBe(true);
    await lease.release();
    stop();
    await reconciler.close();
  });

  it('ACKs publication while retaining the original real effect cleanup failure in diagnostics', async () => {
    const cleanupError = new Error('old effect cleanup failed');
    const state = { cleanupError: cleanupError as Error | undefined, disposed: [] as string[] };
    const reconciler = new PluginSnapshotReconcilerV2(
      new LoaderV2(instrumentedDefinitions(state), 'web')
    );
    await reconciler.apply(distribution(await snapshotAt(104)));
    const previous = reconciler.manager.current!;
    const expectedDisposed = previous.fibers.map((fiber) => fiber.entry.entry_id).reverse();
    state.cleanupError = undefined;
    const snapshot = await snapshotAt(105);
    const receipt = await reconciler.apply(distribution(snapshot));
    expect(receipt).toMatchObject({
      status: 'ack',
      applied_version: 105,
      applied_digest: snapshot.digest,
    });
    expect(state.disposed).toEqual(expectedDisposed);
    const failures = reconciler.manager.lastPublication?.diagnostics.filter(
      (item) => item.phase === 'retirement'
    );
    expect(failures?.some((item) => containsError(item.error, cleanupError))).toBe(true);
    expect(previous.disposed).toBe(true);
    await expectCleanupFailure(previous.dispose(), cleanupError);
    await reconciler.close();
  });

  it('keeps the new identity when the last old lease releases and cleanup fails', async () => {
    const cleanupError = new Error('retained effect cleanup failed');
    const state = { cleanupError: cleanupError as Error | undefined, disposed: [] as string[] };
    const reconciler = new PluginSnapshotReconcilerV2(
      new LoaderV2(instrumentedDefinitions(state), 'web')
    );
    await reconciler.apply(distribution(await snapshotAt(106)));
    const oldLease = reconciler.manager.acquire();
    state.cleanupError = undefined;
    const snapshot = await snapshotAt(107);
    const receipt = await reconciler.apply(distribution(snapshot));
    expect(state.disposed).toEqual([]);
    await expectCleanupFailure(oldLease.release(), cleanupError);
    expect(reconciler.manager.current?.snapshot.digest).toBe(snapshot.digest);
    expect(await reconciler.apply(distribution(snapshot))).toEqual(receipt);
    expect(receipt.status).toBe('ack');
    await reconciler.close();
  });

  it('preserves the last good identity and both original errors when candidate activation and cleanup fail', async () => {
    const state = {
      cleanupError: undefined as Error | undefined,
      activationError: undefined as Error | undefined,
      disposed: [] as string[],
    };
    const loader = new LoaderV2(instrumentedDefinitions(state), 'web');
    const reconciler = new PluginSnapshotReconcilerV2(loader);
    const initial = await snapshotAt(108);
    await reconciler.apply(distribution(initial));
    const previous = reconciler.manager.current;
    state.cleanupError = new Error('candidate cleanup failed');
    state.activationError = new Error('candidate apply failed');
    const candidate = await snapshotAt(109);
    const failure = await loader.stage(candidate).then(
      () => undefined,
      (error) => error
    );
    expect(containsError(failure, state.activationError)).toBe(true);
    expect(containsError(failure, state.cleanupError)).toBe(true);
    const receipt = await reconciler.apply(distribution(candidate));
    expect(receipt).toMatchObject({
      status: 'nack',
      applied_version: 108,
      applied_digest: initial.digest,
    });
    expect(reconciler.manager.current).toBe(previous);
    expect(previous?.disposed).toBe(false);
    await reconciler.close();
  });

  it('closes every real effect despite an observer and disposer failure and repeats the same failure', async () => {
    const cleanupError = new Error('current cleanup failed');
    const observerError = new Error('close observer failed');
    const state = { cleanupError, disposed: [] as string[] };
    const reconciler = new PluginSnapshotReconcilerV2(
      new LoaderV2(instrumentedDefinitions(state), 'web')
    );
    await reconciler.apply(distribution(await snapshotAt(112)));
    const generation = reconciler.manager.current!;
    const expectedDisposed = generation.fibers.map((fiber) => fiber.entry.entry_id).reverse();
    const stop = reconciler.manager.subscribe(() => {
      throw observerError;
    });
    const first = await reconciler.manager.close().then(
      () => undefined,
      (error) => error
    );
    expect(first).toBeInstanceOf(AggregateError);
    expect(containsError(first, cleanupError)).toBe(true);
    expect(containsError(first, observerError)).toBe(true);
    expect(state.disposed).toEqual(expectedDisposed);
    expect(generation.disposed).toBe(true);
    expect(reconciler.manager.current).toBeUndefined();
    const repeated = await reconciler.manager.close().then(
      () => undefined,
      (error) => error
    );
    expect(repeated).toBe(first);
    stop();
  });

  it('retains cloud and local baseline identity after observer failures through the real Desktop reconciler', async () => {
    // The Desktop distribution adapter is shared; use the complete real Web target profile
    // to test its cloud/local identity protocol without faking Desktop application modules.
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const reconciler = new DesktopRendererDistributionReconcilerV2(runtime);
    const stop = runtime.subscribe(() => {
      throw new Error('distribution observer');
    });
    const cloud = distribution(await snapshotAt(110));
    expect(await reconciler.apply({ source: 'cloud', distribution: cloud })).toMatchObject({
      status: 'ack',
    });
    const local = await snapshotAt(111);
    await reconciler.apply({ source: 'local', snapshot: local });
    const localGeneration = runtime.getSnapshot();
    await reconciler.apply({ source: 'local', snapshot: local });
    expect(runtime.getSnapshot()).toBe(localGeneration);
    expect(localGeneration?.disposed).toBe(false);
    expect(await reconciler.apply({ source: 'cloud', distribution: cloud })).toMatchObject({
      status: 'ack',
    });
    expect(runtime.getSnapshot()?.snapshot.digest).toBe(cloud.snapshot.digest);
    stop();
    await reconciler.close();
  });

  it('coalesces same-generation publication while its previous real disposer is blocked', async () => {
    let unblock!: () => void;
    let entered!: () => void;
    const cleanupGate = new Promise<void>((resolve) => {
      unblock = resolve;
    });
    const cleanupEntered = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const cleanupError = new Error('blocked retirement failed');
    let blockCleanup = true;
    const definitions = webRendererDefinitionsV2.map((definition) => ({
      ...definition,
      async apply(
        context: Parameters<PluginDefinitionV2['apply']>[0],
        config: Parameters<PluginDefinitionV2['apply']>[1]
      ) {
        const blocks = blockCleanup;
        await context.effect(
          () => async () => {
            if (!blocks) return;
            entered();
            await cleanupGate;
            throw cleanupError;
          },
          'blocked-retirement'
        );
        return definition.apply(context, config);
      },
    }));
    const loader = new LoaderV2(definitions, 'web');
    const manager = new GenerationManagerV2();
    const previous = await loader.stage(await snapshotAt(113));
    await manager.publish(previous);
    blockCleanup = false;
    const next = await loader.stage(await snapshotAt(114));
    const first = manager.publish(next);
    const repeated = manager.publish(next);
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      expect(repeated).toBe(first);
      await Promise.race([
        cleanupEntered,
        new Promise<void>((_, reject) => {
          timeout = setTimeout(() => reject(new Error('retirement did not start')), 1000);
        }),
      ]);
      let completed = false;
      void first.then(() => {
        completed = true;
      });
      await Promise.resolve();
      expect(completed).toBe(false);
      expect(previous.disposed).toBe(false);
      expect(manager.current).toBe(next);
    } finally {
      clearTimeout(timeout);
      unblock();
    }
    const outcome = await first;
    expect(await repeated).toBe(outcome);
    expect(
      outcome.diagnostics.some(
        (item) => item.phase === 'retirement' && containsError(item.error, cleanupError)
      )
    ).toBe(true);
    expect(previous.disposed).toBe(true);
    await manager.close();
  });

  it('does not cache an outer close over a synchronously reentrant publication', async () => {
    const loader = new LoaderV2(webRendererDefinitionsV2, 'web');
    const manager = new GenerationManagerV2();
    const first = await loader.stage(await snapshotAt(115));
    const next = await loader.stage(await snapshotAt(116));
    await manager.publish(first);
    let reentrantClose: Promise<void> | undefined;
    let reentrantPublication: ReturnType<GenerationManagerV2['publish']> | undefined;
    const stop = manager.subscribe(() => {
      if (manager.current !== undefined) return;
      stop();
      reentrantClose = manager.close();
      reentrantPublication = manager.publish(next);
    });
    const outerClose = manager.close();
    expect(reentrantClose).toBe(outerClose);
    expect(reentrantPublication).toBeDefined();
    await outerClose;
    await reentrantPublication;
    expect(first.disposed).toBe(true);
    expect(manager.current).toBe(next);
    expect(next.disposed).toBe(false);
    const nextClose = manager.close();
    expect(nextClose).not.toBe(outerClose);
    await nextClose;
    expect(next.disposed).toBe(true);
    expect(manager.current).toBeUndefined();
  });
});
