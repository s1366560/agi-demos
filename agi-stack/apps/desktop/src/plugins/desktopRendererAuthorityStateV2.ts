import { createContext, useContext, useMemo } from 'react';

import {
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
} from '../features/navigation/desktopProductionRouteRegistry';
import {
  createDesktopRouteRegistry,
  type DesktopRouteRegistry,
} from '../features/navigation/desktopRouteRegistry';

import type { DesktopRouteModule } from '../features/navigation/desktopRouteModule';
import type { DesktopRouteArtifactV2 } from './desktopRendererArtifactCatalogV2';
import type { DesktopRendererCompositionPortV2 } from './desktopRendererCompositionPortV2';
import type { UiSlotDefinition, UiSlotKind } from './uiSlotRegistry';

export type DesktopRendererAuthorityStatusV2 = 'disabled' | 'loading' | 'ready' | 'unavailable';

export interface DesktopRendererAuthorityStateV2 {
  readonly error?: unknown;
  readonly navigationArtifactIds: readonly string[];
  readonly navigationDiscoveryRouteIds: readonly string[];
  readonly navigationRouteIds: readonly string[];
  readonly routeArtifactIds: readonly string[];
  readonly routeArtifacts: readonly DesktopRouteArtifactV2[];
  readonly routeIds: readonly string[];
  readonly slotDefinitions: readonly UiSlotDefinition[];
  readonly status: DesktopRendererAuthorityStatusV2;
  readonly uiSlotArtifactIds: readonly string[];
}

const AUTHENTICATION_KERNEL_ROUTE_IDS_V2 = Object.freeze([
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
]);
const EMPTY_IDS_V2: readonly string[] = Object.freeze([]);
const EMPTY_ROUTE_ARTIFACTS_V2: readonly DesktopRouteArtifactV2[] = Object.freeze([]);
const EMPTY_UI_SLOT_DEFINITIONS_V2: readonly UiSlotDefinition[] = Object.freeze([]);
const DISABLED_STATE_V2: DesktopRendererAuthorityStateV2 = Object.freeze({
  navigationArtifactIds: EMPTY_IDS_V2,
  navigationDiscoveryRouteIds: EMPTY_IDS_V2,
  navigationRouteIds: EMPTY_IDS_V2,
  routeArtifactIds: EMPTY_IDS_V2,
  routeArtifacts: EMPTY_ROUTE_ARTIFACTS_V2,
  routeIds: EMPTY_IDS_V2,
  slotDefinitions: EMPTY_UI_SLOT_DEFINITIONS_V2,
  status: 'disabled',
  uiSlotArtifactIds: EMPTY_IDS_V2,
});

export const DesktopRendererAuthorityContextV2 =
  createContext<DesktopRendererAuthorityStateV2>(DISABLED_STATE_V2);

export function useDesktopRendererAuthorityV2(): DesktopRendererAuthorityStateV2 {
  return useContext(DesktopRendererAuthorityContextV2);
}

export function projectDesktopRouteRegistryV2(
  composition: DesktopRendererCompositionPortV2,
  state: DesktopRendererAuthorityStateV2,
): DesktopRouteRegistry<DesktopRouteModule> {
  const definitions: DesktopRouteRegistry<DesktopRouteModule>['definitions'][number][] = [];
  const seenRouteIds = new Set<string>();
  const authenticationRegistry = composition.createAuthenticationRouteRegistry();
  appendRouteDefinitionsV2(
    definitions,
    seenRouteIds,
    authenticationRegistry,
    AUTHENTICATION_KERNEL_ROUTE_IDS_V2,
    'authentication-kernel',
  );

  if (state.status === 'ready') {
    const artifactRouteIds = state.routeArtifacts.flatMap(({ routeIds }) => routeIds);
    if (
      artifactRouteIds.length !== state.routeIds.length ||
      artifactRouteIds.some((routeId, index) => routeId !== state.routeIds[index])
    ) {
      throw new Error('desktop_renderer_route_projection_mismatch');
    }
    for (const artifact of state.routeArtifacts) {
      appendRouteDefinitionsV2(
        definitions,
        seenRouteIds,
        composition.createRouteRegistry(artifact.id),
        artifact.routeIds,
        artifact.id,
      );
    }
  }
  return createDesktopRouteRegistry(definitions);
}

function appendRouteDefinitionsV2(
  definitions: DesktopRouteRegistry<DesktopRouteModule>['definitions'][number][],
  seenRouteIds: Set<string>,
  registry: DesktopRouteRegistry<DesktopRouteModule>,
  routeIds: readonly string[],
  source: string,
): void {
  for (const routeId of routeIds) {
    const definition = registry.byId.get(routeId);
    if (!definition) {
      throw new Error(`desktop_renderer_route_artifact_missing:${source}:${routeId}`);
    }
    if (seenRouteIds.has(routeId)) {
      throw new Error(`desktop_renderer_route_artifact_duplicate:${routeId}`);
    }
    seenRouteIds.add(routeId);
    definitions.push(definition);
  }
}

export function projectDesktopNavigationRegistryV2<TModule>(
  routes: DesktopRouteRegistry<TModule>,
  state: DesktopRendererAuthorityStateV2,
): DesktopRouteRegistry<TModule> {
  if (state.status !== 'ready') return createDesktopRouteRegistry([]);
  const definitions = state.navigationDiscoveryRouteIds.flatMap((routeId) => {
    const definition = routes.byId.get(routeId);
    return definition ? [definition] : [];
  });
  return createDesktopRouteRegistry(definitions);
}

export function isDesktopNavigationRouteEnabledV2(
  state: DesktopRendererAuthorityStateV2,
  routeId: string,
): boolean {
  return state.status === 'ready' && state.navigationRouteIds.includes(routeId);
}

export function selectDesktopUiSlotsV2(
  state: DesktopRendererAuthorityStateV2,
  kind?: UiSlotKind,
): readonly UiSlotDefinition[] {
  if (state.status !== 'ready') return EMPTY_UI_SLOT_DEFINITIONS_V2;
  if (kind === undefined) return state.slotDefinitions;
  return state.slotDefinitions.filter((slot) => slot.slot === kind);
}

export function useDesktopUiSlotsV2(kind?: UiSlotKind): readonly UiSlotDefinition[] {
  const state = useDesktopRendererAuthorityV2();
  return useMemo(() => selectDesktopUiSlotsV2(state, kind), [kind, state]);
}
