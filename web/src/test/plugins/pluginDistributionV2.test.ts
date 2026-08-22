import { describe, expect, it, vi } from 'vitest';

import {
  digestV2,
  LoaderV2,
  parseControlPlaneDistributionV2,
  parseProfileSnapshotV2,
  PluginSnapshotReconcilerV2,
  type ControlPlaneDistributionV2,
  type ProfileSnapshotV2,
  webRendererDefinitionsV2,
} from '@agistack/plugin-runtime';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

async function snapshotAt(
  generation: number,
  transform: (snapshot: ProfileSnapshotV2) => Omit<ProfileSnapshotV2, 'digest'> = (snapshot) => {
    const { digest: _digest, ...payload } = snapshot;
    return payload;
  }
): Promise<ProfileSnapshotV2> {
  const base = await parseProfileSnapshotV2(structuredClone(bootstrapProfile));
  const payload = { ...transform(base), generation };
  return parseProfileSnapshotV2({ ...payload, digest: await digestV2(payload) });
}

function distribution(snapshot: ProfileSnapshotV2, version: number): ControlPlaneDistributionV2 {
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
      nonce: `publication-${version}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

describe('protocol-v2 control-plane distribution', () => {
  it('strictly parses a complete distribution', async () => {
    const snapshot = await snapshotAt(11);

    await expect(parseControlPlaneDistributionV2(distribution(snapshot, 7))).resolves.toEqual(
      distribution(snapshot, 7)
    );
    await expect(
      parseControlPlaneDistributionV2({
        ...distribution(snapshot, 7),
        descriptor: { ...distribution(snapshot, 7).descriptor, generation: 12 },
      })
    ).rejects.toMatchObject({ code: 'distribution_mismatch' });
  });

  it('publishes once and treats the exact publication as idempotent', async () => {
    const snapshot = await snapshotAt(12);
    const reconciler = new PluginSnapshotReconcilerV2(
      new LoaderV2(webRendererDefinitionsV2, 'web')
    );

    const first = await reconciler.apply(distribution(snapshot, 8));
    const repeated = await reconciler.apply(distribution(snapshot, 8));

    expect(first).toMatchObject({
      status: 'ack',
      applied_version: 8,
      applied_digest: snapshot.digest,
    });
    expect(repeated).toEqual(first);
    expect(reconciler.manager.current?.snapshot.digest).toBe(snapshot.digest);
    await reconciler.close();
  });

  it('coalesces concurrent bootstrap attempts into one staged publication', async () => {
    const snapshot = await snapshotAt(18);
    const loader = new LoaderV2(webRendererDefinitionsV2, 'web');
    const stage = vi.spyOn(loader, 'stage');
    const reconciler = new PluginSnapshotReconcilerV2(loader);
    const subscriber = vi.fn();
    const unsubscribe = reconciler.manager.subscribe(subscriber);

    await Promise.all([
      reconciler.bootstrap(snapshot),
      reconciler.bootstrap(snapshot),
      reconciler.bootstrap(snapshot),
    ]);

    expect(stage).toHaveBeenCalledOnce();
    expect(subscriber).toHaveBeenCalledOnce();
    expect(reconciler.manager.current?.snapshot.digest).toBe(snapshot.digest);

    unsubscribe();
    await reconciler.close();
  });

  it('clears a failed bootstrap singleflight so the next attempt can retry', async () => {
    const snapshot = await snapshotAt(19);
    const loader = new LoaderV2(webRendererDefinitionsV2, 'web');
    const failure = new Error('bootstrap stage failed');
    const stage = vi.spyOn(loader, 'stage').mockRejectedValueOnce(failure);
    const reconciler = new PluginSnapshotReconcilerV2(loader);

    await expect(reconciler.bootstrap(snapshot)).rejects.toBe(failure);
    await expect(reconciler.bootstrap(snapshot)).resolves.toBeUndefined();

    expect(stage).toHaveBeenCalledTimes(2);
    expect(reconciler.manager.current?.snapshot.digest).toBe(snapshot.digest);
    await reconciler.close();
  });

  it('disposes a delayed bootstrap when a remote publication wins the race', async () => {
    const bootstrapSnapshot = await snapshotAt(20);
    const remoteSnapshot = await snapshotAt(21);
    const loader = new LoaderV2(webRendererDefinitionsV2, 'web');
    const originalStage = loader.stage.bind(loader);
    let releaseBootstrap: (() => void) | undefined;
    let stagedBootstrap: Awaited<ReturnType<LoaderV2['stage']>> | undefined;
    const bootstrapGate = new Promise<void>((resolve) => {
      releaseBootstrap = resolve;
    });
    const stage = vi.spyOn(loader, 'stage').mockImplementationOnce(async (snapshot) => {
      await bootstrapGate;
      stagedBootstrap = await originalStage(snapshot);
      return stagedBootstrap;
    });
    const reconciler = new PluginSnapshotReconcilerV2(loader);

    const bootstrap = reconciler.bootstrap(bootstrapSnapshot);
    await vi.waitFor(() => expect(stage).toHaveBeenCalledOnce());
    const receipt = await reconciler.apply(distribution(remoteSnapshot, 13));
    releaseBootstrap?.();
    await bootstrap;

    expect(receipt.status).toBe('ack');
    expect(reconciler.manager.current?.snapshot.digest).toBe(remoteSnapshot.digest);
    expect(stagedBootstrap?.disposed).toBe(true);
    await reconciler.close();
  });

  it('waits for an in-flight bootstrap before closing the reconciler', async () => {
    const snapshot = await snapshotAt(22);
    const loader = new LoaderV2(webRendererDefinitionsV2, 'web');
    const originalStage = loader.stage.bind(loader);
    let releaseBootstrap: (() => void) | undefined;
    let stagedBootstrap: Awaited<ReturnType<LoaderV2['stage']>> | undefined;
    const bootstrapGate = new Promise<void>((resolve) => {
      releaseBootstrap = resolve;
    });
    const stage = vi.spyOn(loader, 'stage').mockImplementationOnce(async (candidate) => {
      await bootstrapGate;
      stagedBootstrap = await originalStage(candidate);
      return stagedBootstrap;
    });
    const reconciler = new PluginSnapshotReconcilerV2(loader);

    const bootstrap = reconciler.bootstrap(snapshot);
    await vi.waitFor(() => expect(stage).toHaveBeenCalledOnce());
    const close = reconciler.close();
    releaseBootstrap?.();
    await Promise.all([bootstrap, close]);

    expect(reconciler.manager.current).toBeUndefined();
    expect(stagedBootstrap?.disposed).toBe(true);
  });

  it('waits for an in-flight remote apply before closing the reconciler', async () => {
    const snapshot = await snapshotAt(23);
    const loader = new LoaderV2(webRendererDefinitionsV2, 'web');
    const originalStage = loader.stage.bind(loader);
    let releaseApply: (() => void) | undefined;
    let stagedApply: Awaited<ReturnType<LoaderV2['stage']>> | undefined;
    const applyGate = new Promise<void>((resolve) => {
      releaseApply = resolve;
    });
    const stage = vi.spyOn(loader, 'stage').mockImplementationOnce(async (candidate) => {
      await applyGate;
      stagedApply = await originalStage(candidate);
      return stagedApply;
    });
    const reconciler = new PluginSnapshotReconcilerV2(loader);

    const apply = reconciler.apply(distribution(snapshot, 14));
    await vi.waitFor(() => expect(stage).toHaveBeenCalledOnce());
    const close = reconciler.close();
    releaseApply?.();
    const [receipt] = await Promise.all([apply, close]);

    expect(receipt.status).toBe('ack');
    expect(reconciler.manager.current).toBeUndefined();
    expect(stagedApply?.disposed).toBe(true);
  });

  it('serializes concurrent remote publications in invocation order', async () => {
    const newest = await snapshotAt(24);
    const stale = await snapshotAt(25);
    const loader = new LoaderV2(webRendererDefinitionsV2, 'web');
    const originalStage = loader.stage.bind(loader);
    let releaseNewest: (() => void) | undefined;
    const newestGate = new Promise<void>((resolve) => {
      releaseNewest = resolve;
    });
    const stage = vi.spyOn(loader, 'stage').mockImplementationOnce(async (candidate) => {
      await newestGate;
      return originalStage(candidate);
    });
    const reconciler = new PluginSnapshotReconcilerV2(loader);

    const newestApply = reconciler.apply(distribution(newest, 16));
    await vi.waitFor(() => expect(stage).toHaveBeenCalledOnce());
    const staleApply = reconciler.apply(distribution(stale, 15));
    releaseNewest?.();
    const [newestReceipt, staleReceipt] = await Promise.all([newestApply, staleApply]);

    expect(newestReceipt).toMatchObject({ status: 'ack', applied_version: 16 });
    expect(staleReceipt).toMatchObject({ status: 'nack', error_code: 'stale_version' });
    expect(stage).toHaveBeenCalledOnce();
    expect(reconciler.manager.current?.snapshot.digest).toBe(newest.digest);
    await reconciler.close();
  });

  it('can close and reapply after a StrictMode lifecycle restart', async () => {
    const snapshot = await snapshotAt(17);
    const reconciler = new PluginSnapshotReconcilerV2(
      new LoaderV2(webRendererDefinitionsV2, 'web')
    );
    const first = await reconciler.apply(distribution(snapshot, 12));
    const firstGeneration = reconciler.manager.current;

    await reconciler.close();
    const reapplied = await reconciler.apply(distribution(snapshot, 12));

    expect(first.status).toBe('ack');
    expect(firstGeneration?.disposed).toBe(true);
    expect(reapplied).toMatchObject({
      status: 'ack',
      applied_version: 12,
      applied_digest: snapshot.digest,
    });
    expect(reconciler.manager.current).toBeDefined();
    expect(reconciler.manager.current).not.toBe(firstGeneration);
    await reconciler.close();
  });

  it('nacks stale and same-version conflicting publications without replacing last-good', async () => {
    const current = await snapshotAt(13);
    const conflicting = await snapshotAt(14);
    const reconciler = new PluginSnapshotReconcilerV2(
      new LoaderV2(webRendererDefinitionsV2, 'web')
    );
    await reconciler.apply(distribution(current, 9));

    const stale = await reconciler.apply(distribution(conflicting, 8));
    const conflict = await reconciler.apply(distribution(conflicting, 9));

    expect(stale).toMatchObject({
      status: 'nack',
      error_code: 'stale_version',
      applied_version: 9,
      applied_digest: current.digest,
    });
    expect(conflict).toMatchObject({
      status: 'nack',
      error_code: 'version_conflict',
      applied_version: 9,
      applied_digest: current.digest,
    });
    expect(reconciler.manager.current?.snapshot.digest).toBe(current.digest);
    await reconciler.close();
  });

  it('retains last-good when a complete candidate cannot activate', async () => {
    const emptyProjection = await snapshotAt(15, (snapshot) => {
      const { digest: _digest, ...payload } = snapshot;
      const webModuleRefs = new Set(
        payload.manifests.flatMap((manifest) =>
          manifest.modules
            .filter((module) => module.targets.includes('web'))
            .map((module) => module.module_ref)
        )
      );
      return {
        ...payload,
        entries: payload.entries.map((entry) =>
          webModuleRefs.has(entry.module_ref) ? { ...entry, enabled: false } : entry
        ),
      };
    });
    const nonEmptyProjection = await snapshotAt(16);
    const reconciler = new PluginSnapshotReconcilerV2(new LoaderV2([], 'web'));
    await reconciler.apply(distribution(emptyProjection, 10));

    const receipt = await reconciler.apply(distribution(nonEmptyProjection, 11));

    expect(receipt).toMatchObject({
      status: 'nack',
      error_code: 'generation_apply_failed',
      applied_version: 10,
      applied_digest: emptyProjection.digest,
    });
    expect(reconciler.manager.current?.snapshot.digest).toBe(emptyProjection.digest);
    await reconciler.close();
  });
});
