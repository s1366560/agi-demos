import {
  DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  type RegisteredRendererContributionV2,
  type RendererContributionRegistryV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

import {
  resolveDesktopRendererArtifactsV2,
  type DesktopRouteArtifactV2,
} from './desktopRendererArtifactCatalogV2';

import type { DesktopRendererAuthorityStateV2 } from './desktopRendererAuthorityStateV2';
import type { AuthorizedUiSlotDefinitionV2 } from './uiSlotRegistry';

const EMPTY_IDS_V2: readonly string[] = Object.freeze([]);
const EMPTY_ROUTE_ARTIFACTS_V2: readonly DesktopRouteArtifactV2[] = Object.freeze([]);
const EMPTY_UI_SLOT_DEFINITIONS_V2: readonly AuthorizedUiSlotDefinitionV2[] = Object.freeze([]);
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
  const contributions = registry.list();
  const artifacts = resolveDesktopRendererArtifactsV2(contributions);
  const sourceEntryIds = sourceEntryIdsForArtifactsV2(contributions);
  if (sourceEntryIds.length !== artifacts.length) {
    throw new Error('desktop_renderer_artifact_source_projection_mismatch');
  }
  const resolvedArtifacts = artifacts.map((artifact, index) =>
    Object.freeze({ artifact, sourceEntryId: sourceEntryIds[index] }),
  );
  const routeArtifacts = resolvedArtifacts.flatMap(({ artifact }) =>
    artifact.kind === 'route' ? [artifact] : [],
  );
  const navigationArtifacts = resolvedArtifacts.flatMap(({ artifact }) =>
    artifact.kind === 'navigation' ? [artifact] : [],
  );
  const uiSlotArtifacts = resolvedArtifacts.flatMap(({ artifact, sourceEntryId }) =>
    artifact.kind === 'ui-slot' ? [{ artifact, sourceEntryId }] : [],
  );
  const permissionsByEntryId = new Map(
    generation.snapshot.entries.map((entry) => [entry.entry_id, entry.permissions] as const),
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
      uiSlotArtifacts.flatMap(({ artifact, sourceEntryId }) => {
        const grantedPermissions = permissionsByEntryId.get(sourceEntryId);
        if (grantedPermissions === undefined) {
          throw new Error(`desktop_renderer_source_entry_missing:${sourceEntryId}`);
        }
        return artifact.slotDefinitions.map((definition) =>
          Object.freeze({
            ...definition,
            grantedPermissions: Object.freeze([...grantedPermissions]),
            sourceEntryId,
          }),
        );
      }),
    ),
    status: 'ready',
    uiSlotArtifactIds: freezeStringsV2(uiSlotArtifacts.map(({ artifact }) => artifact.id)),
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

function sourceEntryIdsForArtifactsV2(
  contributions: readonly RegisteredRendererContributionV2[],
): readonly string[] {
  return Object.freeze(
    contributions.flatMap((contribution) =>
      (contribution.payload.artifact_refs as readonly string[]).map(
        () => contribution.sourceEntryId,
      ),
    ),
  );
}
