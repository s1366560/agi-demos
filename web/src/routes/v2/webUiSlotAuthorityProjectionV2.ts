import {
  WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  type RendererContributionRegistryV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

import {
  resolveWebRendererArtifactsV2,
  type WebUiSlotArtifactV2,
} from './webRendererArtifactCatalogV2';

import type { WebUiSlotAuthorityStateV2 } from './webUiSlotAuthorityStateV2';
import type { UiSlotDefinition } from '../../types/pluginSlots';

const EMPTY_UI_SLOT_ARTIFACT_IDS_V2: readonly string[] = Object.freeze([]);
const EMPTY_UI_SLOT_DEFINITIONS_V2: readonly UiSlotDefinition[] = Object.freeze([]);
const DISABLED_STATE_V2: WebUiSlotAuthorityStateV2 = Object.freeze({
  slotDefinitions: EMPTY_UI_SLOT_DEFINITIONS_V2,
  status: 'disabled',
  uiSlotArtifactIds: EMPTY_UI_SLOT_ARTIFACT_IDS_V2,
});
const LOADING_STATE_V2: WebUiSlotAuthorityStateV2 = Object.freeze({
  slotDefinitions: EMPTY_UI_SLOT_DEFINITIONS_V2,
  status: 'loading',
  uiSlotArtifactIds: EMPTY_UI_SLOT_ARTIFACT_IDS_V2,
});

export function projectWebUiSlotAuthorityV2(
  generation: RuntimeGenerationV2
): WebUiSlotAuthorityStateV2 {
  const registry = generation.resolve<RendererContributionRegistryV2>(
    WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
    { kind: 'root' }
  );
  const uiSlotArtifacts = resolveWebRendererArtifactsV2(registry.list()).filter(
    (artifact): artifact is WebUiSlotArtifactV2 => artifact.kind === 'ui-slot'
  );
  const slotDefinitions = uiSlotArtifacts.flatMap((artifact) => artifact.slotDefinitions);
  return Object.freeze({
    slotDefinitions: Object.freeze(slotDefinitions),
    status: 'ready',
    uiSlotArtifactIds: Object.freeze(uiSlotArtifacts.map((artifact) => artifact.id)),
  });
}

export function resolveWebUiSlotAuthorityStateV2(
  generation: RuntimeGenerationV2 | undefined,
  enabled: boolean
): WebUiSlotAuthorityStateV2 {
  if (!enabled) return DISABLED_STATE_V2;
  if (generation === undefined) return LOADING_STATE_V2;
  try {
    return projectWebUiSlotAuthorityV2(generation);
  } catch (error) {
    return Object.freeze({
      error,
      slotDefinitions: EMPTY_UI_SLOT_DEFINITIONS_V2,
      status: 'unavailable',
      uiSlotArtifactIds: EMPTY_UI_SLOT_ARTIFACT_IDS_V2,
    });
  }
}
