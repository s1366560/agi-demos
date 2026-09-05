import { describe, expect, it } from 'vitest';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  WebOperationCleanupErrorV2,
} from '../../plugins/webOperationAdmissionV2';
async function fixture() {
  const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
  await runtime.bootstrap(profile);
  const admission = new WebOperationAdmissionV2(runtime);
  admission.setEnabled(true);
  return { runtime, admission };
}
describe('production Loader child cleanup accounting', () => {
  it('keeps handled business rejection out of parent cleanup', async () => {
    const { runtime, admission } = await fixture();
    await expect(
      admission.run(async (parent) => {
        await parent
          .runChild(async () => {
            throw new Error('handled business');
          })
          .catch(() => undefined);
        return 'ok';
      })
    ).resolves.toBe('ok');
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    await admission.close();
    await runtime.close();
  });
  it('retains caught settled child resource cleanup through multiple ancestors', async () => {
    const { runtime, admission } = await fixture();
    const cleanup = new Error('device close failed');
    await expect(
      admission.run(async (parent) => {
        await parent
          .runChild(async (child) => {
            await child
              .runChild(async () => {
                throw new WebOperationCleanupErrorV2([cleanup]);
              })
              .catch(() => undefined);
          })
          .catch(() => undefined);
      })
    ).rejects.toBeInstanceOf(WebOperationCleanupErrorV2);
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    await expect(admission.close()).rejects.toMatchObject({ errors: [cleanup] });
    await runtime.close();
  });
  it('drains pending child cleanup and preserves primary business error', async () => {
    const { runtime, admission } = await fixture();
    let finish!: () => void, started!: () => void;
    const wait = new Promise<void>((resolve) => {
      finish = resolve;
    });
    const ready = new Promise<void>((resolve) => {
      started = resolve;
    });
    const cleanup = new Error('device close failed'),
      business = new Error('primary business');
    const task = admission.run(async (parent) => {
      void parent
        .runChild(async () => {
          started();
          await wait;
          throw new WebOperationCleanupErrorV2([cleanup]);
        })
        .catch(() => undefined);
      throw business;
    });
    const rejected = expect(task).rejects.toBe(business);
    await ready;
    expect(runtime.getSnapshot()!.leaseCount).toBe(2);
    finish();
    await rejected;
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    await expect(admission.close()).rejects.toMatchObject({ errors: [cleanup] });
    await runtime.close();
  });
  it('retains caught child lease-release failure with a real Loader lease', async () => {
    const { runtime, admission: original } = await fixture();
    await original.close();
    const cleanup = new Error('child lease release failed');
    const admission = new WebOperationAdmissionV2({
      getSnapshot: runtime.getSnapshot,
      subscribe: runtime.subscribe,
      acquire: () => {
        const lease = runtime.acquire();
        const fork = lease.fork.bind(lease);
        lease.fork = () => {
          const child = fork();
          const release = child.release.bind(child);
          child.release = async () => {
            await release();
            throw cleanup;
          };
          return child;
        };
        return lease;
      },
    });
    admission.setEnabled(true);
    await expect(
      admission.run(async (parent) => {
        await parent.runChild(async () => 'complete').catch(() => undefined);
      })
    ).rejects.toMatchObject({ errors: [cleanup] });
    expect(runtime.getSnapshot()!.leaseCount).toBe(0);
    await expect(admission.close()).rejects.toMatchObject({ errors: [cleanup] });
    await expect(admission.close()).rejects.toMatchObject({ errors: [cleanup] });
    await runtime.close();
  });
});
