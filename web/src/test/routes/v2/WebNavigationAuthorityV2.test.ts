import { describe, expect, it } from 'vitest';

import {
  createWebRendererDefinitionsV2,
  digestV2,
  RendererPluginRuntimeV2,
} from '@agistack/plugin-runtime';

import {
  isWebNavigationPathActiveV2,
  projectWebNavigationAuthorityV2,
  selectWebTopNavigationItemsV2,
} from '../../../routes/v2/webNavigationAuthorityStateV2';
import { projectWebRouteAuthorityV2 } from '../../../routes/v2/webRouteAuthorityStateV2';
import { validateWebRendererContributionsV2 } from '../../../routes/v2/webRendererArtifactCatalogV2';

import bootstrapProfile from '../../../../../shared/profiles/memstack-default-bootstrap.v2.json';

async function generationWithDisabledEntriesV2(disabledEntryIds: readonly string[]) {
  const snapshot = structuredClone(bootstrapProfile);
  for (const entryId of disabledEntryIds) {
    const entry = snapshot.entries.find(({ entry_id }) => entry_id === entryId);
    if (!entry) throw new Error(`web contribution fixture is missing: ${entryId}`);
    entry.enabled = false;
  }
  snapshot.generation += 1;
  const { digest: _digest, ...unsigned } = snapshot;
  snapshot.digest = await digestV2(unsigned);

  const runtime = new RendererPluginRuntimeV2(
    'web',
    createWebRendererDefinitionsV2(validateWebRendererContributionsV2)
  );
  const receipt = await runtime.apply({
    schema_version: 2,
    descriptor: {
      profile_id: snapshot.profile_id,
      generation: snapshot.generation,
      digest: snapshot.digest,
    },
    snapshot,
    envelope: {
      version: 1,
      nonce: `web-navigation-authority-${disabledEntryIds.join('-') || 'default'}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  });
  expect(receipt.status).toBe('ack');
  const generation = runtime.getSnapshot();
  if (!generation) throw new Error('acknowledged generation was not published');
  return { generation, runtime };
}

describe('WebNavigationAuthorityV2', () => {
  it('derives navigation from the active artifact and filters it by active route keys', async () => {
    const { generation, runtime } = await generationWithDisabledEntriesV2([]);
    const routeState = projectWebRouteAuthorityV2(generation);
    const navigationState = projectWebNavigationAuthorityV2(generation, routeState.routeKeys);

    const items = selectWebTopNavigationItemsV2(navigationState, 'tenant', {
      tenantId: 'tenant-1',
    });

    expect(navigationState.navigationArtifactIds).toContain('web.navigation.tenant-overview.v1');
    expect(items.map(({ id }) => id)).toContain('overview');
    expect(items.length).toBeGreaterThan(20);
    expect(items.every(({ path }) => isWebNavigationPathActiveV2(path, routeState.routeKeys))).toBe(
      true
    );
    await runtime.close();
  });

  it('removes one feature navigation with its routes while unrelated destinations stay active', async () => {
    const { generation, runtime } = await generationWithDisabledEntriesV2([
      'builtin-web-feature-project-graph',
    ]);
    const routeState = projectWebRouteAuthorityV2(generation);
    const state = projectWebNavigationAuthorityV2(generation, routeState.routeKeys);
    expect(state.navigationArtifactIds).not.toContain('web.navigation.project-graph.v1');
    expect(state.navigationArtifactIds).toContain('web.navigation.tenant-skills.v1');
    const items = selectWebTopNavigationItemsV2(state, 'project', {
      tenantId: 'tenant-1',
      projectId: 'project-1',
    });
    expect(items.some(({ path }) => path.endsWith('/graph'))).toBe(false);
    expect(items.some(({ path }) => path.endsWith('/memories'))).toBe(true);
    await runtime.close();
  });

  it('keeps navigation empty when its target routes are not active', async () => {
    const { generation, runtime } = await generationWithDisabledEntriesV2([]);
    const state = projectWebNavigationAuthorityV2(generation, []);
    expect(selectWebTopNavigationItemsV2(state, 'tenant', { tenantId: 'tenant-1' })).toEqual([]);
    await runtime.close();
  });

  it('matches exact route templates without accepting unrelated prefixes', () => {
    const routeKeys = ['route:/tenant/:tenantId/projects'] as const;

    expect(isWebNavigationPathActiveV2('/tenant/tenant-1/projects', routeKeys)).toBe(true);
    expect(isWebNavigationPathActiveV2('/tenant/tenant-1/projects/archive', routeKeys)).toBe(false);
    expect(isWebNavigationPathActiveV2('/tenant/tenant-1/providers', routeKeys)).toBe(false);
  });
});
