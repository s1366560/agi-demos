import { describe, expect, it, vi } from 'vitest';

import {
  LoaderV2,
  RendererContributionRegistryV2,
  RendererPluginRuntimeV2,
  createDesktopRendererDefinitionsV2,
  createWebRendererDefinitionsV2,
  digestV2,
  parseProfileSnapshotV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import { createRendererCandidateReadinessV2 } from '../../../../agi-stack/packages/plugin-runtime/src/rendererReadiness';
import {
  DESKTOP_RENDERER_HOST_MODULE_REF_V2,
  DESKTOP_RENDERER_HOST_SERVICE_V2,
  WEB_RENDERER_HOST_MODULE_REF_V2,
  WEB_RENDERER_HOST_SERVICE_V2,
} from '../../../../agi-stack/packages/plugin-runtime/src/targetModules';
import {
  DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2,
  DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  WEB_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2,
  WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
} from '../../../../agi-stack/packages/plugin-runtime/src/rendererContributions';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

const cases = [
  {
    target: 'web' as const,
    definitions: createWebRendererDefinitionsV2(),
    hostModule: WEB_RENDERER_HOST_MODULE_REF_V2,
    hostService: WEB_RENDERER_HOST_SERVICE_V2,
    registryModule: WEB_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2,
    registryService: WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
    strategy: 'generation-renderer-host',
  },
  {
    target: 'desktop-renderer' as const,
    definitions: createDesktopRendererDefinitionsV2(),
    hostModule: DESKTOP_RENDERER_HOST_MODULE_REF_V2,
    hostService: DESKTOP_RENDERER_HOST_SERVICE_V2,
    registryModule: DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2,
    registryService: DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
    strategy: 'native-generation-renderer-host',
  },
];

type RendererCase = (typeof cases)[number];

async function snapshotFor(item: RendererCase, generation = 501, empty = false) {
  // Web uses every generated Web definition. Desktop exercises the real shared host and
  // contribution modules, not application authority definitions or native acceptance.
  const refs = new Set(item.definitions.map((definition) => definition.moduleRef));
  const { digest: _digest, ...unsigned } = {
    ...structuredClone(bootstrapProfile),
    generation,
    entries: empty ? [] : bootstrapProfile.entries.filter((entry) => refs.has(entry.module_ref)),
  };
  return parseProfileSnapshotV2({ ...unsigned, digest: await digestV2(unsigned) });
}

function envelope(snapshot: Awaited<ReturnType<typeof snapshotFor>>) {
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
      nonce: `candidate-readiness-${snapshot.generation}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

for (const item of cases) {
  describe(`${item.target} candidate readiness`, () => {
    it.each(['host-target', 'host-strategy', 'registry-target', 'contribution'] as const)(
      'rejects %s through the actual Renderer constructor before replacing last-good',
      async (fault) => {
        let invalid = false;
        const disposed = vi.fn();
        const definitions: PluginDefinitionV2[] = item.definitions.map((definition) => {
          if (definition.moduleRef === item.hostModule)
            return {
              ...definition,
              apply(context) {
                context.provide(item.hostService, {
                  target: invalid && fault === 'host-target' ? 'wrong-renderer' : item.target,
                  strategy: invalid && fault === 'host-strategy' ? 'wrong-strategy' : item.strategy,
                });
                return disposed;
              },
            };
          if (definition.moduleRef === item.registryModule)
            return {
              ...definition,
              apply(context) {
                const registry = new RendererContributionRegistryV2(item.target);
                const capturedInvalid = invalid;
                context.provide(item.registryService, {
                  target:
                    capturedInvalid && fault === 'registry-target' ? 'wrong-renderer' : item.target,
                  register: registry.register.bind(registry),
                  list: () =>
                    capturedInvalid && fault === 'contribution'
                      ? [
                          ...registry.list(),
                          {
                            id: 'invalid-final-record',
                            sourceEntryId: 'test',
                            kind: 'route',
                            order: NaN,
                            payload: {},
                          },
                        ]
                      : registry.list(),
                });
              },
            };
          return definition;
        });
        const runtime = new RendererPluginRuntimeV2(item.target, definitions);
        await runtime.bootstrap(await snapshotFor(item));
        const previous = runtime.getSnapshot()!;
        const lease = runtime.acquire();
        invalid = true;
        const receipt = await runtime.apply(envelope(await snapshotFor(item, 502)));
        expect(receipt.status).toBe('nack');
        expect(receipt.error_code).toBe('generation_apply_failed');
        expect(runtime.getSnapshot()).toBe(previous);
        expect(previous.retired).toBe(false);
        expect(lease.generation).toBe(previous);
        expect(disposed).toHaveBeenCalledTimes(1);
        await lease.release();
        await runtime.close();
      }
    );

    it('accepts a structural registry provider without instanceof coupling and validates its complete contribution set', async () => {
      const finalValidator = vi.fn();
      const definitions = item.definitions.map((definition) =>
        definition.moduleRef !== item.registryModule
          ? definition
          : {
              ...definition,
              apply(context: Parameters<PluginDefinitionV2['apply']>[0]) {
                const registry = new RendererContributionRegistryV2(item.target);
                context.provide(
                  item.registryService,
                  Object.freeze({
                    target: item.target,
                    register: registry.register.bind(registry),
                    list: registry.list.bind(registry),
                  })
                );
              },
            }
      );
      const snapshot = await snapshotFor(item);
      const loader = new LoaderV2(
        definitions,
        item.target,
        undefined,
        createRendererCandidateReadinessV2(item.target, finalValidator)
      );
      const generation = await loader.stage(snapshot);
      expect(finalValidator).toHaveBeenCalledTimes(1);
      const contributions = finalValidator.mock.calls[0]![0] as unknown[];
      const expected = snapshot.entries.filter(
        (entry) => entry.enabled && entry.module_ref.endsWith('/renderer-contribution')
      ).length;
      expect(expected).toBeGreaterThan(0);
      expect(contributions).toHaveLength(expected);
      expect(generation.fibers.every((fiber) => fiber.phase === 'active')).toBe(true);
      await generation.dispose();
    });

    it('runs the constructor final-set validator after every contribution and rejects its original error', async () => {
      const snapshot = await snapshotFor(item);
      const failure = new Error('final renderer contribution set rejected');
      const validate = vi.fn((contributions: readonly unknown[]) => {
        expect(contributions).toHaveLength(
          snapshot.entries.filter(
            (entry) => entry.enabled && entry.module_ref.endsWith('/renderer-contribution')
          ).length
        );
        throw failure;
      });
      const runtime = new RendererPluginRuntimeV2(item.target, item.definitions, validate);
      await expect(runtime.bootstrap(snapshot)).rejects.toBe(failure);
      expect(validate).toHaveBeenCalledTimes(1);
      expect(runtime.getSnapshot()).toBeUndefined();
      await runtime.close();
    });

    it('accepts a host-only profile with registry and contributions disabled', async () => {
      const base = await snapshotFor(item, 504);
      const { digest: _digest, ...unsigned } = {
        ...base,
        entries: base.entries.map((entry) => ({
          ...entry,
          enabled: entry.module_ref === item.hostModule,
        })),
      };
      const snapshot = await parseProfileSnapshotV2({
        ...unsigned,
        digest: await digestV2(unsigned),
      });
      const validate = vi.fn();
      const runtime = new RendererPluginRuntimeV2(item.target, item.definitions, validate);
      const receipt = await runtime.apply(envelope(snapshot));
      expect(receipt.status).toBe('ack');
      expect(runtime.getSnapshot()?.fibers).toHaveLength(1);
      expect(runtime.getSnapshot()?.resolve(item.hostService, { kind: 'root' })).toMatchObject({
        target: item.target,
        strategy: item.strategy,
      });
      expect(validate).not.toHaveBeenCalled();
      await runtime.close();
    });

    it('rejects an enabled declared registry that fails to provide its service and retains last-good', async () => {
      let omitRegistry = false;
      const definitions = item.definitions.map((definition) =>
        definition.moduleRef !== item.registryModule
          ? definition
          : {
              ...definition,
              apply(
                context: Parameters<PluginDefinitionV2['apply']>[0],
                config: Readonly<Record<string, unknown>>
              ) {
                if (!omitRegistry) return definition.apply(context, config);
                return undefined;
              },
            }
      );
      const runtime = new RendererPluginRuntimeV2(item.target, definitions);
      await runtime.bootstrap(await snapshotFor(item));
      const previous = runtime.getSnapshot()!;
      const base = await snapshotFor(item, 505);
      const { digest: _digest, ...unsigned } = {
        ...base,
        // No contributor can fail early while requiring registry: readiness itself must
        // enforce the enabled provider declaration after its apply returned successfully.
        entries: base.entries.map((entry) => ({
          ...entry,
          enabled: entry.module_ref === item.hostModule || entry.module_ref === item.registryModule,
        })),
      };
      const snapshot = await parseProfileSnapshotV2({
        ...unsigned,
        digest: await digestV2(unsigned),
      });
      omitRegistry = true;
      const receipt = await runtime.apply(envelope(snapshot));
      expect(receipt.status).toBe('nack');
      expect(runtime.getSnapshot()).toBe(previous);
      expect(previous.retired).toBe(false);
      expect(previous.disposed).toBe(false);
      await runtime.close();
    });

    it.each(['tenant', 'isolated'] as const)(
      'does not resolve a %s registry as the root registry',
      async (placement) => {
        const base = await snapshotFor(item, 506);
        const { digest: _digest, ...unsigned } = {
          ...base,
          entries: base.entries
            .filter(
              (entry) =>
                entry.module_ref === item.hostModule || entry.module_ref === item.registryModule
            )
            .map((entry) => ({
              ...entry,
              enabled:
                entry.module_ref === item.hostModule || entry.module_ref === item.registryModule,
              ...(entry.module_ref === item.registryModule
                ? {
                    scope:
                      placement === 'tenant'
                        ? { kind: 'tenant' as const, tenant_id: 'tenant-readiness' }
                        : entry.scope,
                    isolate:
                      placement === 'isolated'
                        ? { [item.registryService]: 'private-registry' }
                        : entry.isolate,
                  }
                : {}),
            })),
        };
        const snapshot = await parseProfileSnapshotV2({
          ...unsigned,
          digest: await digestV2(unsigned),
        });
        const validate = vi.fn();
        const loader = new LoaderV2(
          item.definitions,
          item.target,
          undefined,
          createRendererCandidateReadinessV2(item.target, validate)
        );
        const generation = await loader.stage(snapshot);
        expect(generation.fibers).toHaveLength(2);
        expect(validate).not.toHaveBeenCalled();
        expect(() => generation.resolve(item.registryService, { kind: 'root' })).toThrow();
        const registry =
          placement === 'tenant'
            ? generation.resolve<RendererContributionRegistryV2>(item.registryService, {
                kind: 'tenant',
                tenant_id: 'tenant-readiness',
              })
            : generation.resolve<RendererContributionRegistryV2>(
                item.registryService,
                { kind: 'root' },
                { isolation: 'private-registry' }
              );
        expect(registry.target).toBe(item.target);
        expect(registry.list()).toEqual([]);
        await generation.dispose();
      }
    );

    it('accepts removal of every target entry without requiring a host or registry', async () => {
      const validate = vi.fn();
      const runtime = new RendererPluginRuntimeV2(item.target, item.definitions, validate);
      const receipt = await runtime.apply(envelope(await snapshotFor(item, 503, true)));
      expect(receipt.status).toBe('ack');
      expect(runtime.getSnapshot()?.fibers).toHaveLength(0);
      expect(validate).not.toHaveBeenCalled();
      await runtime.close();
    });
  });
}
