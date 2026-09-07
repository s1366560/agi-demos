import { describe, expect, it, vi } from 'vitest';

import {
  GenerationManagerV2,
  LoaderV2,
  PluginSnapshotReconcilerV2,
  digestV2,
  parseProfileSnapshotV2,
  webRendererDefinitionsV2,
  type ControlPlaneDistributionV2,
  type PluginDefinitionV2,
  type ProfileSnapshotV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

async function snapshotAt(generation: number): Promise<ProfileSnapshotV2> {
  const { digest: _digest, ...unsigned } = { ...structuredClone(bootstrapProfile), generation };
  return parseProfileSnapshotV2({ ...unsigned, digest: await digestV2(unsigned) });
}

function publication(snapshot: ProfileSnapshotV2): ControlPlaneDistributionV2 {
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
      nonce: `readiness-${snapshot.generation}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

function definitionsWithEffects(
  applied: string[],
  disposed: string[],
  cleanupError?: Error
): PluginDefinitionV2[] {
  return webRendererDefinitionsV2.map((definition) => ({
    ...definition,
    async apply(context, config) {
      await context.effect(
        () => () => {
          disposed.push(context.entryId);
          if (cleanupError) throw cleanupError;
        },
        'readiness-owned-effect'
      );
      const result = await definition.apply(context, config);
      applied.push(context.entryId);
      return result;
    },
  }));
}

function containsError(value: unknown, expected: Error): boolean {
  return (
    value === expected ||
    (value instanceof AggregateError &&
      value.errors.some((error) => containsError(error, expected))) ||
    (value instanceof Error && value.cause !== undefined && containsError(value.cause, expected))
  );
}

describe('candidate readiness before generation publication', () => {
  it('waits for readiness after every real apply and publishes only when readiness succeeds', async () => {
    const manager = new GenerationManagerV2();
    const previous = await new LoaderV2(webRendererDefinitionsV2, 'web').stage(
      await snapshotAt(301)
    );
    await manager.publish(previous);
    const applied: string[] = [];
    const disposed: string[] = [];
    let candidate: RuntimeGenerationV2 | undefined;
    let allowReady!: () => void;
    const gate = new Promise<void>((resolve) => {
      allowReady = resolve;
    });
    const loader = new LoaderV2(
      definitionsWithEffects(applied, disposed),
      'web',
      undefined,
      async (generation) => {
        candidate = generation;
        expect(generation.fibers.every((fiber) => fiber.phase === 'active')).toBe(true);
        expect(applied).toEqual(generation.fibers.map((fiber) => fiber.entry.entry_id));
        await gate;
      }
    );
    let completed = false;
    const staging = loader.stage(await snapshotAt(302));
    const publishing = staging
      .then((generation) => manager.publish(generation))
      .then((result) => {
        completed = true;
        return result;
      });
    try {
      await vi.waitFor(() => expect(candidate).toBeDefined(), { timeout: 1000 });
      expect(completed).toBe(false);
      expect(manager.current).toBe(previous);
      expect(previous.retired).toBe(false);
      expect(disposed).toEqual([]);
    } finally {
      allowReady();
      await publishing;
    }
    expect(manager.current).toBe(candidate);
    expect(previous.disposed).toBe(true);
    await manager.close();
    expect(disposed).toEqual([...applied].reverse());
  });

  it('NACKs a readiness failure after disposing the entire candidate and retains the last good identity', async () => {
    const applied: string[] = [];
    const disposed: string[] = [];
    const readinessError = new Error('candidate is not ready');
    let failReadiness = false;
    let rejected: RuntimeGenerationV2 | undefined;
    const loader = new LoaderV2(
      definitionsWithEffects(applied, disposed),
      'web',
      undefined,
      async (generation) => {
        if (failReadiness) {
          rejected = generation;
          throw readinessError;
        }
      }
    );
    const reconciler = new PluginSnapshotReconcilerV2(loader);
    const initial = await snapshotAt(303);
    await reconciler.apply(publication(initial));
    const previous = reconciler.manager.current;
    applied.length = 0;
    failReadiness = true;
    const receipt = await reconciler.apply(publication(await snapshotAt(304)));
    expect(receipt).toMatchObject({
      status: 'nack',
      applied_version: 303,
      applied_digest: initial.digest,
    });
    expect(reconciler.manager.current).toBe(previous);
    expect(previous?.retired).toBe(false);
    expect(rejected?.disposed).toBe(true);
    expect(rejected?.fibers.every((fiber) => fiber.phase === 'disposed')).toBe(true);
    expect(disposed).toEqual([...applied].reverse());
    await reconciler.close();
  });

  it('returns the original readiness error when candidate cleanup succeeds', async () => {
    const readinessError = new Error('readiness denied');
    const applied: string[] = [];
    const disposed: string[] = [];
    const loader = new LoaderV2(
      definitionsWithEffects(applied, disposed),
      'web',
      undefined,
      async () => {
        throw readinessError;
      }
    );
    await expect(loader.stage(await snapshotAt(305))).rejects.toBe(readinessError);
    expect(applied.length).toBeGreaterThan(0);
    expect(disposed).toEqual([...applied].reverse());
  });

  it('preserves both original failures and drains every real effect when readiness and cleanup fail', async () => {
    const readinessError = new Error('readiness failed');
    const cleanupError = new Error('readiness cleanup failed');
    const applied: string[] = [];
    const disposed: string[] = [];
    let candidate: RuntimeGenerationV2 | undefined;
    const loader = new LoaderV2(
      definitionsWithEffects(applied, disposed, cleanupError),
      'web',
      undefined,
      async (generation) => {
        candidate = generation;
        throw readinessError;
      }
    );
    const error = await loader.stage(await snapshotAt(306)).then(
      () => undefined,
      (failure) => failure
    );
    expect(error).toBeInstanceOf(AggregateError);
    expect(containsError(error, readinessError)).toBe(true);
    expect(containsError(error, cleanupError)).toBe(true);
    expect(candidate?.disposed).toBe(true);
    expect(disposed).toEqual([...applied].reverse());
    expect(candidate?.fibers.every((fiber) => fiber.phase === 'disposed')).toBe(true);
  });
});
