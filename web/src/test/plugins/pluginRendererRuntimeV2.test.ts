import { describe, expect, it, vi } from 'vitest';

import {
  PLUGIN_MODULE_CATALOG_V2,
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

import generatedBootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

// This suite exercises shared renderer host/contribution definitions, not Desktop application
// services. Keep the real generated profile entries for those definitions and re-sign the fixture.
const sharedDesktopModules = new Set(createDesktopRendererDefinitionsV2().map(definition => definition.moduleRef));
const applicationDesktopModules = new Set(PLUGIN_MODULE_CATALOG_V2.modules
  .filter(module => module.targets.includes('desktop-renderer') && !sharedDesktopModules.has(module.module_ref))
  .map(module => module.module_ref));
const bootstrapProfile = structuredClone(generatedBootstrapProfile);
bootstrapProfile.entries = bootstrapProfile.entries.filter(entry => !applicationDesktopModules.has(entry.module_ref));
const { digest: _fixtureDigest, ...fixtureUnsigned } = bootstrapProfile;
bootstrapProfile.digest = await digestV2(fixtureUnsigned);


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

  it('keeps an exact rendered generation alive for an in-flight operation', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.apply(await distributionAt(1, 1));
    const store = new RendererGenerationLeaseStoreV2(runtime);
    store.activateRoot();
    const unsubscribe = store.subscribe(vi.fn());
    const renderedGeneration = store.getSnapshot().generation;
    expect(renderedGeneration).toBeDefined();

    const operationLease = store.acquireGeneration(renderedGeneration!);
    await runtime.apply(await distributionAt(2, 2));
    await store.commit(store.getSnapshot());

    expect(renderedGeneration?.retired).toBe(true);
    expect(renderedGeneration?.disposed).toBe(false);
    expect(renderedGeneration?.leaseCount).toBe(1);
    expect(operationLease.generation).toBe(renderedGeneration);

    await operationLease.release();
    expect(renderedGeneration?.disposed).toBe(true);

    unsubscribe();
    await store.deactivateRoot();
    await runtime.close();
  });

  it('fails closed when an operation tries to reacquire a released render generation', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.apply(await distributionAt(1, 1));
    const store = new RendererGenerationLeaseStoreV2(runtime);
    store.activateRoot();
    const releasedGeneration = store.getSnapshot().generation;
    expect(releasedGeneration).toBeDefined();

    await runtime.apply(await distributionAt(2, 2));
    await store.commit(store.getSnapshot());

    expect(releasedGeneration?.disposed).toBe(true);
    expect(() => store.acquireGeneration(releasedGeneration!)).toThrowError(
      expect.objectContaining({ code: 'renderer_generation_not_renderable' })
    );

    await store.deactivateRoot();
    await runtime.close();
  });

  it('rejects a retained generation owned by another renderer runtime', async () => {
    const owner = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    const foreign = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await owner.apply(await distributionAt(1, 1));
    await foreign.apply(await distributionAt(1, 1));
    const retainedLease = owner.acquire();

    await owner.apply(await distributionAt(2, 2));

    expect(retainedLease.generation.retired).toBe(true);
    expect(retainedLease.generation.leaseCount).toBe(1);
    expect(() => foreign.acquire(retainedLease.generation)).toThrowError(
      expect.objectContaining({ code: 'generation_not_leased' })
    );

    await retainedLease.release();
    await owner.close();
    await foreign.close();
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
      ['web.authenticated-shell-surface', 'ui-slot'],
      ['web.default-business-routes', 'route'],
      ['web.default-navigation', 'navigation'],
      ['web.default-ui-slots', 'ui-slot'],
    ]);
    await runtime.close();
  });

  it('lets the desktop target catalog nack an unknown artifact and retain last-good', async () => {
    const knownArtifactRefs = new Set([
      'desktop.ui-slots.authenticated-shell-surface.v2',
      'desktop.ui-slots.settings-window-surface.v1',
      'desktop.ui-slots.keyboard-shortcuts-surface.v1',
      'desktop.ui-slots.status-bar-surface.v1',
      'desktop.ui-slots.command-palette-surface.v1',
      'desktop.ui-slots.session-canvas-surface.v1',
      'desktop.ui-slots.workspace-create-surface.v1',
      'desktop.ui-slots.workspace-settings-surface.v1',
      'desktop.ui-slots.titlebar-surface.v1',
      'desktop.ui-slots.workbench-tab-bar-surface.v1',
      'desktop.ui-slots.workbench-surface.v2',
      'desktop.ui-slots.session-workspace-surface.v1',
      'desktop.ui-slots.workspace-collaboration-surface.v1',
      'desktop.ui-slots.new-thread-composer-surface.v1',
      'desktop.ui-slots.my-work-queue-surface.v1',
      'desktop.ui-slots.activity-inbox-surface.v1',
      'desktop.ui-slots.conversation-surface.v1',
      'desktop.ui-slots.conversation-renderer.v1',
      'desktop.ui-slots.tool-result-renderer.v1',
      'desktop.ui-slots.sidebar-surface.v1',
      'desktop.ui-slots.right-sidebar-surface.v1',
      'desktop.ui-slots.new-task-flow-surface.v1',
      'desktop.routes.tenant-creation.v1',
      'desktop.routes.auxiliary.v1',
      'desktop.routes.project-knowledge.v1',
      'desktop.routes.project-agent.v1',
      'desktop.routes.project-administration.v1',
      'desktop.routes.runtime-infrastructure.v1',
      'desktop.routes.project-workspace.v1',
      'desktop.routes.project-discovery.v1',
      'desktop.routes.tenant-core.v1',
      'desktop.routes.tenant-agent-building.v1',
      'desktop.routes.tenant-extensions-integrations.v1',
      'desktop.routes.tenant-governance.v1',
      'desktop.navigation.auxiliary.v1',
      'desktop.navigation.project-knowledge.v1',
      'desktop.navigation.project-agent.v1',
      'desktop.navigation.project-administration.v1',
      'desktop.navigation.runtime-infrastructure.v1',
      'desktop.navigation.project-workspace.v1',
      'desktop.navigation.project-discovery.v1',
      'desktop.navigation.tenant-core.v1',
      'desktop.navigation.tenant-agent-building.v1',
      'desktop.navigation.tenant-extensions-integrations.v1',
      'desktop.navigation.tenant-governance.v1',
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
      ['desktop.authenticated-shell-surface', 'ui-slot'],
      ['desktop.settings-window-surface', 'ui-slot'],
      ['desktop.keyboard-shortcuts-surface', 'ui-slot'],
      ['desktop.status-bar-surface', 'ui-slot'],
      ['desktop.command-palette-surface', 'ui-slot'],
      ['desktop.session-canvas-surface', 'ui-slot'],
      ['desktop.workspace-create-surface', 'ui-slot'],
      ['desktop.workspace-settings-surface', 'ui-slot'],
      ['desktop.titlebar-surface', 'ui-slot'],
      ['desktop.workbench-tab-bar-surface', 'ui-slot'],
      ['desktop.workbench-surface', 'ui-slot'],
      ['desktop.session-workspace-surface', 'ui-slot'],
      ['desktop.workspace-collaboration-surface', 'ui-slot'],
      ['desktop.new-thread-composer-surface', 'ui-slot'],
      ['desktop.my-work-queue-surface', 'ui-slot'],
      ['desktop.activity-inbox-surface', 'ui-slot'],
      ['desktop.conversation-surface', 'ui-slot'],
      ['desktop.conversation-renderer', 'ui-slot'],
      ['desktop.tool-result-renderer', 'ui-slot'],
      ['desktop.sidebar-surface', 'ui-slot'],
      ['desktop.tenant-creation-routes', 'route'],
      ['desktop.right-sidebar-surface', 'ui-slot'],
      ['desktop.new-task-flow-surface', 'ui-slot'],
      ['desktop.auxiliary-routes', 'route'],
      ['desktop.project-knowledge-routes', 'route'],
      ['desktop.project-agent-routes', 'route'],
      ['desktop.project-administration-routes', 'route'],
      ['desktop.runtime-infrastructure-routes', 'route'],
      ['desktop.project-workspace-routes', 'route'],
      ['desktop.project-discovery-routes', 'route'],
      ['desktop.tenant-core-routes', 'route'],
      ['desktop.tenant-agent-building-routes', 'route'],
      ['desktop.tenant-extensions-integrations-routes', 'route'],
      ['desktop.tenant-governance-routes', 'route'],
      ['desktop.auxiliary-navigation', 'navigation'],
      ['desktop.project-knowledge-navigation', 'navigation'],
      ['desktop.project-agent-navigation', 'navigation'],
      ['desktop.project-administration-navigation', 'navigation'],
      ['desktop.runtime-infrastructure-navigation', 'navigation'],
      ['desktop.project-workspace-navigation', 'navigation'],
      ['desktop.project-discovery-navigation', 'navigation'],
      ['desktop.tenant-core-navigation', 'navigation'],
      ['desktop.tenant-agent-building-navigation', 'navigation'],
      ['desktop.tenant-extensions-integrations-navigation', 'navigation'],
      ['desktop.tenant-governance-navigation', 'navigation'],
      ['desktop.default-ui-slots', 'ui-slot'],
    ]);

    const invalid = structuredClone(bootstrapProfile);
    const routeEntry = invalid.entries.find(
      ({ entry_id }) => entry_id === 'builtin-desktop-tenant-creation-routes'
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
      'desktop.authenticated-shell-surface',
      'desktop.settings-window-surface',
      'desktop.keyboard-shortcuts-surface',
      'desktop.status-bar-surface',
      'desktop.command-palette-surface',
      'desktop.session-canvas-surface',
      'desktop.workspace-create-surface',
      'desktop.workspace-settings-surface',
      'desktop.titlebar-surface',
      'desktop.workbench-tab-bar-surface',
      'desktop.workbench-surface',
      'desktop.session-workspace-surface',
      'desktop.workspace-collaboration-surface',
      'desktop.new-thread-composer-surface',
      'desktop.my-work-queue-surface',
      'desktop.activity-inbox-surface',
      'desktop.conversation-surface',
      'desktop.conversation-renderer',
      'desktop.tool-result-renderer',
      'desktop.sidebar-surface',
      'desktop.tenant-creation-routes',
      'desktop.right-sidebar-surface',
      'desktop.new-task-flow-surface',
      'desktop.project-knowledge-routes',
      'desktop.project-agent-routes',
      'desktop.project-administration-routes',
      'desktop.runtime-infrastructure-routes',
      'desktop.project-workspace-routes',
      'desktop.project-discovery-routes',
      'desktop.tenant-core-routes',
      'desktop.tenant-agent-building-routes',
      'desktop.tenant-extensions-integrations-routes',
      'desktop.tenant-governance-routes',
      'desktop.project-knowledge-navigation',
      'desktop.project-agent-navigation',
      'desktop.project-administration-navigation',
      'desktop.runtime-infrastructure-navigation',
      'desktop.project-workspace-navigation',
      'desktop.project-discovery-navigation',
      'desktop.tenant-core-navigation',
      'desktop.tenant-agent-building-navigation',
      'desktop.tenant-extensions-integrations-navigation',
      'desktop.tenant-governance-navigation',
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
      'desktop.authenticated-shell-surface',
      'desktop.settings-window-surface',
      'desktop.keyboard-shortcuts-surface',
      'desktop.status-bar-surface',
      'desktop.command-palette-surface',
      'desktop.session-canvas-surface',
      'desktop.workspace-create-surface',
      'desktop.workspace-settings-surface',
      'desktop.titlebar-surface',
      'desktop.workbench-tab-bar-surface',
      'desktop.workbench-surface',
      'desktop.session-workspace-surface',
      'desktop.workspace-collaboration-surface',
      'desktop.new-thread-composer-surface',
      'desktop.my-work-queue-surface',
      'desktop.activity-inbox-surface',
      'desktop.conversation-surface',
      'desktop.conversation-renderer',
      'desktop.tool-result-renderer',
      'desktop.sidebar-surface',
      'desktop.tenant-creation-routes',
      'desktop.right-sidebar-surface',
      'desktop.new-task-flow-surface',
      'desktop.auxiliary-routes',
      'desktop.project-agent-routes',
      'desktop.project-administration-routes',
      'desktop.runtime-infrastructure-routes',
      'desktop.project-workspace-routes',
      'desktop.project-discovery-routes',
      'desktop.tenant-core-routes',
      'desktop.tenant-agent-building-routes',
      'desktop.tenant-extensions-integrations-routes',
      'desktop.tenant-governance-routes',
      'desktop.auxiliary-navigation',
      'desktop.project-agent-navigation',
      'desktop.project-administration-navigation',
      'desktop.runtime-infrastructure-navigation',
      'desktop.project-workspace-navigation',
      'desktop.project-discovery-navigation',
      'desktop.tenant-core-navigation',
      'desktop.tenant-agent-building-navigation',
      'desktop.tenant-extensions-integrations-navigation',
      'desktop.tenant-governance-navigation',
      'desktop.default-ui-slots',
    ]);
    await runtime.close();
  });

  it('removes project agent routes and navigation through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const projectAgentEntryIds = new Set([
      'builtin-desktop-project-agent-routes',
      'builtin-desktop-project-agent-navigation',
    ]);
    const projectAgentEntries = candidate.entries.filter(({ entry_id }) =>
      projectAgentEntryIds.has(entry_id)
    );
    if (projectAgentEntries.length !== projectAgentEntryIds.size) {
      throw new Error('desktop project agent contribution fixtures are missing');
    }
    for (const entry of projectAgentEntries) entry.enabled = false;
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
      'desktop.authenticated-shell-surface',
      'desktop.settings-window-surface',
      'desktop.keyboard-shortcuts-surface',
      'desktop.status-bar-surface',
      'desktop.command-palette-surface',
      'desktop.session-canvas-surface',
      'desktop.workspace-create-surface',
      'desktop.workspace-settings-surface',
      'desktop.titlebar-surface',
      'desktop.workbench-tab-bar-surface',
      'desktop.workbench-surface',
      'desktop.session-workspace-surface',
      'desktop.workspace-collaboration-surface',
      'desktop.new-thread-composer-surface',
      'desktop.my-work-queue-surface',
      'desktop.activity-inbox-surface',
      'desktop.conversation-surface',
      'desktop.conversation-renderer',
      'desktop.tool-result-renderer',
      'desktop.sidebar-surface',
      'desktop.tenant-creation-routes',
      'desktop.right-sidebar-surface',
      'desktop.new-task-flow-surface',
      'desktop.auxiliary-routes',
      'desktop.project-knowledge-routes',
      'desktop.project-administration-routes',
      'desktop.runtime-infrastructure-routes',
      'desktop.project-workspace-routes',
      'desktop.project-discovery-routes',
      'desktop.tenant-core-routes',
      'desktop.tenant-agent-building-routes',
      'desktop.tenant-extensions-integrations-routes',
      'desktop.tenant-governance-routes',
      'desktop.auxiliary-navigation',
      'desktop.project-knowledge-navigation',
      'desktop.project-administration-navigation',
      'desktop.runtime-infrastructure-navigation',
      'desktop.project-workspace-navigation',
      'desktop.project-discovery-navigation',
      'desktop.tenant-core-navigation',
      'desktop.tenant-agent-building-navigation',
      'desktop.tenant-extensions-integrations-navigation',
      'desktop.tenant-governance-navigation',
      'desktop.default-ui-slots',
    ]);
    await runtime.close();
  });

  it('removes project administration routes and navigation through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const projectAdministrationEntryIds = new Set([
      'builtin-desktop-project-administration-routes',
      'builtin-desktop-project-administration-navigation',
    ]);
    const projectAdministrationEntries = candidate.entries.filter(({ entry_id }) =>
      projectAdministrationEntryIds.has(entry_id)
    );
    if (projectAdministrationEntries.length !== projectAdministrationEntryIds.size) {
      throw new Error('desktop project administration contribution fixtures are missing');
    }
    for (const entry of projectAdministrationEntries) entry.enabled = false;
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
      'desktop.authenticated-shell-surface',
      'desktop.settings-window-surface',
      'desktop.keyboard-shortcuts-surface',
      'desktop.status-bar-surface',
      'desktop.command-palette-surface',
      'desktop.session-canvas-surface',
      'desktop.workspace-create-surface',
      'desktop.workspace-settings-surface',
      'desktop.titlebar-surface',
      'desktop.workbench-tab-bar-surface',
      'desktop.workbench-surface',
      'desktop.session-workspace-surface',
      'desktop.workspace-collaboration-surface',
      'desktop.new-thread-composer-surface',
      'desktop.my-work-queue-surface',
      'desktop.activity-inbox-surface',
      'desktop.conversation-surface',
      'desktop.conversation-renderer',
      'desktop.tool-result-renderer',
      'desktop.sidebar-surface',
      'desktop.tenant-creation-routes',
      'desktop.right-sidebar-surface',
      'desktop.new-task-flow-surface',
      'desktop.auxiliary-routes',
      'desktop.project-knowledge-routes',
      'desktop.project-agent-routes',
      'desktop.runtime-infrastructure-routes',
      'desktop.project-workspace-routes',
      'desktop.project-discovery-routes',
      'desktop.tenant-core-routes',
      'desktop.tenant-agent-building-routes',
      'desktop.tenant-extensions-integrations-routes',
      'desktop.tenant-governance-routes',
      'desktop.auxiliary-navigation',
      'desktop.project-knowledge-navigation',
      'desktop.project-agent-navigation',
      'desktop.runtime-infrastructure-navigation',
      'desktop.project-workspace-navigation',
      'desktop.project-discovery-navigation',
      'desktop.tenant-core-navigation',
      'desktop.tenant-agent-building-navigation',
      'desktop.tenant-extensions-integrations-navigation',
      'desktop.tenant-governance-navigation',
      'desktop.default-ui-slots',
    ]);
    await runtime.close();
  });

  it('removes runtime infrastructure routes and navigation through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const runtimeInfrastructureEntryIds = new Set([
      'builtin-desktop-runtime-infrastructure-routes',
      'builtin-desktop-runtime-infrastructure-navigation',
    ]);
    const runtimeInfrastructureEntries = candidate.entries.filter(({ entry_id }) =>
      runtimeInfrastructureEntryIds.has(entry_id)
    );
    if (runtimeInfrastructureEntries.length !== runtimeInfrastructureEntryIds.size) {
      throw new Error('desktop runtime infrastructure contribution fixtures are missing');
    }
    for (const entry of runtimeInfrastructureEntries) entry.enabled = false;
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
      'desktop.authenticated-shell-surface',
      'desktop.settings-window-surface',
      'desktop.keyboard-shortcuts-surface',
      'desktop.status-bar-surface',
      'desktop.command-palette-surface',
      'desktop.session-canvas-surface',
      'desktop.workspace-create-surface',
      'desktop.workspace-settings-surface',
      'desktop.titlebar-surface',
      'desktop.workbench-tab-bar-surface',
      'desktop.workbench-surface',
      'desktop.session-workspace-surface',
      'desktop.workspace-collaboration-surface',
      'desktop.new-thread-composer-surface',
      'desktop.my-work-queue-surface',
      'desktop.activity-inbox-surface',
      'desktop.conversation-surface',
      'desktop.conversation-renderer',
      'desktop.tool-result-renderer',
      'desktop.sidebar-surface',
      'desktop.tenant-creation-routes',
      'desktop.right-sidebar-surface',
      'desktop.new-task-flow-surface',
      'desktop.auxiliary-routes',
      'desktop.project-knowledge-routes',
      'desktop.project-agent-routes',
      'desktop.project-administration-routes',
      'desktop.project-workspace-routes',
      'desktop.project-discovery-routes',
      'desktop.tenant-core-routes',
      'desktop.tenant-agent-building-routes',
      'desktop.tenant-extensions-integrations-routes',
      'desktop.tenant-governance-routes',
      'desktop.auxiliary-navigation',
      'desktop.project-knowledge-navigation',
      'desktop.project-agent-navigation',
      'desktop.project-administration-navigation',
      'desktop.project-workspace-navigation',
      'desktop.project-discovery-navigation',
      'desktop.tenant-core-navigation',
      'desktop.tenant-agent-building-navigation',
      'desktop.tenant-extensions-integrations-navigation',
      'desktop.tenant-governance-navigation',
      'desktop.default-ui-slots',
    ]);
    await runtime.close();
  });

  it('removes project workspace routes and navigation through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const projectWorkspaceEntryIds = new Set([
      'builtin-desktop-project-workspace-routes',
      'builtin-desktop-project-workspace-navigation',
    ]);
    const projectWorkspaceEntries = candidate.entries.filter(({ entry_id }) =>
      projectWorkspaceEntryIds.has(entry_id)
    );
    if (projectWorkspaceEntries.length !== projectWorkspaceEntryIds.size) {
      throw new Error('desktop project workspace contribution fixtures are missing');
    }
    for (const entry of projectWorkspaceEntries) entry.enabled = false;
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
      'desktop.authenticated-shell-surface',
      'desktop.settings-window-surface',
      'desktop.keyboard-shortcuts-surface',
      'desktop.status-bar-surface',
      'desktop.command-palette-surface',
      'desktop.session-canvas-surface',
      'desktop.workspace-create-surface',
      'desktop.workspace-settings-surface',
      'desktop.titlebar-surface',
      'desktop.workbench-tab-bar-surface',
      'desktop.workbench-surface',
      'desktop.session-workspace-surface',
      'desktop.workspace-collaboration-surface',
      'desktop.new-thread-composer-surface',
      'desktop.my-work-queue-surface',
      'desktop.activity-inbox-surface',
      'desktop.conversation-surface',
      'desktop.conversation-renderer',
      'desktop.tool-result-renderer',
      'desktop.sidebar-surface',
      'desktop.tenant-creation-routes',
      'desktop.right-sidebar-surface',
      'desktop.new-task-flow-surface',
      'desktop.auxiliary-routes',
      'desktop.project-knowledge-routes',
      'desktop.project-agent-routes',
      'desktop.project-administration-routes',
      'desktop.runtime-infrastructure-routes',
      'desktop.project-discovery-routes',
      'desktop.tenant-core-routes',
      'desktop.tenant-agent-building-routes',
      'desktop.tenant-extensions-integrations-routes',
      'desktop.tenant-governance-routes',
      'desktop.auxiliary-navigation',
      'desktop.project-knowledge-navigation',
      'desktop.project-agent-navigation',
      'desktop.project-administration-navigation',
      'desktop.runtime-infrastructure-navigation',
      'desktop.project-discovery-navigation',
      'desktop.tenant-core-navigation',
      'desktop.tenant-agent-building-navigation',
      'desktop.tenant-extensions-integrations-navigation',
      'desktop.tenant-governance-navigation',
      'desktop.default-ui-slots',
    ]);
    await runtime.close();
  });

  it('removes project discovery routes and navigation through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const projectDiscoveryEntryIds = new Set([
      'builtin-desktop-project-discovery-routes',
      'builtin-desktop-project-discovery-navigation',
    ]);
    const projectDiscoveryEntries = candidate.entries.filter(({ entry_id }) =>
      projectDiscoveryEntryIds.has(entry_id)
    );
    if (projectDiscoveryEntries.length !== projectDiscoveryEntryIds.size) {
      throw new Error('desktop project discovery contribution fixtures are missing');
    }
    for (const entry of projectDiscoveryEntries) entry.enabled = false;
    candidate.generation += 1;
    const { digest: _digest, ...unsigned } = candidate;
    candidate.digest = await digestV2(unsigned);

    const receipt = await runtime.apply(distribution(candidate));
    const registry = runtime
      .getSnapshot()
      ?.resolve<RendererContributionRegistryV2>(DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2, {
        kind: 'root',
      });
    const contributionIds = registry?.list().map(({ id }) => id);

    expect(receipt.status).toBe('ack');
    expect(contributionIds).toHaveLength(44);
    expect(contributionIds).not.toContain('desktop.project-discovery-routes');
    expect(contributionIds).not.toContain('desktop.project-discovery-navigation');
    await runtime.close();
  });

  it('removes tenant core routes and navigation through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const tenantCoreEntryIds = new Set([
      'builtin-desktop-tenant-core-routes',
      'builtin-desktop-tenant-core-navigation',
    ]);
    const tenantCoreEntries = candidate.entries.filter(({ entry_id }) =>
      tenantCoreEntryIds.has(entry_id)
    );
    if (tenantCoreEntries.length !== tenantCoreEntryIds.size) {
      throw new Error('desktop tenant core contribution fixtures are missing');
    }
    for (const entry of tenantCoreEntries) entry.enabled = false;
    candidate.generation += 1;
    const { digest: _digest, ...unsigned } = candidate;
    candidate.digest = await digestV2(unsigned);

    const receipt = await runtime.apply(distribution(candidate));
    const registry = runtime
      .getSnapshot()
      ?.resolve<RendererContributionRegistryV2>(DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2, {
        kind: 'root',
      });
    const contributionIds = registry?.list().map(({ id }) => id);

    expect(receipt.status).toBe('ack');
    expect(contributionIds).toHaveLength(44);
    expect(contributionIds).not.toContain('desktop.tenant-core-routes');
    expect(contributionIds).not.toContain('desktop.tenant-core-navigation');
    await runtime.close();
  });

  it('removes tenant agent building routes and navigation through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const tenantAgentBuildingEntryIds = new Set([
      'builtin-desktop-tenant-agent-building-routes',
      'builtin-desktop-tenant-agent-building-navigation',
    ]);
    const tenantAgentBuildingEntries = candidate.entries.filter(({ entry_id }) =>
      tenantAgentBuildingEntryIds.has(entry_id)
    );
    if (tenantAgentBuildingEntries.length !== tenantAgentBuildingEntryIds.size) {
      throw new Error('desktop tenant agent building contribution fixtures are missing');
    }
    for (const entry of tenantAgentBuildingEntries) entry.enabled = false;
    candidate.generation += 1;
    const { digest: _digest, ...unsigned } = candidate;
    candidate.digest = await digestV2(unsigned);

    const receipt = await runtime.apply(distribution(candidate));
    const registry = runtime
      .getSnapshot()
      ?.resolve<RendererContributionRegistryV2>(DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2, {
        kind: 'root',
      });
    const contributionIds = registry?.list().map(({ id }) => id);

    expect(receipt.status).toBe('ack');
    expect(contributionIds).toHaveLength(44);
    expect(contributionIds).not.toContain('desktop.tenant-agent-building-routes');
    expect(contributionIds).not.toContain('desktop.tenant-agent-building-navigation');
    await runtime.close();
  });

  it('removes tenant extensions and integrations through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const tenantExtensionsIntegrationsEntryIds = new Set([
      'builtin-desktop-tenant-extensions-integrations-routes',
      'builtin-desktop-tenant-extensions-integrations-navigation',
    ]);
    const tenantExtensionsIntegrationsEntries = candidate.entries.filter(({ entry_id }) =>
      tenantExtensionsIntegrationsEntryIds.has(entry_id)
    );
    if (tenantExtensionsIntegrationsEntries.length !== tenantExtensionsIntegrationsEntryIds.size) {
      throw new Error(
        'desktop tenant extensions and integrations contribution fixtures are missing'
      );
    }
    for (const entry of tenantExtensionsIntegrationsEntries) entry.enabled = false;
    candidate.generation += 1;
    const { digest: _digest, ...unsigned } = candidate;
    candidate.digest = await digestV2(unsigned);

    const receipt = await runtime.apply(distribution(candidate));
    const registry = runtime
      .getSnapshot()
      ?.resolve<RendererContributionRegistryV2>(DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2, {
        kind: 'root',
      });
    const contributionIds = registry?.list().map(({ id }) => id);

    expect(receipt.status).toBe('ack');
    expect(contributionIds).toHaveLength(44);
    expect(contributionIds).not.toContain('desktop.tenant-extensions-integrations-routes');
    expect(contributionIds).not.toContain('desktop.tenant-extensions-integrations-navigation');
    await runtime.close();
  });

  it('removes tenant governance routes and navigation through independent profile effects', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'desktop-renderer',
      createDesktopRendererDefinitionsV2()
    );
    await runtime.bootstrap(bootstrapProfile);
    const candidate = structuredClone(bootstrapProfile);
    const tenantGovernanceEntryIds = new Set([
      'builtin-desktop-tenant-governance-routes',
      'builtin-desktop-tenant-governance-navigation',
    ]);
    const tenantGovernanceEntries = candidate.entries.filter(({ entry_id }) =>
      tenantGovernanceEntryIds.has(entry_id)
    );
    if (tenantGovernanceEntries.length !== tenantGovernanceEntryIds.size) {
      throw new Error('desktop tenant governance contribution fixtures are missing');
    }
    for (const entry of tenantGovernanceEntries) entry.enabled = false;
    candidate.generation += 1;
    const { digest: _digest, ...unsigned } = candidate;
    candidate.digest = await digestV2(unsigned);

    const receipt = await runtime.apply(distribution(candidate));
    const registry = runtime
      .getSnapshot()
      ?.resolve<RendererContributionRegistryV2>(DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2, {
        kind: 'root',
      });
    const contributionIds = registry?.list().map(({ id }) => id);

    expect(receipt.status).toBe('ack');
    expect(contributionIds).toHaveLength(44);
    expect(contributionIds).not.toContain('desktop.tenant-governance-routes');
    expect(contributionIds).not.toContain('desktop.tenant-governance-navigation');
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
