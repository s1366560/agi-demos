import {
  DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  type RendererContributionRegistryV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

import {
  resolveDesktopRendererArtifactsV2,
  type DesktopNavigationArtifactV2,
  type DesktopRouteArtifactV2,
  type DesktopUiSlotArtifactV2,
} from './desktopRendererArtifactCatalogV2';

import type { DesktopRendererAuthorityStateV2 } from './desktopRendererAuthorityStateV2';
import type { UiSlotDefinition } from './uiSlotRegistry';

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
const LOADING_STATE_V2: DesktopRendererAuthorityStateV2 = Object.freeze({
  navigationArtifactIds: EMPTY_IDS_V2,
  navigationDiscoveryRouteIds: EMPTY_IDS_V2,
  navigationRouteIds: EMPTY_IDS_V2,
  routeArtifactIds: EMPTY_IDS_V2,
  routeArtifacts: EMPTY_ROUTE_ARTIFACTS_V2,
  routeIds: EMPTY_IDS_V2,
  slotDefinitions: EMPTY_UI_SLOT_DEFINITIONS_V2,
  status: 'loading',
  uiSlotArtifactIds: EMPTY_IDS_V2,
});

export function projectDesktopRendererAuthorityV2(
  generation: RuntimeGenerationV2,
): DesktopRendererAuthorityStateV2 {
  const registry = generation.resolve<RendererContributionRegistryV2>(
    DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
    { kind: 'root' },
  );
  const artifacts = resolveDesktopRendererArtifactsV2(registry.list());
  const routeArtifacts = artifacts.filter(
    (artifact): artifact is DesktopRouteArtifactV2 => artifact.kind === 'route',
  );
  const navigationArtifacts = artifacts.filter(
    (artifact): artifact is DesktopNavigationArtifactV2 => artifact.kind === 'navigation',
  );
  const uiSlotArtifacts = artifacts.filter(
    (artifact): artifact is DesktopUiSlotArtifactV2 => artifact.kind === 'ui-slot',
  );
  return Object.freeze({
    navigationArtifactIds: freezeStringsV2(navigationArtifacts.map(({ id }) => id)),
    navigationDiscoveryRouteIds: freezeStringsV2(
      navigationArtifacts.flatMap(({ discoveryRouteIds }) => discoveryRouteIds),
    ),
    navigationRouteIds: freezeStringsV2(navigationArtifacts.flatMap(({ routeIds }) => routeIds)),
    routeArtifactIds: freezeStringsV2(routeArtifacts.map(({ id }) => id)),
    routeArtifacts: Object.freeze(routeArtifacts),
    routeIds: freezeStringsV2(routeArtifacts.flatMap(({ routeIds }) => routeIds)),
    slotDefinitions: Object.freeze(
      uiSlotArtifacts.flatMap(({ slotDefinitions }) => slotDefinitions),
    ),
    status: 'ready',
    uiSlotArtifactIds: freezeStringsV2(uiSlotArtifacts.map(({ id }) => id)),
  });
}

export function resolveDesktopRendererAuthorityStateV2(
  generation: RuntimeGenerationV2 | undefined,
  enabled: boolean,
): DesktopRendererAuthorityStateV2 {
  if (!enabled) return DISABLED_STATE_V2;
  if (generation === undefined) return LOADING_STATE_V2;
  try {
    return projectDesktopRendererAuthorityV2(generation);
  } catch (error) {
    return Object.freeze({
      error,
      navigationArtifactIds: EMPTY_IDS_V2,
      navigationDiscoveryRouteIds: EMPTY_IDS_V2,
      navigationRouteIds: EMPTY_IDS_V2,
      routeArtifactIds: EMPTY_IDS_V2,
      routeArtifacts: EMPTY_ROUTE_ARTIFACTS_V2,
      routeIds: EMPTY_IDS_V2,
      slotDefinitions: EMPTY_UI_SLOT_DEFINITIONS_V2,
      status: 'unavailable',
      uiSlotArtifactIds: EMPTY_IDS_V2,
    });
  }
}

function freezeStringsV2(values: readonly string[]): readonly string[] {
  return Object.freeze([...values]);
}
