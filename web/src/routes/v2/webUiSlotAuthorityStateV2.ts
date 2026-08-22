import { createContext, useContext, useMemo } from 'react';

import type { UiSlotDefinition, UiSlotKind } from '../../types/pluginSlots';

export type WebUiSlotAuthorityStatusV2 = 'disabled' | 'loading' | 'ready' | 'unavailable';

export interface WebUiSlotAuthorityStateV2 {
  readonly error?: unknown;
  readonly slotDefinitions: readonly UiSlotDefinition[];
  readonly status: WebUiSlotAuthorityStatusV2;
  readonly uiSlotArtifactIds: readonly string[];
}

const EMPTY_UI_SLOT_ARTIFACT_IDS_V2: readonly string[] = Object.freeze([]);
const EMPTY_UI_SLOT_DEFINITIONS_V2: readonly UiSlotDefinition[] = Object.freeze([]);
const DISABLED_STATE_V2: WebUiSlotAuthorityStateV2 = Object.freeze({
  slotDefinitions: EMPTY_UI_SLOT_DEFINITIONS_V2,
  status: 'disabled',
  uiSlotArtifactIds: EMPTY_UI_SLOT_ARTIFACT_IDS_V2,
});

export const WebUiSlotAuthorityContextV2 =
  createContext<WebUiSlotAuthorityStateV2>(DISABLED_STATE_V2);

export function useWebUiSlotAuthorityV2(): WebUiSlotAuthorityStateV2 {
  return useContext(WebUiSlotAuthorityContextV2);
}

export function selectWebUiSlotsV2(
  state: WebUiSlotAuthorityStateV2,
  kind: UiSlotKind,
  contractId?: string
): readonly UiSlotDefinition[] {
  if (state.status !== 'ready') return EMPTY_UI_SLOT_DEFINITIONS_V2;
  return state.slotDefinitions.filter(
    (slot) => slot.slot === kind && (contractId === undefined || slot.contract === contractId)
  );
}

export function useWebUiSlotsV2(
  kind: UiSlotKind,
  contractId?: string
): readonly UiSlotDefinition[] {
  const state = useWebUiSlotAuthorityV2();
  return useMemo(() => selectWebUiSlotsV2(state, kind, contractId), [contractId, kind, state]);
}

export function findWebToolResultSlotV2(
  state: WebUiSlotAuthorityStateV2,
  toolName: string
): UiSlotDefinition | undefined {
  if (state.status !== 'ready') return undefined;
  return state.slotDefinitions.find(
    (slot) =>
      slot.slot === 'tool_result_renderer' &&
      (slot.contract === `tool-result:${toolName}` || slot.id === toolName)
  );
}

export function useWebToolResultSlotV2(toolName: string): UiSlotDefinition | undefined {
  const state = useWebUiSlotAuthorityV2();
  return useMemo(() => findWebToolResultSlotV2(state, toolName), [state, toolName]);
}
