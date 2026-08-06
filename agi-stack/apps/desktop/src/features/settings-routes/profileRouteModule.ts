import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { ProfileRouteScope } from './profileRouteClient';
import type { ProfileRouteController } from './profileRouteController';
import { createNativeSettingsRouteModuleLoader } from './nativeSettingsRouteModule';
import { buildProfileRoutePresentation, PROFILE_ROUTE_ID } from './profileRoutePresentationModel';

export type ProfileRouteBinding = Readonly<{
  controller: ProfileRouteController;
  scope: ProfileRouteScope;
}>;

export function createProfileRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: DesktopRouteContext) => ProfileRouteBinding;
}>): DesktopRouteModuleLoader {
  return createNativeSettingsRouteModuleLoader({
    routeId: PROFILE_ROUTE_ID,
    localPolicy: 'native_equivalent',
    createBinding,
    normalizeContext: (context) => Object.freeze({ ...context }),
    fallbackScope: () => ({ authority: 'cloud' }),
    scopeMatches: () => true,
    contextKey: (context) =>
      [context.tenantId, context.projectId, context.workspaceId, context.instanceId].join('\u0000'),
    unavailableModel: (scope, reasonCode) =>
      buildProfileRoutePresentation({
        kind: 'failure',
        scope,
        state: 'unavailable',
        reasonCode,
        retryable: false,
      }),
    loadContent: async () => (await import('./ProfileRoutePage')).ProfileRoutePage,
  });
}
