import {
  createAppRouteRegistry,
  type AppRouteRegistryRefs,
} from '../features/navigation/appRouteRegistry';
import { DESKTOP_NAVIGATION_METADATA } from '../features/navigation/desktopCanonicalNavigationCatalog';
import {
  DESKTOP_PRODUCTION_ROUTE_IDS,
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
} from '../features/navigation/desktopProductionRouteRegistry';

import type { DesktopRouteModule } from '../features/navigation/desktopRouteModule';
import type { DesktopRouteRegistry } from '../features/navigation/desktopRouteRegistry';
import type { UiSlotDefinition } from './uiSlotRegistry';

type DesktopRendererContributionKindV2 = 'route' | 'navigation' | 'ui-slot';

interface DesktopRendererContributionV2 {
  readonly id: string;
  readonly kind: DesktopRendererContributionKindV2;
  readonly order: number;
  readonly payload: Readonly<Record<string, unknown>>;
  readonly sourceEntryId: string;
}

export const DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2 = 'desktop.routes.production.v1';
export const DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2 = 'desktop.navigation.default.v1';
export const DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2 = 'desktop.ui-slots.default.v1';

const AUTHENTICATION_KERNEL_ROUTE_IDS_V2 = new Set<string>([
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
]);
const DEFAULT_BUSINESS_ROUTE_IDS_V2 = Object.freeze(
  DESKTOP_PRODUCTION_ROUTE_IDS.filter(
    (routeId) => !AUTHENTICATION_KERNEL_ROUTE_IDS_V2.has(routeId),
  ),
);
const DEFAULT_NAVIGATION_ROUTE_IDS_V2 = Object.freeze([
  ...DESKTOP_NAVIGATION_METADATA.map(({ routeId }) => routeId),
]);
const DEFAULT_UI_SLOT_DEFINITIONS_V2: readonly UiSlotDefinition[] = Object.freeze([
  Object.freeze({
    pluginId: 'builtin-ui',
    slot: 'settings_page',
    id: 'plugin-settings',
    contract: 'ui-builtin:plugin-settings',
    moduleRef: 'builtin:plugin-settings',
    permission: 'ui.settings.plugins',
    sandbox: true,
  }),
  Object.freeze({
    pluginId: 'builtin-ui',
    slot: 'tool_result_renderer',
    id: 'structured-tool-result',
    contract: 'ui-builtin:structured-tool-result',
    moduleRef: 'builtin:structured-tool-result',
    permission: 'ui.render',
    sandbox: true,
  }),
]);

interface DesktopRendererArtifactBaseV2 {
  readonly id: string;
  readonly kind: DesktopRendererContributionKindV2;
}

export interface DesktopRouteArtifactV2 extends DesktopRendererArtifactBaseV2 {
  readonly createRegistry: (refs: AppRouteRegistryRefs) => DesktopRouteRegistry<DesktopRouteModule>;
  readonly kind: 'route';
  readonly routeIds: readonly string[];
}

export interface DesktopNavigationArtifactV2 extends DesktopRendererArtifactBaseV2 {
  readonly discoveryRouteIds: readonly string[];
  readonly kind: 'navigation';
  readonly routeIds: readonly string[];
}

export interface DesktopUiSlotArtifactV2 extends DesktopRendererArtifactBaseV2 {
  readonly kind: 'ui-slot';
  readonly slotDefinitions: readonly UiSlotDefinition[];
}

export type DesktopRendererArtifactV2 =
  | DesktopRouteArtifactV2
  | DesktopNavigationArtifactV2
  | DesktopUiSlotArtifactV2;

export class DesktopRendererArtifactErrorV2 extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'DesktopRendererArtifactErrorV2';
  }
}

const DESKTOP_RENDERER_ARTIFACT_CATALOG_V2 = new Map<string, DesktopRendererArtifactV2>([
  [
    DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2,
    defineDesktopRouteArtifactV2(
      DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2,
      DEFAULT_BUSINESS_ROUTE_IDS_V2,
      createAppRouteRegistry,
    ),
  ],
  [
    DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      discoveryRouteIds: Object.freeze(
        DESKTOP_NAVIGATION_METADATA.map(({ routeId }) => routeId),
      ),
      id: DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
      routeIds: DEFAULT_NAVIGATION_ROUTE_IDS_V2,
    }),
  ],
  [
    DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
    defineDesktopUiSlotArtifactV2(
      DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
      DEFAULT_UI_SLOT_DEFINITIONS_V2,
    ),
  ],
]);

export function defineDesktopRouteArtifactV2(
  id: string,
  routeIds: readonly string[],
  createRegistry: (refs: AppRouteRegistryRefs) => DesktopRouteRegistry<DesktopRouteModule>,
): DesktopRouteArtifactV2 {
  if (!id.trim()) {
    throw artifactErrorV2('desktop_renderer_route_artifact_id_required', id);
  }
  if (routeIds.length === 0 || routeIds.some((routeId) => !routeId.trim())) {
    throw artifactErrorV2('desktop_renderer_route_artifact_routes_invalid', id);
  }
  if (new Set(routeIds).size !== routeIds.length) {
    throw artifactErrorV2('desktop_renderer_route_artifact_routes_duplicate', id);
  }
  return Object.freeze({
    createRegistry,
    id,
    kind: 'route',
    routeIds: Object.freeze([...routeIds]),
  });
}

