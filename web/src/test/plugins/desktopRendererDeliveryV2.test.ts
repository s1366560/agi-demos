import { describe, expect, it, vi } from 'vitest';
import {
  RendererPluginRuntimeV2,
  desktopRendererDefinitionsV2,
  digestV2,
  type SnapshotApplyReceiptV2,
} from '@agistack/plugin-runtime';
import {
  DesktopRendererDeliveryReconcilerV2,
  parseDesktopRendererDeliveryV2,
} from '../../../../agi-stack/packages/plugin-runtime/src/desktopRendererDelivery';
import bootstrap from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

async function delivery(
  version = 10,
  nonce = `nonce-${version}`,
  authority = 'cloud-a',
  token = 'ticket-a'
) {
  const snapshot = structuredClone(bootstrap);
  const refs = new Set(desktopRendererDefinitionsV2.map((definition) => definition.moduleRef));
  snapshot.entries = snapshot.entries.filter((entry) => refs.has(entry.module_ref));
  snapshot.generation = version;
  const { digest: _digest, ...unsigned } = snapshot;
  snapshot.digest = await digestV2(unsigned);
  return {
    source: 'cloud' as const,
    authority_id: authority,
    delivery_token: token,
    distribution: {
      schema_version: 2 as const,
      descriptor: { profile_id: snapshot.profile_id, generation: version, digest: snapshot.digest },
      snapshot,
      envelope: {
        version,
        nonce,
        snapshot_digest: snapshot.digest,
        type_url: 'types.memstack.ai/plugin.profile.v2',
      },
    },
  };
}

function setup() {
  let reject = false;
  const cleanup = vi.fn();
  const applies = vi.fn();
  const definitions = desktopRendererDefinitionsV2.map((definition, index) => ({
    ...definition,
    async apply(
      context: Parameters<typeof definition.apply>[0],
      config: Parameters<typeof definition.apply>[1]
    ) {
      applies();
      if (index === 0) {
        await context.effect(() => cleanup, 'owned-real-effect');
        if (reject) throw new Error('candidate readiness rejected');
      }
      return definition.apply(context, config);
    },
  }));
  const runtime = new RendererPluginRuntimeV2('desktop-renderer', definitions);
  const submit = vi.fn(async (_token: string, _receipt: SnapshotApplyReceiptV2) => undefined);
  const reconciler = new DesktopRendererDeliveryReconcilerV2(runtime, submit);
  return {
    runtime,
    submit,
    reconciler,
    cleanup,
    applies,
    reject: () => {
      reject = true;
    },
  };
}

