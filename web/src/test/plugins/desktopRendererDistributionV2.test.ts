import { describe, expect, it, vi } from 'vitest';

import {
  PLUGIN_MODULE_CATALOG_V2,
  createDesktopRendererDefinitionsV2,
  DesktopRendererDistributionReconcilerV2,
  desktopRendererDefinitionsV2,
  digestV2,
  parseDesktopRendererDistributionV2,
  parseProfileSnapshotV2,
  RendererGenerationStatusStoreV2,
  RendererPluginRuntimeV2,
  startRendererGenerationPollingV2,
  type ControlPlaneDistributionV2,
  type ProfileSnapshotV2,
} from '@agistack/plugin-runtime';

import generatedBootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

// This suite exercises shared renderer host/contribution definitions, not Desktop application
// services. Keep the real generated profile entries for those definitions and re-sign the fixture.
const sharedDesktopModules = new Set(desktopRendererDefinitionsV2.map(definition => definition.moduleRef));
const applicationDesktopModules = new Set(PLUGIN_MODULE_CATALOG_V2.modules
  .filter(module => module.targets.includes('desktop-renderer') && !sharedDesktopModules.has(module.module_ref))
  .map(module => module.module_ref));
const bootstrapProfile = structuredClone(generatedBootstrapProfile);
bootstrapProfile.entries = bootstrapProfile.entries.filter(entry => !applicationDesktopModules.has(entry.module_ref));
const { digest: _fixtureDigest, ...fixtureUnsigned } = bootstrapProfile;
bootstrapProfile.digest = await digestV2(fixtureUnsigned);


