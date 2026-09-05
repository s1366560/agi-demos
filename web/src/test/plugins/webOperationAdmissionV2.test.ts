import { describe, expect, it } from 'vitest';
import {
  digestV2,
  RendererPluginRuntimeV2,
  webRendererDefinitionsV2,
} from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
  installWebOperationAdmissionV2,
  type WebOperationContextV2,
} from '../../plugins/webOperationAdmissionV2';
function gate() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
async function fixture() {
  const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
  await runtime.bootstrap(profile);
  const admission = new WebOperationAdmissionV2(runtime);
  admission.setEnabled(true);
  return { runtime, admission };
}
async function replace(runtime: RendererPluginRuntimeV2) {
  const { digest: _digest, ...snapshot } = structuredClone(profile);
  snapshot.generation += 1;
  await runtime.replaceBaseline({ ...snapshot, digest: await digestV2(snapshot) });
}
describe('Web operation admission with production Loader', () => {
  it('rejects unavailable and disabled business admission before work', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const admission = new WebOperationAdmissionV2(runtime);
    let calls = 0;
    await expect(
      admission.run(async () => {
        calls++;
      })
    ).rejects.toThrow();
    admission.setEnabled(true);
    await expect(
      admission.run(async () => {
        calls++;
      })
    ).rejects.toThrow();
    expect(calls).toBe(0);
    await admission.close();
    await runtime.close();
  });
  it('aborts on publication but retains the old generation until work settles', async () => {
    const { runtime, admission } = await fixture();
    const old = runtime.getSnapshot()!;
    const started = gate(),
      finish = gate();
    let operation!: WebOperationContextV2;
    const task = admission.run(async (context) => {
      operation = context;
      started.resolve();
      await finish.promise;
      return 'stale';
    });
    const rejection = expect(task).rejects.toMatchObject({ name: 'AbortError' });
    await started.promise;
    await replace(runtime);
    expect(operation.signal.aborted).toBe(true);
    expect(old.disposed).toBe(false);
    expect(old.leaseCount).toBe(1);
    finish.resolve();
    await rejection;
    expect(old.disposed).toBe(true);
    await admission.close();
    await runtime.close();
  });
  it('keeps the current owner and its operation alive when a candidate is rejected', async () => {
    const { runtime, admission } = await fixture();
    const snapshot = admission.getSnapshot();
    const generation = runtime.getSnapshot();
    const started = gate(),
      finish = gate();
    let operation!: WebOperationContextV2;
    const task = admission.run(async (context) => {
      operation = context;
      started.resolve();
      await finish.promise;
      return 'last-good';
    });
    await started.promise;
    const { digest: _digest, ...candidate } = structuredClone(profile);
    candidate.generation += 1;
    const host = candidate.entries.find((entry) => entry.entry_id === 'builtin-web-renderer-host')!;
    host.config = { ...host.config, strategy: 'invalid-candidate-strategy' };
    await expect(
      runtime.replaceBaseline({ ...candidate, digest: await digestV2(candidate) })
    ).rejects.toThrow();
    expect(runtime.getSnapshot()).toBe(generation);
    expect(admission.getSnapshot()).toBe(snapshot);
    expect(operation.signal.aborted).toBe(false);
    finish.resolve();
    await expect(task).resolves.toBe('last-good');
    await admission.close();
    await runtime.close();
  });

  it('joins admitted children before releasing a completed parent', async () => {
    const { runtime, admission } = await fixture();
    const generation = runtime.getSnapshot()!;
    const started = gate(),
      finish = gate();
    let child!: Promise<void>;
    const parent = admission.run(async (operation) => {
      child = operation.runChild(async (context) => {
        expect(context.generation).toBe(operation.generation);
        started.resolve();
        await finish.promise;
      });
      return 'done';
    });
    await started.promise;
    expect(generation.leaseCount).toBe(2);
    finish.resolve();
    await child;
    await expect(parent).resolves.toBe('done');
    expect(generation.leaseCount).toBe(0);
    await admission.close();
    await runtime.close();
  });
  it('invalidates identity work and drains cancellation before close', async () => {
    const { runtime, admission } = await fixture();
    const started = gate(),
      finish = gate();
    const task = admission.run(async (operation) => {
      started.resolve();
      await finish.promise;
      operation.check();
    });
    const rejection = expect(task).rejects.toMatchObject({ name: 'AbortError' });
    await started.promise;
    admission.invalidate();
    let closed = false;
    const close = admission.close().then(() => {
      closed = true;
    });
    await Promise.resolve();
    expect(closed).toBe(false);
    expect(runtime.getSnapshot()!.leaseCount).toBe(1);
    finish.resolve();
    await rejection;
    await close;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    await runtime.close();
  });
  it('isolates cache owners across identity and generation changes while children inherit', async () => {
    const { runtime, admission } = await fixture();
    const owner = await admission.run(async (operation) => {
      await operation.runChild(async (child) => {
        expect(child.owner).toBe(operation.owner);
      });
      return operation.owner;
    });
    expect(await admission.run(async (operation) => operation.owner)).toBe(owner);
    admission.invalidate();
    const identityOwner = await admission.run(async (operation) => operation.owner);
    expect(identityOwner).not.toBe(owner);
    await replace(runtime);
    const generationOwner = await admission.run(async (operation) => operation.owner);
    expect(generationOwner).not.toBe(identityOwner);
    expect(Object.keys(generationOwner)).toEqual([]);
    await admission.close();
    await runtime.close();
  });
  it('publishes stable availability only after old operations are synchronously revoked', async () => {
    const { runtime, admission } = await fixture();
    const initial = admission.getSnapshot();
    expect(initial.available).toBe(true);
    admission.setEnabled(true);
    expect(admission.getSnapshot()).toBe(initial);
    const started = gate(),
      finish = gate();
    let context!: WebOperationContextV2;
    const task = admission.run(async (operation) => {
      context = operation;
      started.resolve();
      await finish.promise;
    });
    const rejected = expect(task).rejects.toMatchObject({ name: 'AbortError' });
    await started.promise;
    let notifications = 0;
    const unsubscribe = admission.subscribe(() => {
      notifications++;
      expect(context.signal.aborted).toBe(true);
    });
    admission.invalidate();
    expect(notifications).toBe(1);
    expect(admission.getSnapshot().owner).not.toBe(initial.owner);
    expect(admission.getSnapshot().available).toBe(true);
    admission.setEnabled(false);
    expect(admission.getSnapshot().available).toBe(false);
    const disabled = admission.getSnapshot();
    admission.setEnabled(false);
    expect(admission.getSnapshot()).toBe(disabled);
    finish.resolve();
    await rejected;
    unsubscribe();
    await admission.close();
    await runtime.close();
  });

  it('notifies mounted consumers across root replacement without old detach hiding the new root', async () => {
    const first = await fixture();
    const second = await fixture();
    const snapshots: object[] = [];
    const unsubscribe = subscribeWebOperationAvailabilityV2(() => {
      snapshots.push(getWebOperationAvailabilityV2());
    });
    const detachFirst = installWebOperationAdmissionV2(first.admission);
    expect(getWebOperationAvailabilityV2()).toBe(first.admission.getSnapshot());
    detachFirst();
    expect(getWebOperationAvailabilityV2().available).toBe(false);
    const detachSecond = installWebOperationAdmissionV2(second.admission);
    try {
      detachFirst();
      expect(getWebOperationAvailabilityV2()).toBe(second.admission.getSnapshot());
      first.admission.invalidate();
      expect(snapshots).toHaveLength(3);
      second.admission.invalidate();
      expect(snapshots).toHaveLength(4);
      expect(snapshots.at(-1)).toBe(second.admission.getSnapshot());
    } finally {
      detachSecond();
      unsubscribe();
      await first.admission.close();
      await second.admission.close();
      await first.runtime.close();
      await second.runtime.close();
    }
  });

  it('publishes availability when a production generation arrives and when it closes', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const admission = new WebOperationAdmissionV2(runtime);
    admission.setEnabled(true);
    expect(admission.getSnapshot().available).toBe(false);
    await runtime.bootstrap(profile);
    expect(admission.getSnapshot().available).toBe(true);
    const owner = admission.getSnapshot().owner;
    await runtime.close();
    expect(admission.getSnapshot().available).toBe(false);
    expect(admission.getSnapshot().owner).not.toBe(owner);
    await admission.close();
  });

  it('rejects forged and released parents', async () => {
    const { runtime, admission } = await fixture();
    let retained!: WebOperationContextV2;
    await admission.run(async (operation) => {
      retained = operation;
    });
    await expect(admission.run(async () => {}, { parent: retained })).rejects.toThrow();
    await expect(
      admission.run(async () => {}, { parent: {} as WebOperationContextV2 })
    ).rejects.toThrow();
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    await admission.close();
    await runtime.close();
  });
  it('keeps caller cancellation linked while lease release is pending', async () => {
    const { runtime, admission: original } = await fixture();
    await original.close();
    const releasing = gate(),
      finish = gate();
    const admission = new WebOperationAdmissionV2({
      subscribe: runtime.subscribe,
      getSnapshot: runtime.getSnapshot,
      acquire: () => {
        const lease = runtime.acquire();
        const release = lease.release.bind(lease);
        lease.release = async () => {
          releasing.resolve();
          await finish.promise;
          await release();
        };
        return lease;
      },
    });
    admission.setEnabled(true);
    const caller = new AbortController();
    const task = admission.run(async () => 'stale', { signal: caller.signal });
    const rejected = expect(task).rejects.toMatchObject({ name: 'AbortError' });
    await releasing.promise;
    caller.abort();
    finish.resolve();
    await rejected;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    await admission.close();
    await runtime.close();
  });
  it('reports lease cleanup failure after cancellation to both the operation and root close', async () => {
    const { runtime, admission: original } = await fixture();
    await original.close();
    const started = gate(),
      finish = gate();
    const cleanupFailure = new Error('release failure');
    const admission = new WebOperationAdmissionV2({
      subscribe: runtime.subscribe,
      getSnapshot: runtime.getSnapshot,
      acquire: () => {
        const lease = runtime.acquire();
        const release = lease.release.bind(lease);
        lease.release = async () => {
          await release();
          throw cleanupFailure;
        };
        return lease;
      },
    });
    admission.setEnabled(true);
    const task = admission.run(async () => {
      started.resolve();
      await finish.promise;
    });
    const rejected = expect(task).rejects.toMatchObject({
      name: 'AggregateError',
      errors: [expect.objectContaining({ name: 'AbortError' }), cleanupFailure],
    });
    await started.promise;
    const closing = admission.close();
    const closeRejected = expect(closing).rejects.toMatchObject({
      name: 'AggregateError',
      errors: [cleanupFailure],
    });
    finish.resolve();
    await rejected;
    await closeRejected;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    await runtime.close();
  });

  it('preserves primary failure over lease cleanup failure', async () => {
    const { runtime, admission: original } = await fixture();
    await original.close();
    const admission = new WebOperationAdmissionV2({
      subscribe: runtime.subscribe,
      getSnapshot: runtime.getSnapshot,
      acquire: () => {
        const lease = runtime.acquire();
        const release = lease.release.bind(lease);
        lease.release = async () => {
          await release();
          throw new Error('release failure');
        };
        return lease;
      },
    });
    admission.setEnabled(true);
    await expect(
      admission.run(async () => {
        throw new Error('primary');
      })
    ).rejects.toThrow('primary');
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    await admission.close();
    await runtime.close();
  });
});
