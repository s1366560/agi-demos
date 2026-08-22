import { StrictMode, type PropsWithChildren } from 'react';

import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  digestV2,
  RendererGenerationLeaseStoreV2,
  RendererPluginRuntimeV2,
  webRendererDefinitionsV2,
} from '@agistack/plugin-runtime';

import { useRendererGenerationLeaseV2 } from '../../plugins/webPluginGenerationV2';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

async function distributionAt(generation: number, version: number) {
  const snapshot = structuredClone(bootstrapProfile);
  snapshot.generation = generation;
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
      version,
      nonce: `renderer-hook-publication-${version}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  };
}

function StrictModeWrapper({ children }: PropsWithChildren) {
  return <StrictMode>{children}</StrictMode>;
}

describe('useRendererGenerationLeaseV2', () => {
  it('holds one committed lease across a StrictMode generation swap', async () => {
    const runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.apply(await distributionAt(1, 1));
    const store = new RendererGenerationLeaseStoreV2(runtime);
    store.activateRoot();
    const rendered = renderHook(() => useRendererGenerationLeaseV2(store), {
      wrapper: StrictModeWrapper,
    });
    const firstGeneration = rendered.result.current;

    await waitFor(() => expect(firstGeneration?.leaseCount).toBe(1));
    await act(async () => {
      await runtime.apply(await distributionAt(2, 2));
    });

    await waitFor(() => expect(rendered.result.current).not.toBe(firstGeneration));
    expect(firstGeneration?.disposed).toBe(true);
    expect(rendered.result.current?.leaseCount).toBe(1);

    rendered.unmount();
    await store.deactivateRoot();
    expect(runtime.getSnapshot()?.leaseCount).toBe(0);
    await runtime.close();
  });
});
