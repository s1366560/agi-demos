import { readFileSync } from 'node:fs';
import path from 'node:path';

import {
  canonicalJsonV2,
  type ContextV2,
  digestV2,
  type PluginContractV2,
  GenerationManagerV2,
  LoaderV2,
  parseProfileSnapshotV2,
  PluginProtocolV2Error,
  projectSnapshotEntriesV2,
  RuntimeV2Error,
  type PluginDefinitionV2,
  type PluginModuleV2,
  type ProfileEntryV2,
  type ProfileSnapshotV2,
} from '@agistack/plugin-runtime';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve(__dirname, '../../../..');
const SNAPSHOT = JSON.parse(
  readFileSync(path.join(ROOT, 'shared/fixtures/platform-plugin-profile.v2.json'), 'utf8')
) as MutableSnapshot;
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
const CONTRACT_CONFORMANCE = JSON.parse(
  readFileSync(path.join(ROOT, 'shared/fixtures/plugin-contract-conformance.v2.json'), 'utf8')
) as {
  readonly negative_cases: ReadonlyArray<ContractNegativeCase>;
  readonly runtime_completeness_cases: ReadonlyArray<RuntimeCompletenessCase>;
};

type MutablePluginModule = Omit<PluginModuleV2, 'contract' | 'contract_digest'> & {
  contract: PluginContractV2;
  contract_digest: string;
};

interface MutableSnapshot {
  digest: string;
  generation: number;
  manifests: Array<{
    modules: MutablePluginModule[];
  }>;
  entries: ProfileEntryV2[];
  [key: string]: unknown;
}

interface MutationOperation {
  readonly operation: 'add' | 'remove' | 'replace';
  readonly path: string;
  readonly value?: unknown;
}

interface ContractNegativeCase {
  readonly name: string;
  readonly expected_error: string;
  readonly mutation: MutationOperation & {
    readonly operations?: ReadonlyArray<MutationOperation>;
    readonly refresh_contract_digest?: boolean;
  };
}

interface RuntimeCompletenessCase {
  readonly name: string;
  readonly expected_error: string;
  readonly module_ref: string;
  readonly operation: 'dispatch' | 'on' | 'provide' | 'require';
}

interface DefinitionOptions {
  readonly value: number;
  readonly observed: number[];
  readonly disposed: string[];
  readonly contexts?: ContextV2[];
  readonly eventOrder?: string[];
  readonly applied?: string[];
  readonly fail?: boolean;
  readonly invalidChooseResult?: boolean;
}