describe('desktop renderer delivery', () => {
  it('retries a failed receipt submission without reapplying or losing the published generation', async () => {
    const test = setup();
    const payload = await delivery();
    const failure = new Error('receipt transport failed');
    test.submit.mockRejectedValueOnce(failure);
    try {
      await expect(test.reconciler.apply(payload)).rejects.toBe(failure);
      const generation = test.runtime.getSnapshot();
      const count = test.applies.mock.calls.length;
      expect(generation).toBeDefined();
      const receipt = test.submit.mock.calls[0]?.[1];
      expect(receipt?.status).toBe('ack');
      expect(await test.reconciler.apply(payload)).toBe(receipt);
      expect(test.submit.mock.calls[1]?.[1]).toBe(receipt);
      expect(test.applies).toHaveBeenCalledTimes(count);
      expect(test.runtime.getSnapshot()).toBe(generation);
    } finally {
      await test.reconciler.close();
    }
  });

  it('submits a real candidate NACK and preserves the old generation', async () => {
    const test = setup();
    try {
      await test.reconciler.apply(await delivery());
      const old = test.runtime.getSnapshot();
      test.reject();
      const receipt = await test.reconciler.apply(await delivery(11));
      expect(receipt?.status).toBe('nack');
      expect(receipt?.applied_version).toBe(10);
      expect(test.submit.mock.calls[1]?.[1]).toBe(receipt);
      expect(test.runtime.getSnapshot()).toBe(old);
      expect(test.cleanup).toHaveBeenCalledTimes(1);
    } finally {
      await test.reconciler.close();
    }
  });

  it('sends new nonces and rotated tokens without resetting the same authority generation', async () => {
    const test = setup();
    try {
      const first = await delivery();
      await test.reconciler.apply(first);
      const generation = test.runtime.getSnapshot();
      const count = test.applies.mock.calls.length;
      await test.reconciler.apply({
        ...first,
        distribution: {
          ...first.distribution,
          envelope: { ...first.distribution.envelope, nonce: 'new-nonce' },
        },
      });
      await test.reconciler.apply({ ...first, delivery_token: 'rotated-ticket' });
      expect(test.submit).toHaveBeenCalledTimes(3);
      expect(test.submit.mock.calls[2]?.[0]).toBe('rotated-ticket');
      expect(test.runtime.getSnapshot()).toBe(generation);
      expect(test.applies).toHaveBeenCalledTimes(count);
      expect(test.cleanup).not.toHaveBeenCalled();
    } finally {
      await test.reconciler.close();
    }
  });

  it('resets ordering across authorities, preserves old leases, and never submits local baselines', async () => {
    const test = setup();
    let release: (() => Promise<void>) | undefined;
    try {
      await test.reconciler.apply(await delivery(20));
      const lease = test.runtime.acquire();
      release = () => lease.release();
      const old = test.runtime.getSnapshot();
      const next = await delivery(1, 'new-authority', 'cloud-b', 'ticket-b');
      expect((await test.reconciler.apply(next))?.status).toBe('ack');
      expect(test.runtime.getSnapshot()).not.toBe(old);
      expect(test.cleanup).not.toHaveBeenCalled();
      await release();
      release = undefined;
      expect(test.cleanup).toHaveBeenCalledTimes(1);
      const local = { source: 'local', snapshot: next.distribution.snapshot };
      await test.reconciler.apply(local);
      const baseline = test.runtime.getSnapshot();
      await test.reconciler.apply(local);
      expect(test.runtime.getSnapshot()).toBe(baseline);
      expect(test.submit).toHaveBeenCalledTimes(2);
      const closing = test.reconciler.close();
      expect(test.reconciler.close()).toBe(closing);
      await closing;
    } finally {
      await release?.();
      await test.reconciler.close();
    }
  });

  it('retires the owner before draining submission and blocks new apply until close completes', async () => {
    const test = setup();
    let unblock!: () => void;
    let entered!: () => void;
    const blocked = new Promise<void>((resolve) => {
      unblock = resolve;
    });
    const started = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const submit = vi.fn(async () => {
      entered();
      await blocked;
    });
    const retire = vi.fn(async () => undefined);
    const reconciler = new DesktopRendererDeliveryReconcilerV2(test.runtime, submit, retire);
    const payload = await delivery();
    const applying = reconciler.apply(payload);
    await started;
    const closing = reconciler.close();
    const next = reconciler.apply(await delivery(1, 'after-close', 'new-owner', 'new-ticket'));
    try {
      await Promise.resolve();
      expect(retire).toHaveBeenCalledTimes(1);
      expect(submit).toHaveBeenCalledTimes(1);
      expect(reconciler.close()).toBe(closing);
    } finally {
      unblock();
      await Promise.allSettled([applying, closing, next]);
    }
    expect((await next)?.status).toBe('ack');
    expect(submit).toHaveBeenCalledTimes(2);
    await reconciler.close();
  });

  it('rejects unknown fields and empty delivery credentials without applying or submitting', async () => {
    const payload = await delivery();
    for (const invalid of [
      null,
      { ...payload, delivery_token: '' },
      { ...payload, authority_id: ' ' },
      { ...payload, credential: 'forbidden' },
      { ...payload, url: 'https://example.test' },
    ]) {
      await expect(parseDesktopRendererDeliveryV2(invalid)).rejects.toMatchObject({
        code: 'desktop_renderer_delivery_invalid',
      });
    }
  });
});
