import { describe, expect, it } from 'vitest';

import {
  createWebRendererDefinitionsV2,
  digestV2,
  RendererPluginRuntimeV2,
} from '@agistack/plugin-runtime';

import {
  findWebToolResultSlotV2,
  selectWebUiSlotsV2,
  type WebUiSlotAuthorityStateV2,
} from '../../../routes/v2/webUiSlotAuthorityStateV2';
import { validateWebRendererContributionsV2 } from '../../../routes/v2/webRendererArtifactCatalogV2';
import { projectWebUiSlotAuthorityV2 } from '../../../routes/v2/webUiSlotAuthorityProjectionV2';

import bootstrapProfile from '../../../../../shared/profiles/memstack-default-bootstrap.v2.json';

const TOOL_RESULT_SLOT = Object.freeze({
  pluginId: 'acme',
  slot: 'tool_result_renderer' as const,
  id: 'memory-card',
  contract: 'tool-result:memory_search',
  moduleRef: 'builtin:memory-card',
  permission: 'ui.tools',
  sandbox: true,
});

async function generationWithUiSlotsEnabledV2(
  enabled: boolean,
  entryId = 'builtin-web-feature-ui-tool-result'
) {
  const snapshot = structuredClone(bootstrapProfile);
  const entry = snapshot.entries.find(({ entry_id }) => entry_id === entryId);
  if (!entry) throw new Error('web UI slot contribution fixture is missing');
  entry.enabled = enabled;
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
      nonce: `web-ui-slot-authority-${enabled ? 'enabled' : 'disabled'}`,
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  });
  expect(receipt.status).toBe('ack');
  const generation = runtime.getSnapshot();
  if (!generation) throw new Error('acknowledged generation was not published');
  return { generation, runtime };
}

describe('WebUiSlotAuthorityV2', () => {
  it('projects the active code-owned UI slot artifact', async () => {
    const { generation, runtime } = await generationWithUiSlotsEnabledV2(true);

    const state = projectWebUiSlotAuthorityV2(generation);
    expect(state.status).toBe('ready');
    expect(state.slotDefinitions.map(({ slot }) => slot).sort()).toEqual([
      'authenticated_shell_surface',
      'tool_result_renderer',
    ]);
    expect(state.uiSlotArtifactIds).toContain('web.ui-slots.authenticated-shell-surface.v1');
    expect(state.uiSlotArtifactIds).toContain('web.ui-slots.tool-result.v1');
    expect(state.renderers).toBeDefined();
    await runtime.close();
  });

  it('removes the tool renderer when its contribution is disabled', async () => {
    const { generation, runtime } = await generationWithUiSlotsEnabledV2(false);

    const state = projectWebUiSlotAuthorityV2(generation);
    expect(state.slotDefinitions.map(({ slot }) => slot)).toEqual(['authenticated_shell_surface']);
    expect(findWebToolResultSlotV2(state, 'memory_search')).toBeUndefined();
    expect(state.uiSlotArtifactIds).not.toContain('web.ui-slots.tool-result.v1');
    expect(state.uiSlotArtifactIds).toContain('web.ui-slots.authenticated-shell-surface.v1');
    await runtime.close();
  });

  it('removes the required shell authority when its independent profile effect is disabled', async () => {
    const { generation, runtime } = await generationWithUiSlotsEnabledV2(
      false,
      'builtin-web-authenticated-shell-surface'
    );

    const state = projectWebUiSlotAuthorityV2(generation);
    expect(state.slotDefinitions.map(({ slot }) => slot)).toEqual(['tool_result_renderer']);
    expect(state.slotDefinitions.some(({ slot }) => slot === 'authenticated_shell_surface')).toBe(
      false
    );
    expect(state.uiSlotArtifactIds).toContain('web.ui-slots.tool-result.v1');
    await runtime.close();
  });

  it('selects slots and tool renderers only from the projected V2 state', () => {
    const state: WebUiSlotAuthorityStateV2 = {
      slotDefinitions: [
        TOOL_RESULT_SLOT,
        { ...TOOL_RESULT_SLOT, id: 'other-card', contract: 'tool-result:other' },
      ],
      status: 'ready',
      uiSlotArtifactIds: ['test.ui-slots.v1'],
    };

    expect(selectWebUiSlotsV2(state, 'tool_result_renderer', 'tool-result:memory_search')).toEqual([
      TOOL_RESULT_SLOT,
    ]);
    expect(findWebToolResultSlotV2(state, 'memory_search')).toBe(TOOL_RESULT_SLOT);
    expect(
      findWebToolResultSlotV2({ ...state, status: 'loading' }, 'memory_search')
    ).toBeUndefined();
  });
});