function definitions(
  snapshot: ProfileSnapshotV2,
  options: DefinitionOptions
): ReadonlyArray<PluginDefinitionV2> {
  const digests = moduleContractDigests(snapshot);
  return [
    {
      moduleRef: 'builtin://conformance/root-provider',
      contractDigest: requiredValue(digests, 'builtin://conformance/root-provider'),
      apply(context) {
        options.applied?.push('root-provider');
        context.provide('service:clock', options.value);
        context.on('notify', () => ['notify-1']);
        context.on('notify', () => ['notify-2']);
        context.on('audit', async () => {
          options.eventOrder?.push('audit-1:start');
          await Promise.resolve();
          options.eventOrder?.push('audit-1:end');
          return ['audit-1'];
        });
        context.on('audit', () => {
          options.eventOrder?.push('audit-2');
          return ['audit-2'];
        });
        context.on('choose', () => null);
        context.on('choose', () => (options.invalidChooseResult ? 7 : 'selected'));
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
          async () => {
            options.disposed.push('module');
          },
        ];
      },
    },
    {
      moduleRef: 'builtin://conformance/session-consumer',
      contractDigest: requiredValue(digests, 'builtin://conformance/session-consumer'),
      apply(context) {
        options.applied?.push('session-consumer');
        options.observed.push(context.require<number>('clock'));
        options.contexts?.push(context);
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
    const snapshot = structuredClone(SNAPSHOT);
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
      const snapshot = structuredClone(SNAPSHOT);
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

  it.each(CONTRACT_CONFORMANCE.negative_cases)(
    'matches the shared contract rejection for $name',
    async (testCase) => {
      const raw = await mutatedSnapshot(testCase);
      if (
        ['contract_digest_mismatch', 'event_contract_mismatch', 'invalid_contract_schema'].includes(
          testCase.expected_error
        )
      ) {
        await expect(parseProfileSnapshotV2(raw)).rejects.toMatchObject({
          code: testCase.expected_error,
        });
        return;
      }

      const snapshot = await parseProfileSnapshotV2(raw);
      const applied: string[] = [];
      const loader = webLoader(
        snapshot,
        definitions(snapshot, { value: 7, observed: [], disposed: [], applied })
      );

      await expect(loader.stage(snapshot)).rejects.toMatchObject({ code: testCase.expected_error });
      expect(applied).toEqual([]);
    }
  );

  it('rejects runtime and target-catalog digest drift before apply', async () => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const applied: string[] = [];
    const valid = definitions(snapshot, { value: 7, observed: [], disposed: [], applied });
    const runtimeMismatch = valid.map((definition, index) =>
      index === 0 ? { ...definition, contractDigest: `sha256:${'0'.repeat(64)}` } : definition
    );

    await expect(webLoader(snapshot, runtimeMismatch).stage(snapshot)).rejects.toMatchObject({
      code: 'contract_digest_mismatch',
    });
    expect(applied).toEqual([]);

    const catalogMismatch = { ...targetCatalog(snapshot) };
    catalogMismatch['builtin://conformance/root-provider'] = `sha256:${'1'.repeat(64)}`;
    await expect(new LoaderV2(valid, 'web', catalogMismatch).stage(snapshot)).rejects.toMatchObject(
      {
        code: 'contract_digest_mismatch',
      }
    );
    expect(applied).toEqual([]);

    delete catalogMismatch['builtin://conformance/root-provider'];
    await expect(new LoaderV2(valid, 'web', catalogMismatch).stage(snapshot)).rejects.toMatchObject(
      {
        code: 'missing_target_catalog',
      }
    );
    expect(applied).toEqual([]);
  });

  it.each(CONTRACT_CONFORMANCE.runtime_completeness_cases)(
    'enforces runtime contract completeness for $operation $name',
    async (testCase) => {
      const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
      const base = definitions(snapshot, { value: 7, observed: [], disposed: [] });
      const probe = base.map((definition) =>
        definition.moduleRef === testCase.module_ref
          ? { ...definition, apply: completenessProbe(testCase) }
          : definition
      );

      await expect(webLoader(snapshot, probe).stage(snapshot)).rejects.toMatchObject({
        code: testCase.expected_error,
      });
    }
  );

  it('uses declared event modes and validates event payloads and results', async () => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const contexts: ContextV2[] = [];
    const eventOrder: string[] = [];
    const generation = await webLoader(
      snapshot,
      definitions(snapshot, {
        value: 7,
        observed: [],
        disposed: [],
        contexts,
        eventOrder,
      })
    ).stage(snapshot);
    const context = contexts[0];
    if (!context) throw new Error('consumer context is missing');

    expect(await context.dispatch('notify', {})).toEqual([['notify-1'], ['notify-2']]);
    expect(await context.dispatch('audit', {})).toEqual([['audit-1'], ['audit-2']]);
    expect(eventOrder).toEqual(['audit-1:start', 'audit-1:end', 'audit-2']);
    expect(await context.dispatch('choose', null)).toBe('selected');
    expect(await context.dispatch('transform', 2)).toBe(6);
    await expect(context.dispatch('transform', 'not-an-integer')).rejects.toMatchObject({
      code: 'invalid_event_payload',
    });
    await expect(context.dispatch('undeclared-event', {})).rejects.toMatchObject({
      code: 'undeclared_event_dispatch',
    });

    await generation.dispose();
  });

  it('rejects an event handler result outside the declared result schema', async () => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const contexts: ContextV2[] = [];
    const generation = await webLoader(
      snapshot,
      definitions(snapshot, {
        value: 7,
        observed: [],
        disposed: [],
        contexts,
        invalidChooseResult: true,
      })
    ).stage(snapshot);
    const context = contexts[0];
    if (!context) throw new Error('consumer context is missing');

    await expect(context.dispatch('choose', null)).rejects.toMatchObject({
      code: 'invalid_event_result',
    });
    await generation.dispose();
  });

  it.each([
    ['provide', 'provide_version_mismatch'],
    ['require', 'require_version_mismatch'],
  ] as const)('rejects an explicit incompatible %s version', async (operation, expectedCode) => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const base = definitions(snapshot, { value: 7, observed: [], disposed: [] });
    const mismatched = base.map((definition) => {
      if (operation === 'provide' && definition.moduleRef.endsWith('root-provider')) {
        return {
          ...definition,
          apply(context: ContextV2) {
            context.provide('service:clock', 7, { version: '2.0.0' });
          },
        };
      }
      if (operation === 'require' && definition.moduleRef.endsWith('session-consumer')) {
        return {
          ...definition,
          apply(context: ContextV2) {
            context.require('clock', '2.0.0');
          },
        };
      }
      return definition;
    });

    await expect(webLoader(snapshot, mismatched).stage(snapshot)).rejects.toMatchObject({
      code: expectedCode,
    });
  });

  it('stages provider before consumer and disposes effects in LIFO order', async () => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const observed: number[] = [];
    const disposed: string[] = [];
    const generation = await webLoader(
      snapshot,
      definitions(snapshot, { value: 7, observed, disposed })
    ).stage(snapshot);

    expect(observed).toEqual([7]);
    expect(generation.fibers.map((fiber) => fiber.phase)).toEqual(['active', 'active']);
    await generation.dispose();
    expect(disposed).toEqual(['module', 'listener']);
  });

  it('keeps same-scope activation and listeners in profile declaration order', async () => {
    const snapshot = await orderedSiblingSnapshot();
    const applied: string[] = [];
    const contexts: ContextV2[] = [];
    const digests = moduleContractDigests(snapshot);
    const moduleDefinitions = [
      ['builtin://conformance/declared-first', 'first'],
      ['builtin://conformance/declared-second', 'second'],
    ].map(([moduleRef, label]): PluginDefinitionV2 => {
      if (!moduleRef || !label) throw new Error('ordered module fixture is incomplete');
      return {
        moduleRef,
        contractDigest: requiredValue(digests, moduleRef),
        apply(context) {
          applied.push(label);
          contexts.push(context);
          context.on('ordered', () => label);
        },
      };
    });
    const generation = await webLoader(snapshot, moduleDefinitions).stage(snapshot);

    expect(applied).toEqual(['first', 'second']);
    const context = contexts[0];
    if (!context) throw new Error('ordered listener context is missing');
    await expect(context.dispatch('ordered', {})).resolves.toEqual(['first', 'second']);
    await generation.dispose();
  });

  it('activates dependencies before an earlier declared consumer', async () => {
    const raw = structuredClone(SNAPSHOT);
    raw.entries.reverse();
    await refreshSnapshotDigest(raw);
    const snapshot = await parseProfileSnapshotV2(raw);
    const applied: string[] = [];
    const generation = await webLoader(
      snapshot,
      definitions(snapshot, { value: 7, observed: [], disposed: [], applied })
    ).stage(snapshot);

    expect(applied).toEqual(['root-provider', 'session-consumer']);
    await generation.dispose();
  });

  it('rolls back a failed staging generation without publishing it', async () => {
    const snapshot = await parseProfileSnapshotV2(SNAPSHOT);
    const disposed: string[] = [];
    const manager = new GenerationManagerV2();

    await expect(
      webLoader(
        snapshot,
        definitions(snapshot, { value: 1, observed: [], disposed, fail: true })
      ).stage(snapshot)
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
    const rawSecond = structuredClone(SNAPSHOT);
    rawSecond.generation += 1;
    await refreshSnapshotDigest(rawSecond);
    const secondSnapshot = await parseProfileSnapshotV2(rawSecond);
    const firstDisposed: string[] = [];
    const secondDisposed: string[] = [];
    const first = await webLoader(
      snapshot,
      definitions(snapshot, { value: 1, observed: [], disposed: firstDisposed })
    ).stage(snapshot);
    const second = await webLoader(
      secondSnapshot,
      definitions(secondSnapshot, { value: 2, observed: [], disposed: secondDisposed })
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

function webLoader(
  snapshot: ProfileSnapshotV2,
  moduleDefinitions: Iterable<PluginDefinitionV2>
): LoaderV2 {
  return new LoaderV2(moduleDefinitions, 'web', targetCatalog(snapshot));
}

function targetCatalog(snapshot: ProfileSnapshotV2): Record<string, string> {
  return Object.fromEntries(
    snapshot.manifests.flatMap((manifest) =>
      manifest.modules
        .filter((module) => module.targets.includes('web'))
        .map((module) => [module.module_ref, module.contract_digest])
    )
  );
}

function moduleContractDigests(snapshot: ProfileSnapshotV2): Map<string, string> {
  return new Map(
    snapshot.manifests.flatMap((manifest) =>
      manifest.modules.map((module) => [module.module_ref, module.contract_digest] as const)
    )
  );
}

async function orderedSiblingSnapshot(): Promise<ProfileSnapshotV2> {
  const snapshot = structuredClone(SNAPSHOT);
  const manifest = snapshot.manifests[0];
  const baseModule = manifest?.modules[0];
  const baseEntry = snapshot.entries[0];
  if (!manifest || !baseModule || !baseEntry) {
    throw new Error('ordered sibling fixture base is missing');
  }
  const orderedEvent = {
    event: 'ordered',
    mode: 'serial',
    payload_schema: {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      type: 'object',
    },
    result_schema: {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      type: 'string',
    },
  } as const;
  const contract: PluginContractV2 = {
    services: { provides: [], requires: [] },
    events: { emits: [orderedEvent], handles: [orderedEvent] },
    config_schema: {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      type: 'object',
      additionalProperties: false,
    },
  };
  const module = (moduleRef: string): MutablePluginModule => ({
    ...baseModule,
    module_ref: moduleRef,
    entrypoint: `conformance:${moduleRef}`,
    targets: ['web'],
    contract,
    contract_digest: '',
  });
  manifest.modules = [
    module('builtin://conformance/declared-first'),
    module('builtin://conformance/declared-second'),
  ];
  const entry = (entryId: string, moduleRef: string): ProfileEntryV2 => ({
    ...baseEntry,
    entry_id: entryId,
    parent_entry_id: null,
    module_ref: moduleRef,
    config: {},
    inject: {},
    isolate: {},
    scope: { kind: 'root' },
    permissions: [],
  });
  snapshot.entries = [
    entry('z-declared-first', 'builtin://conformance/declared-first'),
    entry('a-declared-second', 'builtin://conformance/declared-second'),
  ];
  await refreshContractDigests(snapshot);
  await refreshSnapshotDigest(snapshot);
  return parseProfileSnapshotV2(snapshot);
}

function requiredValue(values: ReadonlyMap<string, string>, key: string): string {
  const value = values.get(key);
  if (!value) throw new Error(`missing fixture value ${key}`);
  return value;
}

function completenessProbe(testCase: RuntimeCompletenessCase): PluginDefinitionV2['apply'] {
  return async (context) => {
    if (testCase.module_ref.endsWith('root-provider') && testCase.operation !== 'provide') {
      context.provide('service:clock', 7);
    }
    switch (testCase.operation) {
      case 'provide':
        context.provide(testCase.name, 7);
        return;
      case 'require':
        context.require(testCase.name);
        return;
      case 'on':
        context.on(testCase.name, (payload) => payload);
        return;
      case 'dispatch':
        await context.dispatch(testCase.name, null);
    }
  };
}

async function mutatedSnapshot(testCase: ContractNegativeCase): Promise<MutableSnapshot> {
  const snapshot = structuredClone(SNAPSHOT);
  const operations = testCase.mutation.operations ?? [testCase.mutation];
  for (const operation of operations) applyPointer(snapshot, operation);
  if (testCase.mutation.refresh_contract_digest) await refreshContractDigests(snapshot);
  await refreshSnapshotDigest(snapshot);
  return snapshot;
}

function applyPointer(document: unknown, operation: MutationOperation): void {
  const parts = operation.path
    .split('/')
    .slice(1)
    .map((part) => part.replaceAll('~1', '/').replaceAll('~0', '~'));
  const final = parts.pop();
  if (final === undefined) throw new Error('fixture mutation must have a target');
  let parent = document;
  for (const part of parts) {
    if (Array.isArray(parent)) parent = parent[Number(part)];
    else if (isRecord(parent)) parent = parent[part];
    else throw new Error(`fixture mutation cannot traverse ${operation.path}`);
  }
  if (Array.isArray(parent)) {
    const index = Number(final);
    if (operation.operation === 'add') parent.splice(index, 0, structuredClone(operation.value));
    else if (operation.operation === 'remove') parent.splice(index, 1);
    else parent[index] = structuredClone(operation.value);
    return;
  }
  if (!isRecord(parent)) throw new Error(`fixture mutation cannot update ${operation.path}`);
  if (operation.operation === 'remove') delete parent[final];
  else parent[final] = structuredClone(operation.value);
}

async function refreshContractDigests(snapshot: MutableSnapshot): Promise<void> {
  for (const manifest of snapshot.manifests) {
    for (const module of manifest.modules) {
      module.contract_digest = `sha256:${await digestV2(module.contract)}`;
    }
  }
}

async function refreshSnapshotDigest(snapshot: MutableSnapshot): Promise<void> {
  const payload = { ...snapshot };
  delete payload.digest;
  snapshot.digest = await digestV2(payload);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
