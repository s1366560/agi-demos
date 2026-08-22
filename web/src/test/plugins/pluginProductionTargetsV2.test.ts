import { describe, expect, it } from 'vitest';

import {
  DESKTOP_RENDERER_HOST_SERVICE_V2,
  desktopRendererHostDefinitionV2,
  LoaderV2,
  parseProfileSnapshotV2,
  type TargetHostDescriptorV2,
  WEB_RENDERER_HOST_SERVICE_V2,
  webRendererHostDefinitionV2,
} from '@agistack/plugin-runtime';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

describe('production protocol-v2 renderer target catalogs', () => {
  it('activates the web renderer host from the generated catalog', async () => {
    const snapshot = await parseProfileSnapshotV2(bootstrapProfile);
    const generation = await new LoaderV2([webRendererHostDefinitionV2], 'web').stage(snapshot);

    expect(
      generation.resolve<TargetHostDescriptorV2>(WEB_RENDERER_HOST_SERVICE_V2, { kind: 'root' })
    ).toEqual({ target: 'web', strategy: 'generation-renderer-host' });
    expect(generation.fibers).toHaveLength(1);
    await generation.dispose();
  });

  it('activates the desktop renderer host from the generated catalog', async () => {
    const snapshot = await parseProfileSnapshotV2(bootstrapProfile);
    const generation = await new LoaderV2(
      [desktopRendererHostDefinitionV2],
      'desktop-renderer'
    ).stage(snapshot);

    expect(
      generation.resolve<TargetHostDescriptorV2>(DESKTOP_RENDERER_HOST_SERVICE_V2, {
        kind: 'root',
      })
    ).toEqual({ target: 'desktop-renderer', strategy: 'native-generation-renderer-host' });
    expect(generation.fibers).toHaveLength(1);
    await generation.dispose();
  });

  it('rejects a production target module without its runtime definition', async () => {
    const snapshot = await parseProfileSnapshotV2(bootstrapProfile);

    await expect(new LoaderV2([], 'web').stage(snapshot)).rejects.toMatchObject({
      code: 'missing_module_definition',
    });
  });
});
