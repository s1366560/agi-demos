import { useMemo } from 'react';

import {
  WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  type RendererContributionRegistryV2,
} from '@agistack/plugin-runtime';

import { useCurrentWebPluginGenerationV2 } from '../../plugins/WebPluginGenerationHostV2';

import {
  isWebNavigationPathActiveV2,
  useWebTopNavigationItemsV2,
} from './webNavigationAuthorityStateV2';
import { resolveWebRendererArtifactsV2 } from './webRendererArtifactCatalogV2';
import { useWebRouteAuthorityV2 } from './webRouteAuthorityStateV2';

import type { NavigationRuntimeContext, TopNavigationContext } from '../../config/navigation';

/** Only declared feature identities participate; labels and route text are never classifiers. */
export function useWebFeatureEnabledV2(
  featureId: string,
  contributionKind?: 'command' | 'settings-page'
): boolean {
  const routeAuthority = useWebRouteAuthorityV2();
  const generation = useCurrentWebPluginGenerationV2();
  return useMemo(() => {
    if (routeAuthority.status !== 'ready') return false;
    if (routeAuthority.routeArtifactIds.includes('web.routes.default-business.v1')) return true;
    if (!routeAuthority.routeArtifacts.some((artifact) => artifact.featureId === featureId))
      return false;
    if (!contributionKind) return true;
    if (!generation || generation.retired || generation.disposed) return false;
    const registry = generation.resolve<RendererContributionRegistryV2>(
      WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
      { kind: 'root' }
    );
    return resolveWebRendererArtifactsV2(registry.list()).some(
      (artifact) => artifact.kind === contributionKind && artifact.featureId === featureId
    );
  }, [contributionKind, featureId, generation, routeAuthority]);
}

export function useWebCommandNavigationItemsV2(
  context: TopNavigationContext,
  runtime: NavigationRuntimeContext
) {
  const navigation = useWebTopNavigationItemsV2(context, runtime);
  const routes = useWebRouteAuthorityV2();
  const generation = useCurrentWebPluginGenerationV2();
  return useMemo(() => {
    if (routes.routeArtifactIds.includes('web.routes.default-business.v1')) return navigation;
    if (!generation || generation.retired || generation.disposed) return [];
    const registry = generation.resolve<RendererContributionRegistryV2>(
      WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
      { kind: 'root' }
    );
    const features = new Set(
      resolveWebRendererArtifactsV2(registry.list()).flatMap((artifact) =>
        artifact.kind === 'command' ? [artifact.featureId] : []
      )
    );
    const allowed = new Set(
      routes.routeArtifacts
        .filter((artifact) => artifact.featureId && features.has(artifact.featureId))
        .flatMap((artifact) => artifact.routeKeys)
    );
    return navigation.filter((item) => isWebNavigationPathActiveV2(item.path, [...allowed]));
  }, [generation, navigation, routes]);
}
