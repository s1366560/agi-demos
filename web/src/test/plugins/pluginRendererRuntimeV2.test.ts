import { describe, expect, it, vi } from 'vitest';

import {
  createDesktopRendererDefinitionsV2,
  digestV2,
  DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  RendererContributionRegistryV2,
  RendererGenerationLeaseStoreV2,
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

async function distributionAt(generation: number, version: number) {
  const snapshot = structuredClone(bootstrapProfile);
  snapshot.generation = generation;
  const { digest: _digest, ...unsigned } = snapshot;
  snapshot.digest = await digestV2(unsigned);
  const value = distribution(snapshot);
  return {
    ...value,
    envelope: {
      ...value.envelope,
      nonce: `renderer-publication-${version}`,
      version,
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

  it('keeps the committed generation leased until the replacement commits', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.apply(await distributionAt(1, 1));
    const store = new RendererGenerationLeaseStoreV2(runtime);
    store.activateRoot();
    const unsubscribe = store.subscribe(vi.fn());
    const firstSnapshot = store.getSnapshot();
    await store.commit(firstSnapshot);
    const firstGeneration = firstSnapshot.generation;

    await runtime.apply(await distributionAt(2, 2));
    const nextSnapshot = store.getSnapshot();

    expect(firstGeneration?.retired).toBe(true);
    expect(firstGeneration?.disposed).toBe(false);
    expect(firstGeneration?.leaseCount).toBe(1);
    expect(nextSnapshot.generation?.leaseCount).toBe(1);

    await store.commit(nextSnapshot);
    expect(firstGeneration?.disposed).toBe(true);
    expect(nextSnapshot.generation?.leaseCount).toBe(1);

    unsubscribe();
    await store.deactivateRoot();
    await runtime.close();
  });

  it('leases the initial render snapshot before React subscribes', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.apply(await distributionAt(1, 1));
    const store = new RendererGenerationLeaseStoreV2(runtime);
    store.activateRoot();

    const initialRenderSnapshot = store.getSnapshot();
    const initialGeneration = initialRenderSnapshot.generation;
    await runtime.apply(await distributionAt(2, 2));

    expect(initialGeneration?.retired).toBe(true);
    expect(initialGeneration?.disposed).toBe(false);
    expect(initialGeneration?.leaseCount).toBe(1);
    expect(store.getSnapshot().generation?.leaseCount).toBe(1);

    const unsubscribe = store.subscribe(vi.fn());
    await store.commit(initialRenderSnapshot);
    expect(initialGeneration?.disposed).toBe(false);

    await store.commit(store.getSnapshot());
    expect(initialGeneration?.disposed).toBe(true);

    unsubscribe();
    await store.deactivateRoot();
    await runtime.close();
  });

  it('ignores a stale React commit while a newer generation is pending', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.apply(await distributionAt(1, 1));
    const store = new RendererGenerationLeaseStoreV2(runtime);
    store.activateRoot();
    const unsubscribe = store.subscribe(vi.fn());
    await store.commit(store.getSnapshot());
    const firstGeneration = store.getSnapshot().generation;

    await runtime.apply(await distributionAt(2, 2));
    const staleSnapshot = store.getSnapshot();
    await runtime.apply(await distributionAt(3, 3));
    const currentSnapshot = store.getSnapshot();

    await store.commit(staleSnapshot);
    expect(firstGeneration?.disposed).toBe(false);
    expect(staleSnapshot.generation?.disposed).toBe(false);

    await store.commit(currentSnapshot);
    expect(firstGeneration?.disposed).toBe(true);
    expect(staleSnapshot.generation?.disposed).toBe(true);
    expect(currentSnapshot.generation?.disposed).toBe(false);

    unsubscribe();
    await store.deactivateRoot();
    await runtime.close();
  });

  it('survives a StrictMode-style unsubscribe and immediate resubscribe without underflow', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.apply(await distributionAt(1, 1));
    const store = new RendererGenerationLeaseStoreV2(runtime);
    store.activateRoot();
    const firstUnsubscribe = store.subscribe(vi.fn());
    await store.commit(store.getSnapshot());

    firstUnsubscribe();
    const secondUnsubscribe = store.subscribe(vi.fn());
    await store.commit(store.getSnapshot());

    expect(store.getSnapshot().generation?.leaseCount).toBe(1);
    secondUnsubscribe();
    expect(runtime.getSnapshot()?.leaseCount).toBe(1);
    await store.deactivateRoot();
    expect(runtime.getSnapshot()?.leaseCount).toBe(0);
    await runtime.close();
  });

  it('holds a closing runtime generation until React commits the empty snapshot', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.apply(await distributionAt(1, 1));
    const store = new RendererGenerationLeaseStoreV2(runtime);
    store.activateRoot();
    const generation = store.getSnapshot().generation;
    await store.commit(store.getSnapshot());

    await runtime.close();

    expect(generation?.retired).toBe(true);
    expect(generation?.disposed).toBe(false);
    expect(store.getSnapshot().generation).toBeUndefined();

    await store.commit(store.getSnapshot());
    expect(generation?.disposed).toBe(true);

    await store.deactivateRoot();
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

  it('lets the desktop target catalog nack an unknown artifact and retain last-good', async () => {
    const knownArtifactRefs = new Set([
      'desktop.routes.production.v1',
      'desktop.routes.auxiliary.v1',
      'desktop.routes.project-knowledge.v1',
      'desktop.navigation.default.v1',
      'desktop.navigation.auxiliary.v1',
      'desktop.navigation.project-knowledge.v1',
      'desktop.ui-slots.default.v1',
    ]);
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2((candidate) => {
        for (const contribution of candidate) {
          const refs = contribution.payload.artifact_refs;
          if (!Array.isArray(refs) || refs.some((ref) => !knownArtifactRefs.has(String(ref)))) {
            throw new Error(`desktop_renderer_artifact_unknown:${contribution.id}`);
          }
        }
      })
    );
    await runtime.bootstrap(bootstrapProfile);
    const lastGood = runtime.getSnapshot();
    const registry = lastGood?.resolve<RendererContributionRegistryV2>(
      DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
      { kind: 'root' }
    );
    expect(registry?.list().map(({ id, kind }) => [id, kind])).toEqual([
      ['desktop.production-routes', 'route'],
      ['desktop.auxiliary-routes', 'route'],
      ['desktop.project-knowledge-routes', 'route'],
      ['desktop.default-navigation', 'navigation'],
      ['desktop.auxiliary-navigation', 'navigation'],
      ['desktop.project-knowledge-navigation', 'navigation'],
      ['desktop.default-ui-slots', 'ui-slot'],
    ]);

    const invalid = structuredClone(bootstrapProfile);
    const routeEntry = invalid.entries.find(
      ({ entry_id }) => entry_id === 'builtin-desktop-default-routes'
    );
    if (!routeEntry) throw new Error('desktop route contribution fixture is missing');
    routeEntry.config.payload = {
      artifact_refs: ['desktop.routes.unknown.v1'],
      schema_version: 1,
    };
    invalid.generation += 1;
    const { digest: _digest, ...unsigned } = invalid;
    invalid.digest = await digestV2(unsigned);
    const nextDistribution = distribution(invalid);
    const receipt = await runtime.apply({
      ...nextDistribution,
      envelope: {
        ...nextDistribution.envelope,
        nonce: 'desktop-renderer-unknown-artifact-v2',
        version: 2,
      },
    });

    expect(receipt).toMatchObject({
      status: 'nack',
      error_code: 'generation_apply_failed',
    });
    expect(receipt.error_message).toContain('desktop_renderer_artifact_unknown');
    expect(runtime.getSnapshot()).toBe(lastGood);
    await runtime.close();
  });

  it('removes auxiliary desktop routes and navigation through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const auxiliaryEntryIds = new Set([
      'builtin-desktop-auxiliary-routes',
      'builtin-desktop-auxiliary-navigation',
    ]);
    const auxiliaryEntries = candidate.entries.filter(({ entry_id }) =>
      auxiliaryEntryIds.has(entry_id)
    );
    if (auxiliaryEntries.length !== auxiliaryEntryIds.size) {
      throw new Error('desktop auxiliary contribution fixtures are missing');
    }
    for (const entry of auxiliaryEntries) entry.enabled = false;
    candidate.generation += 1;
    const { digest: _digest, ...unsigned } = candidate;
    candidate.digest = await digestV2(unsigned);

    const receipt = await runtime.apply(distribution(candidate));
    const registry = runtime
      .getSnapshot()
      ?.resolve<RendererContributionRegistryV2>(DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2, {
        kind: 'root',
      });

    expect(receipt.status).toBe('ack');
    expect(registry?.list().map(({ id }) => id)).toEqual([
      'desktop.production-routes',
      'desktop.project-knowledge-routes',
      'desktop.default-navigation',
      'desktop.project-knowledge-navigation',
      'desktop.default-ui-slots',
    ]);
    await runtime.close();
  });

  it('removes project knowledge routes and navigation through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const projectKnowledgeEntryIds = new Set([
      'builtin-desktop-project-knowledge-routes',
      'builtin-desktop-project-knowledge-navigation',
    ]);
    const projectKnowledgeEntries = candidate.entries.filter(({ entry_id }) =>
      projectKnowledgeEntryIds.has(entry_id)
    );
    if (projectKnowledgeEntries.length !== projectKnowledgeEntryIds.size) {
      throw new Error('desktop project knowledge contribution fixtures are missing');
    }
    for (const entry of projectKnowledgeEntries) entry.enabled = false;
    candidate.generation += 1;
    const { digest: _digest, ...unsigned } = candidate;
    candidate.digest = await digestV2(unsigned);

    const receipt = await runtime.apply(distribution(candidate));
    const registry = runtime
      .getSnapshot()
      ?.resolve<RendererContributionRegistryV2>(DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2, {
        kind: 'root',
      });

    expect(receipt.status).toBe('ack');
    expect(registry?.list().map(({ id }) => id)).toEqual([
      'desktop.production-routes',
      'desktop.auxiliary-routes',
      'desktop.default-navigation',
      'desktop.auxiliary-navigation',
      'desktop.default-ui-slots',
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

  it('validates a complete candidate set before committing registry state', () => {
    const registry = new RendererContributionRegistryV2('web', (candidate) => {
      if (candidate.length > 1) throw new Error('candidate rejected');
    });
    registry.register('entry-one', {
      id: 'web.first-route',
      kind: 'route',
      order: 100,
      payload: {},
    });

    expect(() =>
      registry.register('entry-two', {
        id: 'web.second-route',
        kind: 'route',
        order: 200,
        payload: {},
      })
    ).toThrow('candidate rejected');
    expect(registry.list().map(({ id }) => id)).toEqual(['web.first-route']);
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
