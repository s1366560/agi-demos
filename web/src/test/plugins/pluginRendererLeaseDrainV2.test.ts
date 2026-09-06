import { describe, expect, it, vi } from 'vitest';

import {
  RendererGenerationLeaseStoreV2,
  RendererPluginRuntimeV2,
  digestV2,
  parseProfileSnapshotV2,
  webRendererDefinitionsV2,
} from '@agistack/plugin-runtime';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function snapshotAt(generation: number) {
  const { digest: _digest, ...unsigned } = { ...structuredClone(bootstrapProfile), generation };
  return parseProfileSnapshotV2({ ...unsigned, digest: await digestV2(unsigned) });
}

function containsError(value: unknown, expected: Error): boolean {
  return (
    value === expected ||
    (value instanceof AggregateError &&
      value.errors.some((error) => containsError(error, expected)))
  );
}

async function retainedGenerations() {
  let cleanup: () => void | Promise<void> = () => undefined;
  const runtime = new RendererPluginRuntimeV2(
    'web',
    webRendererDefinitionsV2.map((definition, index) => ({
      ...definition,
      async apply(context, config) {
        if (index === 0) {
          const captured = cleanup;
          await context.effect(() => captured, 'root-drain-test');
        }
        return definition.apply(context, config);
      },
    }))
  );
  const store = new RendererGenerationLeaseStoreV2(runtime);
  store.activateRoot();
  const failure = new Error('first generation cleanup failed');
  const failed = deferred();
  cleanup = () => {
    failed.resolve();
    throw failure;
  };
  await runtime.bootstrap(await snapshotAt(401));
  const first = runtime.getSnapshot()!;
  const entered = deferred();
  const blocked = deferred();
  cleanup = async () => {
    entered.resolve();
    await blocked.promise;
  };
  await runtime.replaceBaseline(await snapshotAt(402));
  const second = runtime.getSnapshot()!;
  cleanup = () => undefined;
  await runtime.replaceBaseline(await snapshotAt(403));
  return { runtime, store, failure, first, second, failed, entered, blocked };
}

describe('renderer root lease drain barriers', () => {
  it.each(['commit', 'deactivate'] as const)(
    'waits every retained generation after a %s cleanup failure',
    async (mode) => {
      const fixture = await retainedGenerations();
      const { runtime, store, failure, first, second, failed, entered, blocked } = fixture;
      const operation =
        mode === 'commit' ? store.commit(store.getSnapshot()) : store.deactivateRoot();
      let settled = false;
      const outcome = operation
        .catch((error: unknown) => error)
        .finally(() => {
          settled = true;
        });
      await Promise.all([failed.promise, entered.promise]);
      await vi.waitFor(() => expect(first.disposed).toBe(true));
      expect(settled).toBe(false);
      expect(second.disposed).toBe(false);
      // Deactivation must also capture a previously started commit drain.
      const closing = store.deactivateRoot();
      const closingOutcome = closing.catch((error: unknown) => error);
      expect(store.deactivateRoot()).toBe(closing);
      blocked.resolve();
      const error = await outcome;
      expect(containsError(error, failure)).toBe(true);
      const closeError = await closingOutcome;
      expect(containsError(closeError, failure)).toBe(true);
      expect(second.disposed).toBe(true);
      await expect(store.deactivateRoot()).rejects.toBe(closeError);
      await runtime.close();
    }
  );

  it('lets a replacement root retain its own lease while the prior root drains and fails', async () => {
    const { runtime, store, failure, entered, blocked } = await retainedGenerations();
    const closing = store.deactivateRoot();
    const outcome = closing.catch((error: unknown) => error);
    await entered.promise;
    store.activateRoot();
    const current = runtime.getSnapshot()!;
    expect(current.leaseCount).toBe(1);
    const child = store.acquireGeneration(current);
    blocked.resolve();
    expect(containsError(await outcome, failure)).toBe(true);
    expect(store.getSnapshot().generation).toBe(current);
    expect(current.leaseCount).toBe(2);
    expect(current.disposed).toBe(false);
    await child.release();
    const newClosing = store.deactivateRoot();
    expect(newClosing).not.toBe(closing);
    await newClosing;
    expect(current.leaseCount).toBe(0);
    await runtime.close();
  });

  it('notifies remaining root observers and exposes the original failure as publication diagnostics', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const store = new RendererGenerationLeaseStoreV2(runtime);
    store.activateRoot();
    const failure = new Error('root observer failed');
    store.subscribe(() => {
      throw failure;
    });
    const notified = vi.fn();
    store.subscribe(notified);
    await runtime.bootstrap(await snapshotAt(404));
    expect(notified).toHaveBeenCalledTimes(1);
    expect(
      runtime.lastPublication?.diagnostics.some(
        (diagnostic) => diagnostic.phase === 'observer' && containsError(diagnostic.error, failure)
      )
    ).toBe(true);
    expect(store.getSnapshot().generation).toBe(runtime.getSnapshot());
    await store.deactivateRoot();
    await runtime.close();
  });
});
