import { describe, expect, it, vi } from 'vitest';

import {
  RendererGenerationStatusStoreV2,
  RendererPluginRuntimeV2,
  digestV2,
  parseProfileSnapshotV2,
  startRendererGenerationPollingV2,
  webRendererDefinitionsV2,
  type ControlPlaneDistributionV2,
  type ProfileSnapshotV2,
} from '@agistack/plugin-runtime';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

async function snapshotAt(generation: number): Promise<ProfileSnapshotV2> {
  const { digest: _digest, ...unsigned } = { ...structuredClone(bootstrapProfile), generation };
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
      nonce: `renderer-diagnostics-${snapshot.generation}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

function containsError(value: unknown, expected: Error): boolean {
  return (
    value === expected ||
    (value instanceof AggregateError &&
      value.errors.some((error) => containsError(error, expected)))
  );
}

describe('production renderer publication diagnostics', () => {
  it('keeps ACK and current identity, retains degraded on idempotent polls, and clears on a clean publication', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const statusStore = new RendererGenerationStatusStoreV2();
    const failure = new Error('publication observer failure');
    const unsubscribe = runtime.subscribe(() => {
      throw failure;
    });
    let payload = distribution(await snapshotAt(301));
    const receipts: Awaited<ReturnType<typeof runtime.apply>>[] = [];
    const stop = startRendererGenerationPollingV2({
      runtime,
      statusStore,
      source: async () => payload,
      apply: async (value) => {
        const receipt = await runtime.apply(value);
        receipts.push(receipt);
        return receipt;
      },
      pollIntervalMs: 10,
    });
    try {
      await vi.waitFor(() => expect(receipts.length).toBeGreaterThanOrEqual(2));
      expect(receipts.every((receipt) => receipt.status === 'ack')).toBe(true);
      expect(runtime.getSnapshot()?.snapshot.digest).toBe(payload.snapshot.digest);
      expect(statusStore.getSnapshot().status).toBe('degraded');
      expect(containsError(statusStore.getSnapshot().error, failure)).toBe(true);
      expect(runtime.lastPublication?.diagnostics[0]?.error).toBe(failure);
      const retainedError = statusStore.getSnapshot().error;
      const count = receipts.length;
      unsubscribe();
      await vi.waitFor(() => expect(receipts.length).toBeGreaterThan(count));
      expect(statusStore.getSnapshot().error).toBe(retainedError);
      payload = distribution(await snapshotAt(302));
      await vi.waitFor(() => {
        expect(runtime.getSnapshot()?.snapshot.digest).toBe(payload.snapshot.digest);
        expect(statusStore.getSnapshot().status).toBe('ready');
      });
      expect(runtime.lastPublication?.diagnostics).toEqual([]);
    } finally {
      stop();
      unsubscribe();
      await runtime.close();
    }
  });

  it('exposes original real effect retirement failures without changing successful apply identity', async () => {
    const failure = new Error('old effect failed to clean up');
    let installFailure = true;
    const runtime = new RendererPluginRuntimeV2(
      'web',
      webRendererDefinitionsV2.map((definition) => ({
        ...definition,
        async apply(context, config) {
          if (installFailure) {
            await context.effect(
              () => () => {
                throw failure;
              },
              'renderer-publication-cleanup'
            );
          }
          return definition.apply(context, config);
        },
      }))
    );
    await runtime.bootstrap(await snapshotAt(303));
    const old = runtime.getSnapshot()!;
    installFailure = false;
    const next = distribution(await snapshotAt(304));
    const statusStore = new RendererGenerationStatusStoreV2();
    let receipt: Awaited<ReturnType<typeof runtime.apply>> | undefined;
    const stop = startRendererGenerationPollingV2({
      runtime,
      statusStore,
      source: async () => next,
      apply: async (value) => (receipt = await runtime.apply(value)),
      pollIntervalMs: 10,
    });
    try {
      await vi.waitFor(() => expect(statusStore.getSnapshot().status).toBe('degraded'));
      expect(receipt?.status).toBe('ack');
      expect(runtime.getSnapshot()?.snapshot.digest).toBe(next.snapshot.digest);
      expect(old.retired).toBe(true);
      expect(old.disposed).toBe(true);
      expect(containsError(statusStore.getSnapshot().error, failure)).toBe(true);
      expect(
        runtime.lastPublication?.diagnostics.some(
          (diagnostic) =>
            diagnostic.phase === 'retirement' &&
            diagnostic.generation === old &&
            containsError(diagnostic.error, failure)
        )
      ).toBe(true);
    } finally {
      stop();
      await runtime.close();
    }
  });

  it.each(['bootstrap', 'baseline'] as const)(
    'projects %s diagnostics through the same polling status',
    async (mode) => {
      const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
      const statusStore = new RendererGenerationStatusStoreV2();
      const snapshot = await snapshotAt(mode === 'bootstrap' ? 305 : 306);
      const failure = new Error(`${mode} observer failure`);
      const unsubscribe = runtime.subscribe(() => {
        throw failure;
      });
      const stop = startRendererGenerationPollingV2({
        runtime,
        statusStore,
        ...(mode === 'bootstrap' ? { bootstrap: () => runtime.bootstrap(snapshot) } : {}),
        source: async () => (mode === 'bootstrap' ? null : snapshot),
        apply: async () => {
          await runtime.replaceBaseline(snapshot);
          return undefined;
        },
        pollIntervalMs: 1000,
      });
      try {
        await vi.waitFor(() => expect(statusStore.getSnapshot().status).toBe('degraded'));
        expect(runtime.getSnapshot()?.snapshot.digest).toBe(snapshot.digest);
        expect(runtime.getSnapshot()?.disposed).toBe(false);
        expect(containsError(statusStore.getSnapshot().error, failure)).toBe(true);
        expect(runtime.lastPublication?.diagnostics[0]?.error).toBe(failure);
      } finally {
        stop();
        unsubscribe();
        await runtime.close();
      }
    }
  );
});
