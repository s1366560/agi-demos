import {
  RuntimeV2Error,
  type RegisteredRendererContributionV2,
  type RendererContributionKindV2,
} from '@agistack/plugin-runtime';

export const WEB_DEFAULT_ROUTE_ARTIFACT_ID_V2 = 'web.routes.default-business.v1';
export const WEB_DEFAULT_NAVIGATION_ARTIFACT_ID_V2 = 'web.navigation.default.v1';
export const WEB_DEFAULT_UI_SLOT_ARTIFACT_ID_V2 = 'web.ui-slots.default.v1';

interface WebRendererArtifactBaseV2 {
  readonly id: string;
  readonly kind: RendererContributionKindV2;
}

export interface WebRouteArtifactV2 extends WebRendererArtifactBaseV2 {
  readonly kind: 'route';
  readonly routeKeys: readonly string[];
}

export interface WebNavigationArtifactV2 extends WebRendererArtifactBaseV2 {
  readonly kind: 'navigation';
}

export interface WebUiSlotArtifactV2 extends WebRendererArtifactBaseV2 {
  readonly kind: 'ui-slot';
}

export type WebRendererArtifactV2 =
  | WebRouteArtifactV2
  | WebNavigationArtifactV2
  | WebUiSlotArtifactV2;

const WEB_RENDERER_ARTIFACT_CATALOG_V2 = new Map<string, WebRendererArtifactV2>([
  [
    WEB_DEFAULT_ROUTE_ARTIFACT_ID_V2,
    Object.freeze({
      id: WEB_DEFAULT_ROUTE_ARTIFACT_ID_V2,
      kind: 'route',
      routeKeys: Object.freeze(['root:web.default-business-routes']),
    }),
  ],
  [
    WEB_DEFAULT_NAVIGATION_ARTIFACT_ID_V2,
    Object.freeze({
      id: WEB_DEFAULT_NAVIGATION_ARTIFACT_ID_V2,
      kind: 'navigation',
    }),
  ],
  [
    WEB_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
    Object.freeze({
      id: WEB_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
      kind: 'ui-slot',
    }),
  ],
]);

export function validateWebRendererContributionsV2(
  contributions: readonly RegisteredRendererContributionV2[]
): void {
  resolveWebRendererArtifactsV2(contributions);
}

export function resolveWebRendererArtifactsV2(
  contributions: readonly RegisteredRendererContributionV2[]
): readonly WebRendererArtifactV2[] {
  const artifacts: WebRendererArtifactV2[] = [];
  const routeOwners = new Map<string, string>();
  const ordered = [...contributions].sort(
    (left, right) =>
      left.order - right.order ||
      `${left.kind}:${left.id}`.localeCompare(`${right.kind}:${right.id}`)
  );

  for (const contribution of ordered) {
    for (const artifactRef of artifactRefsV2(contribution)) {
      const artifact = WEB_RENDERER_ARTIFACT_CATALOG_V2.get(artifactRef);
      if (!artifact) {
        throw new RuntimeV2Error(
          'renderer_artifact_unknown',
          `renderer_artifact_unknown:${artifactRef}`
        );
      }
      if (artifact.kind !== contribution.kind) {
        throw new RuntimeV2Error(
          'renderer_artifact_kind_mismatch',
          `renderer_artifact_kind_mismatch:${artifactRef}:${contribution.kind}`
        );
      }
      if (artifact.kind === 'route') {
        validateRouteKeysV2(routeOwners, artifact, contribution);
      }
      artifacts.push(artifact);
    }
  }

  return Object.freeze(artifacts);
}

function artifactRefsV2(contribution: RegisteredRendererContributionV2): readonly string[] {
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
    throw new RuntimeV2Error(
      'renderer_artifact_payload_invalid',
      `renderer_artifact_payload_invalid:${contribution.id}`
    );
  }
  return artifactRefs as readonly string[];
}

function validateRouteKeysV2(
  owners: Map<string, string>,
  artifact: WebRouteArtifactV2,
  contribution: RegisteredRendererContributionV2
): void {
  for (const routeKey of artifact.routeKeys) {
    const existingOwner = owners.get(routeKey);
    if (existingOwner !== undefined) {
      throw new RuntimeV2Error(
        'renderer_route_path_conflict',
        `renderer_route_path_conflict:${routeKey}:${existingOwner}:${contribution.id}`
      );
    }
    owners.set(routeKey, contribution.id);
  }
}
