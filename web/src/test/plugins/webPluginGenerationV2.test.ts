import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const { getDistributionMock } = vi.hoisted(() => ({
  getDistributionMock: vi.fn(),
}));

vi.mock('../../services/client/httpClient', () => ({
  httpClient: { get: getDistributionMock },
}));

import {
  RendererPluginRuntimeV2,
  WEB_RENDERER_HOST_SERVICE_V2,
  webRendererDefinitionsV2,
} from '@agistack/plugin-runtime';

import {
  activateWebPluginGenerationRootV2,
  deactivateWebPluginGenerationRootV2,
  startWebPluginGenerationPollingV2,
  type WebPluginDistributionSourceV2,
  useWebPluginGenerationV2,
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

afterEach(async () => {
  await deactivateWebPluginGenerationRootV2();
  getDistributionMock.mockReset();
  vi.useRealTimers();
});

describe('web plugin generation polling', () => {
  it('loads immediately, polls serially, and stops without discarding last-good', async () => {
    vi.useFakeTimers();
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
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

  it('releases last-good when the authenticated generation host becomes disabled', async () => {
    getDistributionMock.mockResolvedValue(distribution());
    activateWebPluginGenerationRootV2();
    const rendered = renderHook(
      ({ enabled }: { enabled: boolean }) => useWebPluginGenerationV2(enabled),
      { initialProps: { enabled: true } }
    );
    await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
    const firstGeneration = rendered.result.current.generation;

    rendered.rerender({ enabled: false });

    await waitFor(() => expect(firstGeneration?.disposed).toBe(true));
    expect(rendered.result.current).toMatchObject({
      status: 'empty',
      generation: undefined,
      error: undefined,
    });

    rendered.rerender({ enabled: true });
    await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
    expect(rendered.result.current.generation).not.toBe(firstGeneration);
    rendered.unmount();
  });
});
