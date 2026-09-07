import { createContext, useContext, useMemo } from 'react';

import { matchPath } from 'react-router-dom';

import {
  WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  type RendererContributionRegistryV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

import {
  resolveWebRendererArtifactsV2,
  type WebNavigationArtifactV2,
} from './webRendererArtifactCatalogV2';

import type {
  DerivedNavigationItem,
  NavigationRuntimeContext,
  TopNavigationContext,
} from '../../config/navigation';


export type WebNavigationAuthorityStatusV2 = 'disabled' | 'loading' | 'ready' | 'unavailable';

export interface WebNavigationAuthorityStateV2 {
  readonly activeRouteKeys: readonly string[];
  readonly error?: unknown;
  readonly navigationArtifacts: readonly WebNavigationArtifactV2[];
  readonly navigationArtifactIds: readonly string[];
  readonly status: WebNavigationAuthorityStatusV2;
}

const EMPTY_NAVIGATION_ARTIFACTS_V2: readonly WebNavigationArtifactV2[] = Object.freeze([]);
const EMPTY_NAVIGATION_ARTIFACT_IDS_V2: readonly string[] = Object.freeze([]);
const EMPTY_ROUTE_KEYS_V2: readonly string[] = Object.freeze([]);
const EMPTY_NAVIGATION_ITEMS_V2: readonly DerivedNavigationItem[] = Object.freeze([]);
const DISABLED_STATE_V2: WebNavigationAuthorityStateV2 = Object.freeze({
  activeRouteKeys: EMPTY_ROUTE_KEYS_V2,
  navigationArtifacts: EMPTY_NAVIGATION_ARTIFACTS_V2,
  navigationArtifactIds: EMPTY_NAVIGATION_ARTIFACT_IDS_V2,
  status: 'disabled',
});
const LOADING_STATE_V2: WebNavigationAuthorityStateV2 = Object.freeze({
  activeRouteKeys: EMPTY_ROUTE_KEYS_V2,
  navigationArtifacts: EMPTY_NAVIGATION_ARTIFACTS_V2,
  navigationArtifactIds: EMPTY_NAVIGATION_ARTIFACT_IDS_V2,
  status: 'loading',
});

export const WebNavigationAuthorityContextV2 =
  createContext<WebNavigationAuthorityStateV2>(DISABLED_STATE_V2);

export function useWebNavigationAuthorityV2(): WebNavigationAuthorityStateV2 {
  return useContext(WebNavigationAuthorityContextV2);
}

export function projectWebNavigationAuthorityV2(
  generation: RuntimeGenerationV2,
  activeRouteKeys: readonly string[]
): WebNavigationAuthorityStateV2 {
  const registry = generation.resolve<RendererContributionRegistryV2>(
    WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
    { kind: 'root' }
  );
  const navigationArtifacts = resolveWebRendererArtifactsV2(registry.list()).filter(
    (artifact): artifact is WebNavigationArtifactV2 => artifact.kind === 'navigation'
  );
  return Object.freeze({
    activeRouteKeys: Object.freeze([...activeRouteKeys]),
    navigationArtifacts: Object.freeze(navigationArtifacts),
    navigationArtifactIds: Object.freeze(navigationArtifacts.map((artifact) => artifact.id)),
    status: 'ready',
  });
}

export function resolveWebNavigationAuthorityStateV2(
  generation: RuntimeGenerationV2 | undefined,
  activeRouteKeys: readonly string[],
  enabled: boolean,
  routeAuthorityReady: boolean,
  routeAuthorityError?: unknown
): WebNavigationAuthorityStateV2 {
  if (!enabled) return DISABLED_STATE_V2;
  if (routeAuthorityError !== undefined) {
    return Object.freeze({
      activeRouteKeys: EMPTY_ROUTE_KEYS_V2,
      error: routeAuthorityError,
      navigationArtifacts: EMPTY_NAVIGATION_ARTIFACTS_V2,
      navigationArtifactIds: EMPTY_NAVIGATION_ARTIFACT_IDS_V2,
      status: 'unavailable',
    });
  }
  if (generation === undefined || !routeAuthorityReady) return LOADING_STATE_V2;
  try {
    return projectWebNavigationAuthorityV2(generation, activeRouteKeys);
  } catch (error) {
    return Object.freeze({
      activeRouteKeys: EMPTY_ROUTE_KEYS_V2,
      error,
      navigationArtifacts: EMPTY_NAVIGATION_ARTIFACTS_V2,
      navigationArtifactIds: EMPTY_NAVIGATION_ARTIFACT_IDS_V2,
      status: 'unavailable',
    });
  }
}

export function selectWebTopNavigationItemsV2(
  state: WebNavigationAuthorityStateV2,
  context: TopNavigationContext,
  runtimeContext: NavigationRuntimeContext = {}
): readonly DerivedNavigationItem[] {
  if (state.status !== 'ready') return EMPTY_NAVIGATION_ITEMS_V2;

  const items = state.navigationArtifacts.flatMap((artifact) =>
    artifact.createTopNavigationItems(context, runtimeContext)
  );
  return Object.freeze(
    items.filter((item) => isWebNavigationPathActiveV2(item.path, state.activeRouteKeys))
  );
}

export function useWebTopNavigationItemsV2(
  context: TopNavigationContext,
  runtimeContext: NavigationRuntimeContext = {}
): readonly DerivedNavigationItem[] {
  const state = useWebNavigationAuthorityV2();
  const { conversationId, preferredWorkspaceId, projectId, tenantId } = runtimeContext;
  return useMemo(
    () =>
      selectWebTopNavigationItemsV2(state, context, {
        conversationId,
        preferredWorkspaceId,
        projectId,
        tenantId,
      }),
    [context, conversationId, preferredWorkspaceId, projectId, state, tenantId]
  );
}

export function isWebNavigationPathActiveV2(
  path: string,
  activeRouteKeys: readonly string[]
): boolean {
  const pathname = path.split(/[?#]/, 1)[0] || '/';
  return activeRouteKeys.some((routeKey) => {
    const routePattern = routePatternFromKeyV2(routeKey);
    return (
      routePattern !== undefined &&
      matchPath({ caseSensitive: true, end: true, path: routePattern }, pathname) !== null
    );
  });
}

function routePatternFromKeyV2(routeKey: string): string | undefined {
  if (!routeKey.startsWith('route:')) return undefined;
  return routeKey.slice('route:'.length).replace(/#index$/, '');
}
