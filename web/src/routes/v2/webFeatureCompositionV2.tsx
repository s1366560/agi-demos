import { Children, Fragment, cloneElement, isValidElement, type ReactNode } from 'react';

import {
  createRoutesFromElements,
  matchRoutes,
  type RouteObject,
  type RouteProps,
} from 'react-router-dom';

import { WebFeatureUnavailableV2 } from '../../components/plugins/WebFeatureUnavailableV2';
import { deriveTopNavigationItems } from '../../config/navigation';

import { createDefaultBusinessRouteElementsV2 } from './webDefaultBusinessRouteElementsV2';
import { registerCoreWebFeatureIdsV2 } from './webFeatureIdsV2';

import type { WebNavigationArtifactV2, WebRouteArtifactV2 } from './webRendererArtifactCatalogV2';

export const WEB_CORE_ROUTE_ARTIFACT_ID_V2 = 'web.routes.core.v1';

type FeatureRouteProps = Omit<RouteProps, 'handle'> & {
  readonly children?: ReactNode;
  readonly handle?: { readonly pluginFeature?: string };
};

// The feature assignment lives on each route declaration. These keys are protocol metadata,
// never inferred from a translated label, route parameter, or user input.
const businessRoutes = createDefaultBusinessRouteElementsV2();
const routeObjects = createRoutesFromElements(businessRoutes);
const navigationRouteObjects = routeObjects.map(toNavigationMatchRoute);

export const WEB_FEATURE_IDS_V2: readonly string[] = Object.freeze(
  [...new Set(featureRoutes(routeObjects).map(({ feature }) => feature))].sort()
);
registerCoreWebFeatureIdsV2(WEB_FEATURE_IDS_V2);

export function webFeatureRouteArtifactIdV2(feature: string): string {
  return `web.routes.${feature}.v1`;
}

export function webFeatureNavigationArtifactIdV2(feature: string): string {
  return `web.navigation.${feature}.v1`;
}

export function createWebFeatureArtifactsV2(): readonly (
  | WebRouteArtifactV2
  | WebNavigationArtifactV2
)[] {
  const ownedRoutes = featureRoutes(routeObjects);
  return Object.freeze([
    Object.freeze({
      id: WEB_CORE_ROUTE_ARTIFACT_ID_V2,
      kind: 'route' as const,
      featureId: 'core',
      routeKeys: Object.freeze(coreRouteKeys(routeObjects)),
      createRouteElements: () => selectRoutes(businessRoutes, new Set(), false),
    }),
    ...WEB_FEATURE_IDS_V2.flatMap((feature) => {
      const keys = ownedRoutes.filter((route) => route.feature === feature).map(({ key }) => key);
      return [
        Object.freeze({
          id: webFeatureRouteArtifactIdV2(feature),
          kind: 'route' as const,
          featureId: feature,
          routeKeys: Object.freeze(keys),
          createRouteElements: () => selectRoutes(businessRoutes, new Set([feature]), false),
        }),
        Object.freeze({
          id: webFeatureNavigationArtifactIdV2(feature),
          kind: 'navigation' as const,
          featureId: feature,
          createTopNavigationItems: (...args: Parameters<typeof deriveTopNavigationItems>) =>
            deriveTopNavigationItems(...args).filter((item) => {
              // Use the router's ranked match. A legacy conversation parameter also
              // structurally matches /plugins; it must not claim that fixed feature URL.
              const matches = matchRoutes(navigationRouteObjects, item.path);
              return (
                matches?.reduce<string | undefined>(
                  (owner, match) => featureOwner(match.route.handle, owner),
                  undefined
                ) === feature
              );
            }),
        }),
      ];
    }),
  ]);
}

/** Compose one guard/layout tree so changing an unrelated feature preserves mounted pages. */
export function composeWebRouteArtifactsV2(artifacts: readonly WebRouteArtifactV2[]): ReactNode {
  if (artifacts.some(({ id }) => id === 'web.routes.default-business.v1')) {
    return businessRoutes;
  }
  if (!artifacts.some(({ id }) => id === WEB_CORE_ROUTE_ARTIFACT_ID_V2)) return null;
  const active = new Set(artifacts.flatMap(({ featureId }) => (featureId ? [featureId] : [])));
  return selectRoutes(businessRoutes, active, true);
}

function selectRoutes(
  nodes: ReactNode,
  active: ReadonlySet<string>,
  showUnavailable: boolean
): ReactNode {
  return Children.map(nodes, (node) => {
    if (!isValidElement<FeatureRouteProps>(node)) return node;
    if (node.type === Fragment) {
      return cloneElement(
        node,
        undefined,
        selectRoutes(node.props.children, active, showUnavailable)
      );
    }
    const { handle, children, path, index } = node.props;
    const feature = handle?.pluginFeature;
    const key = node.key ?? `${path ?? 'index'}:${index ? 'index' : 'path'}`;
    if (feature && !active.has(feature)) {
      if (!showUnavailable) return null;
      return cloneElement(
        node,
        {
          key,
          element: <WebFeatureUnavailableV2 />,
        },
        children
      );
    }
    return cloneElement(node, { key }, selectRoutes(children, active, showUnavailable));
  });
}

function pathAt(parent: string, path?: string): string {
  if (path === undefined) return parent;
  const combined = path.startsWith('/') ? path : `${parent}/${path}`;
  return combined.replace(/\/{2,}/g, '/').replace(/\/$/, '') || '/';
}

function featureRoutes(
  routes: readonly RouteObject[],
  parent = '/',
  inherited?: string
): Array<{ feature: string; key: string }> {
  return routes.flatMap((route) => {
    const path = pathAt(parent, route.path);
    const feature: string | undefined = featureOwner(route.handle, inherited);
    const own =
      feature && (route.index || route.path !== undefined)
        ? [{ feature, key: `route:${path}${route.index ? '#index' : ''}` }]
        : [];
    return [...own, ...featureRoutes(route.children ?? [], path, feature)];
  });
}

function coreRouteKeys(routes: readonly RouteObject[], parent = '/', inherited?: string): string[] {
  return routes.flatMap((route) => {
    const path = pathAt(parent, route.path);
    const feature: string | undefined = featureOwner(route.handle, inherited);
    const own =
      !feature && (route.index || route.path !== undefined)
        ? [`route:${path}${route.index ? '#index' : ''}`]
        : [];
    return [...own, ...coreRouteKeys(route.children ?? [], path, feature)];
  });
}

function featureOwner(handle: unknown, inherited?: string): string | undefined {
  if (typeof handle !== 'object' || handle === null) return inherited;
  const value = (handle as { readonly pluginFeature?: unknown }).pluginFeature;
  return typeof value === 'string' ? value : inherited;
}

function toNavigationMatchRoute(route: RouteObject): Parameters<typeof matchRoutes>[0][number] {
  const base = {
    ...(route.path === undefined ? {} : { path: route.path }),
    ...(route.caseSensitive === undefined ? {} : { caseSensitive: route.caseSensitive }),
    handle: route.handle as unknown,
  };
  return route.index
    ? { ...base, index: true }
    : { ...base, children: (route.children ?? []).map(toNavigationMatchRoute) };
}
