import { readFileSync } from 'node:fs';
import path from 'node:path';

import {
  canonicalJsonV2,
  GenerationManagerV2,
  LoaderV2,
  parseProfileSnapshotV2,
  PluginProtocolV2Error,
  projectSnapshotEntriesV2,
  RuntimeV2Error,
  type PluginDefinitionV2,
  type ProfileSnapshotV2,
} from '@agistack/plugin-runtime';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve(__dirname, '../../../..');
const SNAPSHOT = JSON.parse(
  readFileSync(path.join(ROOT, 'shared/fixtures/platform-plugin-profile.v2.json'), 'utf8')
) as unknown;
const CONFORMANCE = JSON.parse(
  readFileSync(path.join(ROOT, 'shared/fixtures/plugin-runtime-conformance.v2.json'), 'utf8')
) as {
  readonly snapshot_digest: string;
  readonly canonical_json: ReadonlyArray<{
    readonly input: unknown;
    readonly expected: string;
  }>;
  readonly target_projection: Readonly<Record<string, ReadonlyArray<string>>>;
};

function definitions(options: {
  readonly value: number;
  readonly observed: number[];
  readonly disposed: string[];
  readonly fail?: boolean;
}): ReadonlyArray<PluginDefinitionV2> {
  return [
    {
      moduleRef: 'builtin://conformance/root-provider',
      provides: ['service:clock'],
      apply(context) {
        context.provide('service:clock', options.value);
        context.on('choose', () => undefined);
        context.on('choose', () => 'selected');
        context.on('transform', async (value, next) => {
          if (!next) throw new Error('waterfall next is required');
          return next((value as number) + 1);
        });
        context.on('transform', async (value, next) => {
          if (!next) throw new Error('waterfall next is required');
          return next((value as number) * 2);
        });
        return [
          () => options.disposed.push('listener'),
          async () => options.disposed.push('module'),
        ];
      },
    },
    {
      moduleRef: 'builtin://conformance/session-consumer',
      apply(context) {
        options.observed.push(context.require<number>('clock'));
        if (options.fail) throw new RuntimeV2Error('module_failed', 'boom');
      },
    },
  ];
}

describe('plugin runtime v2 conformance', () => {
  it('matches the shared RFC 8785 vector and snapshot digest', async () => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const vector = CONFORMANCE.canonical_json[0];
    if (!vector) throw new Error('canonical vector is missing');

    expect(canonicalJsonV2(vector.input)).toBe(vector.expected);
    expect(snapshot.digest).toBe(CONFORMANCE.snapshot_digest);
    for (const target of [
      'python',
      'rust-server',
      'desktop-sidecar',
      'web',
      'desktop-renderer',
    ] as const) {
      expect(projectSnapshotEntriesV2(snapshot, target).map((entry) => entry.entry_id)).toEqual(
        CONFORMANCE.target_projection[target]
      );
    }
  });

  it('rejects child module targets outside the parent targets', async () => {
    const snapshot = structuredClone(SNAPSHOT) as {
      manifests: Array<{ modules: Array<{ targets: string[] }> }>;
    };
    const child = snapshot.manifests[0]?.modules[1];
    if (!child) throw new Error('child module is missing');
    child.targets.push('desktop-renderer');

    await expect(parseProfileSnapshotV2(snapshot)).rejects.toMatchObject({
      code: 'invalid_parent_targets',
    });
  });

  it.each([[], ['python', 'python']])(
    'rejects non-unique or empty module targets: %j',
    async (targets) => {
      const snapshot = structuredClone(SNAPSHOT) as {
        manifests: Array<{ modules: Array<{ targets: string[] }> }>;
      };
      const module = snapshot.manifests[0]?.modules[0];
      if (!module) throw new Error('root module is missing');
      module.targets = targets;

      await expect(parseProfileSnapshotV2(snapshot)).rejects.toMatchObject({
        code: 'schema_validation_failed',
      });
    }
  );

  it('rejects v1, unknown fields, and digest mutation', async () => {
    await expect(parseProfileSnapshotV2({ schema_version: 1, plugins: [] })).rejects.toMatchObject({
      code: 'incompatible_schema_version',
    } satisfies Partial<PluginProtocolV2Error>);

    await expect(
      parseProfileSnapshotV2({ ...(SNAPSHOT as object), unexpected: true })
    ).rejects.toMatchObject({ code: 'schema_validation_failed' });

    await expect(
      parseProfileSnapshotV2({ ...(SNAPSHOT as object), digest: '0'.repeat(64) })
    ).rejects.toMatchObject({ code: 'digest_mismatch' });
  });

  it('stages provider before consumer and disposes effects in LIFO order', async () => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const observed: number[] = [];
    const disposed: string[] = [];
    const generation = await new LoaderV2(definitions({ value: 7, observed, disposed })).stage(
      snapshot
    );

    expect(observed).toEqual([7]);
    expect(generation.fibers.map((fiber) => fiber.phase)).toEqual(['active', 'active']);
    const context = generation.fibers[0]?.context;
    if (!context) throw new Error('root context is missing');
    expect(await context.bail('choose', null)).toBe('selected');
    expect(await context.waterfall('transform', 2)).toBe(6);

    await generation.dispose();
    expect(disposed).toEqual(['module', 'listener']);
    expect(await context.serial('choose', null)).toEqual([]);
  });

  it('rolls back a failed staging generation without publishing it', async () => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const disposed: string[] = [];
    const manager = new GenerationManagerV2();

    await expect(
      new LoaderV2(definitions({ value: 1, observed: [], disposed, fail: true })).stage(snapshot)
    ).rejects.toMatchObject({ code: 'module_failed' });

    expect(disposed).toEqual(['module', 'listener']);
    expect(() => manager.acquire()).toThrowError(
      expect.objectContaining({ code: 'generation_unavailable' })
    );
  });

  it('skips entries outside the loader data plane target', async () => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const generation = await new LoaderV2([], 'desktop-renderer').stage(snapshot);

    expect(generation.fibers).toEqual([]);
  });

  it('pins old generation services until the old lease is released', async () => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const secondSnapshot: ProfileSnapshotV2 = { ...snapshot, generation: snapshot.generation + 1 };
    const firstDisposed: string[] = [];
    const secondDisposed: string[] = [];
    const first = await new LoaderV2(
      definitions({ value: 1, observed: [], disposed: firstDisposed })
    ).stage(snapshot);
    const second = await new LoaderV2(
      definitions({ value: 2, observed: [], disposed: secondDisposed })
    ).stage(secondSnapshot);
    const scope = snapshot.entries[0]?.scope;
    if (!scope) throw new Error('root scope is missing');
    const manager = new GenerationManagerV2();
    await manager.publish(first);
    const oldLease = manager.acquire();

    await manager.publish(second);
    const newLease = manager.acquire();

    expect(oldLease.generation.resolve<number>('service:clock', scope)).toBe(1);
    expect(newLease.generation.resolve<number>('service:clock', scope)).toBe(2);
    expect(firstDisposed).toEqual([]);
    await oldLease.release();
    expect(firstDisposed).toEqual(['module', 'listener']);
    await newLease.release();
    await manager.close();
    expect(secondDisposed).toEqual(['module', 'listener']);
  });
});
