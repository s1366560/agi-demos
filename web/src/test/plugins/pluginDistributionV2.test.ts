import { describe, expect, it } from 'vitest';

import {
  digestV2,
  LoaderV2,
  parseControlPlaneDistributionV2,
  parseProfileSnapshotV2,
  PluginSnapshotReconcilerV2,
  type ControlPlaneDistributionV2,
  type ProfileSnapshotV2,
  webRendererHostDefinitionV2,
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
      new LoaderV2([webRendererHostDefinitionV2], 'web')
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

  it('can close and reapply after a StrictMode lifecycle restart', async () => {
    const snapshot = await snapshotAt(17);
    const reconciler = new PluginSnapshotReconcilerV2(
      new LoaderV2([webRendererHostDefinitionV2], 'web')
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
      new LoaderV2([webRendererHostDefinitionV2], 'web')
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
      return {
        ...payload,
        entries: payload.entries.map((entry) =>
          entry.module_ref === 'builtin://memstack/web/renderer-host'
            ? { ...entry, enabled: false }
            : entry
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
