import { describe, expect, it } from 'vitest';

import {
  createWebRendererDefinitionsV2,
  digestV2,
  RendererPluginRuntimeV2,
} from '@agistack/plugin-runtime';

import { projectWebRouteAuthorityV2 } from '../../../routes/v2/webRouteAuthorityStateV2';
import { validateWebRendererContributionsV2 } from '../../../routes/v2/webRendererArtifactCatalogV2';

import bootstrapProfile from '../../../../../shared/profiles/memstack-default-bootstrap.v2.json';

async function distributionWithoutDefaultRoutesV2() {
  const snapshot = structuredClone(bootstrapProfile);
  const routeEntry = snapshot.entries.find(
    ({ entry_id }) => entry_id === 'builtin-web-default-routes'
  );
  if (!routeEntry) throw new Error('web route contribution fixture is missing');
  routeEntry.enabled = false;
  snapshot.generation += 1;
  const { digest: _digest, ...unsigned } = snapshot;
  snapshot.digest = await digestV2(unsigned);
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
      nonce: 'web-route-authority-disabled-v1',
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

describe('WebRouteAuthorityV2', () => {
  it('projects no routes from an acknowledged generation with the route entry disabled', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'web',
      createWebRendererDefinitionsV2(validateWebRendererContributionsV2)
    );

    const receipt = await runtime.apply(await distributionWithoutDefaultRoutesV2());

    expect(receipt.status).toBe('ack');
    const generation = runtime.getSnapshot();
    if (!generation) throw new Error('acknowledged generation was not published');
    expect(projectWebRouteAuthorityV2(generation)).toEqual({
      routeArtifacts: [],
      routeArtifactIds: [],
      status: 'ready',
    });
    await runtime.close();
  });
});
