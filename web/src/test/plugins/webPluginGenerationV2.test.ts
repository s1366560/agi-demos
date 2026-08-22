import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  RendererPluginRuntimeV2,
  WEB_RENDERER_HOST_SERVICE_V2,
  webRendererHostDefinitionV2,
} from '@agistack/plugin-runtime';

import {
  startWebPluginGenerationPollingV2,
  type WebPluginDistributionSourceV2,
} from '../../plugins/webPluginGenerationV2';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

function distribution() {
  return {
    schema_version: 2,
    descriptor: {
      profile_id: bootstrapProfile.profile_id,
      generation: bootstrapProfile.generation,
      digest: bootstrapProfile.digest,
    },
    snapshot: bootstrapProfile,
    envelope: {
      version: 1,
      nonce: 'web-renderer-publication-v2',
      snapshot_digest: bootstrapProfile.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('web plugin generation polling', () => {
  it('loads immediately, polls serially, and stops without discarding last-good', async () => {
    vi.useFakeTimers();
    const runtime = new RendererPluginRuntimeV2('web', [webRendererHostDefinitionV2]);
    const source: WebPluginDistributionSourceV2 = vi.fn(async () => distribution());

    const stop = startWebPluginGenerationPollingV2(runtime, source, 100);
    await vi.waitFor(() => {
      expect(runtime.getSnapshot()).toBeDefined();
    });
    await vi.advanceTimersByTimeAsync(100);

    expect(source).toHaveBeenCalledTimes(2);
    expect(runtime.getSnapshot()?.resolve(WEB_RENDERER_HOST_SERVICE_V2, { kind: 'root' })).toEqual({
      target: 'web',
      strategy: 'generation-renderer-host',
    });
    stop();
    await vi.advanceTimersByTimeAsync(200);
    expect(source).toHaveBeenCalledTimes(2);
    expect(runtime.getSnapshot()).toBeDefined();
    await runtime.close();
  });
});
