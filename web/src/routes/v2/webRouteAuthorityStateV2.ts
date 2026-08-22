import { createContext, useContext } from 'react';

import {
  WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  type RendererContributionRegistryV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

import {
  resolveWebRendererArtifactsV2,
  type WebRouteArtifactV2,
} from './webRendererArtifactCatalogV2';

export type WebRouteAuthorityStatusV2 = 'disabled' | 'loading' | 'ready' | 'unavailable';

export interface WebRouteAuthorityStateV2 {
  readonly error?: unknown;
  readonly routeArtifacts: readonly WebRouteArtifactV2[];
  readonly routeArtifactIds: readonly string[];
  readonly status: WebRouteAuthorityStatusV2;
}

const EMPTY_ROUTE_ARTIFACTS_V2: readonly WebRouteArtifactV2[] = Object.freeze([]);
const EMPTY_ROUTE_ARTIFACT_IDS_V2: readonly string[] = Object.freeze([]);
const DISABLED_STATE_V2: WebRouteAuthorityStateV2 = Object.freeze({
  routeArtifacts: EMPTY_ROUTE_ARTIFACTS_V2,
  routeArtifactIds: EMPTY_ROUTE_ARTIFACT_IDS_V2,
  status: 'disabled',
});
const LOADING_STATE_V2: WebRouteAuthorityStateV2 = Object.freeze({
  routeArtifacts: EMPTY_ROUTE_ARTIFACTS_V2,
  routeArtifactIds: EMPTY_ROUTE_ARTIFACT_IDS_V2,
  status: 'loading',
});

export const WebRouteAuthorityContextV2 =
  createContext<WebRouteAuthorityStateV2>(DISABLED_STATE_V2);

export function useWebRouteAuthorityV2(): WebRouteAuthorityStateV2 {
  return useContext(WebRouteAuthorityContextV2);
}

export function projectWebRouteAuthorityV2(
  generation: RuntimeGenerationV2
): WebRouteAuthorityStateV2 {
  const registry = generation.resolve<RendererContributionRegistryV2>(
    WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
    { kind: 'root' }
  );
  const routeArtifacts = resolveWebRendererArtifactsV2(registry.list()).filter(
    (artifact): artifact is WebRouteArtifactV2 => artifact.kind === 'route'
  );
  const routeArtifactIds = routeArtifacts.map((artifact) => artifact.id);
  return Object.freeze({
    routeArtifacts: Object.freeze(routeArtifacts),
    routeArtifactIds: Object.freeze(routeArtifactIds),
    status: 'ready',
  });
}

export function resolveWebRouteAuthorityStateV2(
  generation: RuntimeGenerationV2 | undefined,
  enabled: boolean
): WebRouteAuthorityStateV2 {
  if (!enabled) return DISABLED_STATE_V2;
  if (generation === undefined) return LOADING_STATE_V2;
  try {
    return projectWebRouteAuthorityV2(generation);
  } catch (error) {
    return Object.freeze({
      error,
      routeArtifacts: EMPTY_ROUTE_ARTIFACTS_V2,
      routeArtifactIds: EMPTY_ROUTE_ARTIFACT_IDS_V2,
      status: 'unavailable',
    });
  }
}