async function snapshotAt(generation: number): Promise<ProfileSnapshotV2> {
  const snapshot = structuredClone(bootstrapProfile);
  snapshot.generation = generation;
  const { digest: _digest, ...unsigned } = snapshot;
  snapshot.digest = await digestV2(unsigned);
  return parseProfileSnapshotV2(snapshot);
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
      nonce: `desktop-renderer-${version}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

describe('desktop renderer sidecar distribution', () => {
  it('strictly accepts only the exact local or cloud tagged union', async () => {
    const local = await snapshotAt(31);
    const cloud = distribution(await snapshotAt(32), 20);

    await expect(
      parseDesktopRendererDistributionV2({ source: 'local', snapshot: local })
    ).resolves.toEqual({ source: 'local', snapshot: local });
    await expect(
      parseDesktopRendererDistributionV2({ source: 'cloud', distribution: cloud })
    ).resolves.toEqual({ source: 'cloud', distribution: cloud });

    await expect(
      parseDesktopRendererDistributionV2({ source: 'local', snapshot: local, credential: 'x' })
    ).rejects.toMatchObject({ code: 'desktop_renderer_distribution_invalid' });
    await expect(parseDesktopRendererDistributionV2({ source: 'cloud' })).rejects.toMatchObject({
      code: 'desktop_renderer_distribution_invalid',
    });
    await expect(
      parseDesktopRendererDistributionV2({ source: 'remote', distribution: cloud })
    ).rejects.toMatchObject({ code: 'desktop_renderer_distribution_invalid' });
    await expect(parseDesktopRendererDistributionV2(null)).rejects.toMatchObject({
      code: 'desktop_renderer_distribution_invalid',
    });
  });

  it('switches cloud to local to the same cloud publication as three real authorities', async () => {
    const cloud = distribution(await snapshotAt(33), 21);
    const local = await snapshotAt(34);
    const runtime = new RendererPluginRuntimeV2('desktop-renderer', desktopRendererDefinitionsV2);
    const reconciler = new DesktopRendererDistributionReconcilerV2(runtime);
    const published: unknown[] = [];
    const unsubscribe = runtime.subscribe(() => {
      const generation = runtime.getSnapshot();
      if (generation !== undefined) published.push(generation);
    });

    await reconciler.apply({ source: 'cloud', distribution: cloud });
    const firstCloud = runtime.getSnapshot();
    await reconciler.apply({ source: 'cloud', distribution: cloud });
    await reconciler.apply({ source: 'local', snapshot: local });
    const localGeneration = runtime.getSnapshot();
    await reconciler.apply({ source: 'cloud', distribution: cloud });
    const secondCloud = runtime.getSnapshot();

    expect(published).toHaveLength(3);
    expect(firstCloud?.snapshot.digest).toBe(cloud.snapshot.digest);
    expect(localGeneration?.snapshot.digest).toBe(local.digest);
    expect(secondCloud?.snapshot.digest).toBe(cloud.snapshot.digest);
    expect(firstCloud).not.toBe(localGeneration);
    expect(firstCloud).not.toBe(secondCloud);
    expect(localGeneration).not.toBe(secondCloud);

    unsubscribe();
    await reconciler.close();
  });

  it('does not advance source identity when a local candidate fails', async () => {
    let rejectCandidate = false;
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2(() => {
        if (rejectCandidate) throw new Error('desktop_candidate_rejected');
      })
    );
    const reconciler = new DesktopRendererDistributionReconcilerV2(runtime);
    const cloud = distribution(await snapshotAt(35), 22);
    const local = await snapshotAt(36);
    await reconciler.apply({ source: 'cloud', distribution: cloud });
    const lastGood = runtime.getSnapshot();

    rejectCandidate = true;
    await expect(reconciler.apply({ source: 'local', snapshot: local })).rejects.toThrow(
      'desktop_candidate_rejected'
    );
    expect(runtime.getSnapshot()).toBe(lastGood);

    rejectCandidate = false;
    await expect(reconciler.apply({ source: 'local', snapshot: local })).resolves.toBeUndefined();
    expect(runtime.getSnapshot()?.snapshot.digest).toBe(local.digest);

    await reconciler.close();
  });

  it('serializes concurrent local payloads so the same authority publishes once', async () => {
    const runtime = new RendererPluginRuntimeV2('desktop-renderer', desktopRendererDefinitionsV2);
    const reconciler = new DesktopRendererDistributionReconcilerV2(runtime);
    const local = await snapshotAt(39);
    const published: unknown[] = [];
    const unsubscribe = runtime.subscribe(() => {
      const generation = runtime.getSnapshot();
      if (generation !== undefined) published.push(generation);
    });

    await Promise.all([
      reconciler.apply({ source: 'local', snapshot: local }),
      reconciler.apply({ source: 'local', snapshot: local }),
    ]);

    expect(published).toHaveLength(1);
    expect(runtime.getSnapshot()?.snapshot.digest).toBe(local.digest);

    unsubscribe();
    await reconciler.close();
  });

  it('waits for an in-flight source apply before closing the runtime', async () => {
    const runtime = new RendererPluginRuntimeV2('desktop-renderer', desktopRendererDefinitionsV2);
    const reconciler = new DesktopRendererDistributionReconcilerV2(runtime);
    const local = await snapshotAt(40);
    const originalReplace = runtime.replaceBaseline.bind(runtime);
    let releaseReplace: (() => void) | undefined;
    const replaceGate = new Promise<void>((resolve) => {
      releaseReplace = resolve;
    });
    const replace = vi.spyOn(runtime, 'replaceBaseline').mockImplementationOnce(async (value) => {
      await replaceGate;
      await originalReplace(value);
    });

    const apply = reconciler.apply({ source: 'local', snapshot: local });
    await vi.waitFor(() => expect(replace).toHaveBeenCalledOnce());
    const close = reconciler.close();
    releaseReplace?.();
    await Promise.all([apply, close]);

    expect(runtime.getSnapshot()).toBeUndefined();
  });

  it('projects an IPC publication nack as degraded without replacing last-good', async () => {
    const runtime = new RendererPluginRuntimeV2('desktop-renderer', desktopRendererDefinitionsV2);
    const reconciler = new DesktopRendererDistributionReconcilerV2(runtime);
    const statusStore = new RendererGenerationStatusStoreV2();
    const current = distribution(await snapshotAt(37), 24);
    const stale = distribution(await snapshotAt(38), 23);
    await reconciler.apply({ source: 'cloud', distribution: current });
    const lastGood = runtime.getSnapshot();

    const stop = startRendererGenerationPollingV2({
      runtime,
      source: async () => ({ source: 'cloud', distribution: stale }),
      apply: (payload) => reconciler.apply(payload),
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
    await reconciler.close();
  });
});
