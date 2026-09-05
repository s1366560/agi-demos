import { describe, expect, it } from 'vitest';

import {
  PLUGIN_MODULE_CATALOG_V2,
  DESKTOP_RENDERER_HOST_SERVICE_V2,
  desktopRendererDefinitionsV2,
  LoaderV2,
  digestV2,
  parseProfileSnapshotV2,
  type RendererContributionRegistryV2,
  type TargetHostDescriptorV2,
  DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  WEB_RENDERER_HOST_SERVICE_V2,
  webRendererDefinitionsV2,
} from '@agistack/plugin-runtime';

import generatedBootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

// This suite exercises shared renderer host/contribution definitions, not Desktop application
// services. Keep the real generated profile entries for those definitions and re-sign the fixture.
const sharedDesktopModules = new Set(desktopRendererDefinitionsV2.map(definition => definition.moduleRef));
const applicationDesktopModules = new Set(PLUGIN_MODULE_CATALOG_V2.modules
  .filter(module => module.targets.includes('desktop-renderer') && !sharedDesktopModules.has(module.module_ref))
  .map(module => module.module_ref));
const bootstrapProfile = structuredClone(generatedBootstrapProfile);
bootstrapProfile.entries = bootstrapProfile.entries.filter(entry => !applicationDesktopModules.has(entry.module_ref));
const { digest: _fixtureDigest, ...fixtureUnsigned } = bootstrapProfile;
bootstrapProfile.digest = await digestV2(fixtureUnsigned);


describe('production protocol-v2 renderer target catalogs', () => {
  it('activates the web renderer host from the generated catalog', async () => {
    const snapshot = await parseProfileSnapshotV2(bootstrapProfile);
    const generation = await new LoaderV2(webRendererDefinitionsV2, 'web').stage(snapshot);

    expect(
      generation.resolve<TargetHostDescriptorV2>(WEB_RENDERER_HOST_SERVICE_V2, { kind: 'root' })
    ).toEqual({ target: 'web', strategy: 'generation-renderer-host' });
    expect(
      generation
        .resolve<RendererContributionRegistryV2>(WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2, {
          kind: 'root',
        })
        .list()
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: 'web.authenticated-shell-surface',
          kind: 'ui-slot',
          order: 80,
          payload: {
            artifact_refs: ['web.ui-slots.authenticated-shell-surface.v1'],
            schema_version: 1,
          },
        }),
      ])
    );
    expect(
      generation
        .resolve<RendererContributionRegistryV2>(WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2, {
          kind: 'root',
        })
        .list()
    ).toHaveLength(4);
    expect(generation.fibers).toHaveLength(6);
    await generation.dispose();
  });

  it('activates the desktop renderer host from the generated catalog', async () => {
    const snapshot = await parseProfileSnapshotV2(bootstrapProfile);
    const generation = await new LoaderV2(desktopRendererDefinitionsV2, 'desktop-renderer').stage(
      snapshot
    );

    expect(
      generation.resolve<TargetHostDescriptorV2>(DESKTOP_RENDERER_HOST_SERVICE_V2, {
        kind: 'root',
      })
    ).toEqual({ target: 'desktop-renderer', strategy: 'native-generation-renderer-host' });
    expect(
      generation
        .resolve<RendererContributionRegistryV2>(
          DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
          { kind: 'root' }
        )
        .list()
    ).toHaveLength(46);
    expect(generation.fibers).toHaveLength(48);
    await generation.dispose();
  });

  it('rejects a production target module without its runtime definition', async () => {
    const snapshot = await parseProfileSnapshotV2(bootstrapProfile);

    await expect(new LoaderV2([], 'web').stage(snapshot)).rejects.toMatchObject({
      code: 'missing_module_definition',
    });
  });
});
