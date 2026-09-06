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
