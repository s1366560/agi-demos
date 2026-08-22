import { describe, expect, it, vi } from 'vitest';

import {
  RendererPluginRuntimeV2,
  type TargetHostDescriptorV2,
  WEB_RENDERER_HOST_SERVICE_V2,
  webRendererHostDefinitionV2,
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
    const runtime = new RendererPluginRuntimeV2('web', [webRendererHostDefinitionV2]);
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
    const runtime = new RendererPluginRuntimeV2('web', [webRendererHostDefinitionV2]);
    await runtime.apply(distribution(bootstrapProfile));
    const lastGood = runtime.getSnapshot();

    await expect(
      runtime.apply({ ...distribution(bootstrapProfile), schema_version: 1 })
    ).rejects.toMatchObject({ code: 'incompatible_schema_version' });

    expect(runtime.getSnapshot()).toBe(lastGood);
    await runtime.close();
  });

  it('uses a local snapshot as a replaceable bootstrap instead of a publication version', async () => {
    const runtime = new RendererPluginRuntimeV2('web', [webRendererHostDefinitionV2]);

    await runtime.bootstrap(bootstrapProfile);
    const localGeneration = runtime.getSnapshot();
    const receipt = await runtime.apply(distribution(bootstrapProfile));

    expect(localGeneration).toBeDefined();
    expect(receipt.status).toBe('ack');
    expect(localGeneration?.disposed).toBe(true);
    expect(runtime.getSnapshot()).not.toBe(localGeneration);
    await runtime.close();
  });
});
