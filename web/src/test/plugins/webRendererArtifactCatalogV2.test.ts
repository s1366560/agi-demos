import { describe, expect, it } from 'vitest';

import {
  createWebRendererDefinitionsV2,
  digestV2,
  RendererPluginRuntimeV2,
  type RegisteredRendererContributionV2,
} from '@agistack/plugin-runtime';

import {
  resolveWebRendererArtifactsV2,
  validateWebRendererContributionsV2,
} from '../../routes/v2/webRendererArtifactCatalogV2';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

const WEB_ARTIFACT_REFS = {
  navigation: 'web.navigation.default.v1',
  route: 'web.routes.default-business.v1',
  'ui-slot': 'web.ui-slots.default.v1',
} as const;

function contribution(
  id: string,
  kind: RegisteredRendererContributionV2['kind'],
  artifactRefs: readonly string[]
): RegisteredRendererContributionV2 {
  return {
    id,
    kind,
    order: 100,
    payload: { schema_version: 1, artifact_refs: artifactRefs },
    sourceEntryId: `entry:${id}`,
  };
}

async function webArtifactSnapshot() {
  const snapshot = structuredClone(bootstrapProfile);
  for (const entry of snapshot.entries) {
    if (!entry.entry_id.startsWith('builtin-web-default-')) continue;
    const kind = entry.config.kind as keyof typeof WEB_ARTIFACT_REFS;
    entry.config.payload = {
      schema_version: 1,
      artifact_refs: [WEB_ARTIFACT_REFS[kind]],
    };
  }
  const { digest: _digest, ...unsigned } = snapshot;
  snapshot.digest = await digestV2(unsigned);
  return snapshot;
}

function distribution(snapshot: Awaited<ReturnType<typeof webArtifactSnapshot>>, version: number) {
  return {
    schema_version: 2,
    descriptor: {
      profile_id: snapshot.profile_id,
      generation: snapshot.generation,
      digest: snapshot.digest,
    },
    snapshot,
    envelope: {
      version,
      nonce: `web-artifact-publication-${version}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

describe('web renderer artifact catalog v2', () => {
  it('resolves ordered code-owned artifacts from an exact contribution payload', () => {
    const artifacts = resolveWebRendererArtifactsV2([
      contribution('web.default-navigation', 'navigation', [WEB_ARTIFACT_REFS.navigation]),
      contribution('web.default-routes', 'route', [WEB_ARTIFACT_REFS.route]),
    ]);

    expect(artifacts.map(({ id, kind }) => [id, kind])).toEqual([
      [WEB_ARTIFACT_REFS.navigation, 'navigation'],
      [WEB_ARTIFACT_REFS.route, 'route'],
    ]);
  });

  it('exposes an executable default route artifact with exact mount-aware keys', () => {
    const [artifact] = resolveWebRendererArtifactsV2([
      contribution('web.default-routes', 'route', [WEB_ARTIFACT_REFS.route]),
    ]);

    expect(artifact?.kind).toBe('route');
    if (!artifact || artifact.kind !== 'route')
      throw new Error('default route artifact is missing');
    expect(artifact.createRouteElements).toBeTypeOf('function');
    expect(artifact.routeKeys.length).toBeGreaterThan(100);
    expect(artifact.routeKeys).toContain('route:/tenant/:tenantId/project/:projectId/agent/logs');
    expect(artifact.routeKeys).toContain('route:/tenant/:tenantId/project/:projectId#index');
    expect(artifact.routeKeys).not.toContain('root:web.default-business-routes');
    expect(new Set(artifact.routeKeys).size).toBe(artifact.routeKeys.length);
  });

  it.each([
    {
      name: 'unknown artifact',
      candidate: contribution('web.unknown', 'route', ['web.routes.missing.v1']),
      code: 'renderer_artifact_unknown',
    },
    {
      name: 'kind mismatch',
      candidate: contribution('web.wrong-kind', 'route', [WEB_ARTIFACT_REFS.navigation]),
      code: 'renderer_artifact_kind_mismatch',
    },
    {
      name: 'duplicate artifact ref',
      candidate: contribution('web.duplicate-ref', 'route', [
        WEB_ARTIFACT_REFS.route,
        WEB_ARTIFACT_REFS.route,
      ]),
      code: 'renderer_artifact_payload_invalid',
    },
  ])('rejects $name before publication', ({ candidate, code }) => {
    expect(() => validateWebRendererContributionsV2([candidate])).toThrow(
      expect.objectContaining({ code })
    );
  });

  it('nacks an unknown artifact and retains the last-good generation', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'web',
      createWebRendererDefinitionsV2(validateWebRendererContributionsV2)
    );
    const initial = await webArtifactSnapshot();
    await runtime.apply(distribution(initial, 1));
    const lastGood = runtime.getSnapshot();
    const invalid = structuredClone(initial);
    const route = invalid.entries.find(({ entry_id }) => entry_id === 'builtin-web-default-routes');
    if (!route) throw new Error('web route contribution fixture is missing');
    route.config.payload = { schema_version: 1, artifact_refs: ['web.routes.missing.v1'] };
    invalid.generation += 1;
    const { digest: _digest, ...unsigned } = invalid;
    invalid.digest = await digestV2(unsigned);

    const receipt = await runtime.apply(distribution(invalid, 2));

    expect(receipt).toMatchObject({
      status: 'nack',
      error_code: 'generation_apply_failed',
    });
    expect(receipt.error_message).toContain('renderer_artifact_unknown');
    expect(runtime.getSnapshot()).toBe(lastGood);
    await runtime.close();
  });

  it('nacks a duplicate route artifact path and retains the last-good generation', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'web',
      createWebRendererDefinitionsV2(validateWebRendererContributionsV2)
    );
    const initial = await webArtifactSnapshot();
    await runtime.apply(distribution(initial, 1));
    const lastGood = runtime.getSnapshot();
    const invalid = structuredClone(initial);
    const route = invalid.entries.find(({ entry_id }) => entry_id === 'builtin-web-default-routes');
    if (!route) throw new Error('web route contribution fixture is missing');
    invalid.entries.push({
      ...route,
      entry_id: 'builtin-web-conflicting-routes',
      config: {
        ...route.config,
        id: 'web.conflicting-business-routes',
      },
    });
    invalid.generation += 1;
    const { digest: _digest, ...unsigned } = invalid;
    invalid.digest = await digestV2(unsigned);

    const receipt = await runtime.apply(distribution(invalid, 2));

    expect(receipt).toMatchObject({
      status: 'nack',
      error_code: 'generation_apply_failed',
    });
    expect(receipt.error_message).toContain('renderer_route_path_conflict');
    expect(runtime.getSnapshot()).toBe(lastGood);
    await runtime.close();
  });
});