export function defineDesktopUiSlotArtifactV2(
  id: string,
  slotDefinitions: readonly UiSlotDefinition[],
): DesktopUiSlotArtifactV2 {
  const owners = new Set<string>();
  const definitions = slotDefinitions.map((slot) => {
    const ownerKey = `${slot.pluginId}/${slot.id}`;
    if (owners.has(ownerKey)) {
      throw artifactErrorV2('desktop_renderer_ui_slot_conflict', ownerKey);
    }
    owners.add(ownerKey);
    if (!slot.moduleRef.startsWith('builtin:')) {
      throw artifactErrorV2('desktop_renderer_ui_slot_module_ref_invalid', ownerKey);
    }
    if (!slot.permission.startsWith('ui.')) {
      throw artifactErrorV2('desktop_renderer_ui_slot_permission_invalid', ownerKey);
    }
    if (!slot.sandbox) {
      throw artifactErrorV2('desktop_renderer_ui_slot_sandbox_required', ownerKey);
    }
    return Object.freeze({ ...slot });
  });
  return Object.freeze({
    id,
    kind: 'ui-slot',
    slotDefinitions: Object.freeze(definitions),
  });
}

export function validateDesktopRendererContributionsV2(
  contributions: readonly DesktopRendererContributionV2[],
): void {
  resolveDesktopRendererArtifactsV2(contributions);
}

export function resolveDesktopRendererArtifactsV2(
  contributions: readonly DesktopRendererContributionV2[],
): readonly DesktopRendererArtifactV2[] {
  const artifacts: DesktopRendererArtifactV2[] = [];
  const routeOwners = new Map<string, string>();
  const navigationOwners = new Map<string, string>();
  const uiSlotArtifactOwners = new Map<string, string>();
  const ordered = [...contributions].sort(
    (left, right) =>
      left.order - right.order ||
      `${left.kind}:${left.id}`.localeCompare(`${right.kind}:${right.id}`),
  );

  for (const contribution of ordered) {
    for (const artifactRef of artifactRefsV2(contribution)) {
      const artifact = DESKTOP_RENDERER_ARTIFACT_CATALOG_V2.get(artifactRef);
      if (!artifact) {
        throw artifactErrorV2('desktop_renderer_artifact_unknown', artifactRef);
      }
      if (artifact.kind !== contribution.kind) {
        throw artifactErrorV2(
          'desktop_renderer_artifact_kind_mismatch',
          `${artifactRef}:${contribution.kind}`,
        );
      }
      if (artifact.kind === 'route') {
        validateRouteOwnershipV2(routeOwners, artifact.routeIds, contribution);
      } else if (artifact.kind === 'navigation') {
        validateRouteOwnershipV2(navigationOwners, artifact.routeIds, contribution);
      } else {
        validateUiSlotArtifactOwnershipV2(uiSlotArtifactOwners, artifact, contribution);
      }
      artifacts.push(artifact);
    }
  }

  return Object.freeze(artifacts);
}

function artifactRefsV2(contribution: DesktopRendererContributionV2): readonly string[] {
  const payload = contribution.payload;
  const keys = Object.keys(payload).sort();
  const artifactRefs = payload.artifact_refs;
  if (
    keys.length !== 2 ||
    keys[0] !== 'artifact_refs' ||
    keys[1] !== 'schema_version' ||
    payload.schema_version !== 1 ||
    !Array.isArray(artifactRefs) ||
    artifactRefs.length === 0 ||
    artifactRefs.some((value) => typeof value !== 'string' || value.length === 0) ||
    new Set(artifactRefs).size !== artifactRefs.length
  ) {
    throw artifactErrorV2('desktop_renderer_artifact_payload_invalid', contribution.id);
  }
  return artifactRefs as readonly string[];
}

function validateRouteOwnershipV2(
  owners: Map<string, string>,
  routeIds: readonly string[],
  contribution: DesktopRendererContributionV2,
): void {
  for (const routeId of routeIds) {
    const existingOwner = owners.get(routeId);
    if (existingOwner !== undefined) {
      throw artifactErrorV2(
        'desktop_renderer_route_conflict',
        `${routeId}:${existingOwner}:${contribution.id}`,
      );
    }
    owners.set(routeId, contribution.id);
  }
}

function validateUiSlotArtifactOwnershipV2(
  owners: Map<string, string>,
  artifact: DesktopUiSlotArtifactV2,
  contribution: DesktopRendererContributionV2,
): void {
  const existingOwner = owners.get(artifact.id);
  if (existingOwner !== undefined) {
    throw artifactErrorV2(
      'desktop_renderer_ui_slot_artifact_conflict',
      `${artifact.id}:${existingOwner}:${contribution.id}`,
    );
  }
  owners.set(artifact.id, contribution.id);
}

function artifactErrorV2(code: string, detail: string): DesktopRendererArtifactErrorV2 {
  return new DesktopRendererArtifactErrorV2(code, `${code}:${detail}`);
}
