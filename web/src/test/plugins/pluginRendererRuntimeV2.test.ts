import { describe, expect, it, vi } from 'vitest';

import {
  digestV2,
  RendererContributionRegistryV2,
  RendererPluginRuntimeV2,
  type TargetHostDescriptorV2,
  WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  WEB_RENDERER_HOST_SERVICE_V2,
  webRendererDefinitionsV2,
} from '@agistack/plugin-runtime';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

function distribution(snapshot: typeof bootstrapProfile) {
  return {
    schema_version: 2,
    descriptor: {
      profile_id: snapshot.profile_id,
      generation: snapshot.generation,
      digest: snapshot.digest,
    },
    snapshot,
    envelope: {
      version: 1,
      nonce: 'renderer-bootstrap-v2',
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

describe('RendererPluginRuntimeV2', () => {
  it('publishes a generated target contribution through a stable external-store seam', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const subscriber = vi.fn();
    const unsubscribe = runtime.subscribe(subscriber);

    const receipt = await runtime.apply(distribution(bootstrapProfile));

    expect(receipt.status).toBe('ack');
    expect(subscriber).toHaveBeenCalledOnce();
    expect(
      runtime
        .getSnapshot()
        ?.resolve<TargetHostDescriptorV2>(WEB_RENDERER_HOST_SERVICE_V2, { kind: 'root' })
    ).toEqual({ target: 'web', strategy: 'generation-renderer-host' });
    unsubscribe();
    await runtime.close();
  });

  it('does not replace last-good when the next distribution is malformed', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.apply(distribution(bootstrapProfile));
    const lastGood = runtime.getSnapshot();

    await expect(
      runtime.apply({ ...distribution(bootstrapProfile), schema_version: 1 })
    ).rejects.toMatchObject({ code: 'incompatible_schema_version' });

    expect(runtime.getSnapshot()).toBe(lastGood);
    await runtime.close();
  });

  it('uses a local snapshot as a replaceable bootstrap instead of a publication version', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);

    await runtime.bootstrap(bootstrapProfile);
    const localGeneration = runtime.getSnapshot();
    const receipt = await runtime.apply(distribution(bootstrapProfile));

    expect(localGeneration).toBeDefined();
    expect(receipt.status).toBe('ack');
    expect(localGeneration?.disposed).toBe(true);
    expect(runtime.getSnapshot()).not.toBe(localGeneration);
    await runtime.close();
  });

  it('keeps a retired renderer generation alive until its boundary lease is released', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.bootstrap(bootstrapProfile);
    const leasedGeneration = runtime.getSnapshot();
    const lease = runtime.acquire();

    await runtime.close();

    expect(lease.generation).toBe(leasedGeneration);
    expect(leasedGeneration?.retired).toBe(true);
    expect(leasedGeneration?.disposed).toBe(false);

    await lease.release();
    expect(leasedGeneration?.disposed).toBe(true);
  });

  it('activates explicit route navigation and ui-slot contributions from the profile', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.bootstrap(bootstrapProfile);

    const registry = runtime
      .getSnapshot()
      ?.resolve<RendererContributionRegistryV2>(WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2, {
        kind: 'root',
      });

    expect(registry?.list().map(({ id, kind }) => [id, kind])).toEqual([
      ['web.default-business-routes', 'route'],
      ['web.default-navigation', 'navigation'],
      ['web.default-ui-slots', 'ui-slot'],
    ]);
    await runtime.close();
  });

  it('removes a registered contribution through its idempotent disposer', () => {
    const registry = new RendererContributionRegistryV2('web');
    const dispose = registry.register('entry-one', {
      id: 'web.example-route',
      kind: 'route',
      order: 100,
      payload: { path: '/example' },
    });

    expect(registry.list()).toHaveLength(1);
    dispose();
    dispose();
    expect(registry.list()).toEqual([]);
  });

  it('orders contributions stably and owns a deeply immutable payload snapshot', () => {
    const registry = new RendererContributionRegistryV2('web');
    const sourcePayload = { slots: [{ id: 'original' }] };
    registry.register('entry-late', {
      id: 'web.late',
      kind: 'ui-slot',
      order: 200,
      payload: {},
    });
    registry.register('entry-zeta', {
      id: 'web.zeta',
      kind: 'ui-slot',
      order: 100,
      payload: sourcePayload,
    });
    registry.register('entry-alpha', {
      id: 'web.alpha',
      kind: 'ui-slot',
      order: 100,
      payload: {},
    });

    sourcePayload.slots[0].id = 'mutated';
    const contributions = registry.list('ui-slot');
    const slots = contributions[1].payload.slots as readonly Readonly<{ id: string }>[];

    expect(contributions.map(({ id }) => id)).toEqual(['web.alpha', 'web.zeta', 'web.late']);
    expect(slots[0].id).toBe('original');
    expect(Object.isFrozen(contributions)).toBe(true);
    expect(Object.isFrozen(contributions[1].payload)).toBe(true);
    expect(Object.isFrozen(slots)).toBe(true);
    expect(Object.isFrozen(slots[0])).toBe(true);
  });

  it('reports duplicate contributions with a structured runtime error', () => {
    const registry = new RendererContributionRegistryV2('web');
    const contribution = {
      id: 'web.example-navigation',
      kind: 'navigation' as const,
      order: 100,
      payload: {},
    };
    registry.register('entry-one', contribution);

    let conflict: unknown;
    try {
      registry.register('entry-two', contribution);
    } catch (error) {
      conflict = error;
    }

    expect(conflict).toMatchObject({
      code: 'renderer_contribution_conflict',
      name: 'RuntimeV2Error',
    });
  });

  it('nacks a duplicate contribution and retains the last-good generation', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.apply(distribution(bootstrapProfile));
    const lastGood = runtime.getSnapshot();
    const duplicate = structuredClone(bootstrapProfile);
    const source = duplicate.entries.find(
      ({ entry_id }) => entry_id === 'builtin-web-default-navigation'
    );
    if (!source) throw new Error('web navigation contribution fixture is missing');
    duplicate.entries.push({
      ...source,
      entry_id: 'builtin-web-duplicate-navigation',
    });
    duplicate.generation += 1;
    const { digest: _digest, ...unsigned } = duplicate;
    duplicate.digest = await digestV2(unsigned);
    const nextDistribution = distribution(duplicate);
    const receipt = await runtime.apply({
      ...nextDistribution,
      envelope: {
        ...nextDistribution.envelope,
        nonce: 'renderer-duplicate-v2',
        version: 2,
      },
    });

    expect(receipt).toMatchObject({
      status: 'nack',
      error_code: 'generation_apply_failed',
    });
    expect(receipt.error_message).toContain(
      'renderer_contribution_conflict:navigation:web.default-navigation'
    );
    expect(runtime.getSnapshot()).toBe(lastGood);
    await runtime.close();
  });
});
