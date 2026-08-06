import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { ChannelsRouteScope } from './channelsRouteClient';
import type { ChannelsRouteController } from './channelsRouteController';
import {
  buildChannelsRoutePresentation,
  CHANNELS_ROUTE_ID,
} from './channelsRoutePresentationModel';
import { createNativeSettingsRouteModuleLoader } from './nativeSettingsRouteModule';

export type ChannelsRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string; projectId: string }
>;
export type ChannelsRouteBinding = Readonly<{
  controller: ChannelsRouteController;
  scope: ChannelsRouteScope;
}>;

export function createChannelsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: ChannelsRouteContext) => ChannelsRouteBinding;
}>): DesktopRouteModuleLoader {
  return createNativeSettingsRouteModuleLoader({
    routeId: CHANNELS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    createBinding,
    normalizeContext: projectContext,
    fallbackScope: (context) => ({
      authority: 'cloud',
      tenantId: exactIdentifier(context.tenantId) ?? 'unavailable',
      projectId: exactIdentifier(context.projectId) ?? 'unavailable',
    }),
    scopeMatches: (context, scope) =>
      context.tenantId === scope.tenantId && context.projectId === scope.projectId,
    contextKey: (context) => `${context.tenantId}\u0000${context.projectId}`,
    unavailableModel: (scope, reasonCode) =>
      buildChannelsRoutePresentation({
        kind: 'failure',
        scope,
        state: 'unavailable',
        reasonCode,
        retryable: false,
      }),
    loadContent: async () => (await import('./ChannelsRoutePage')).ChannelsRoutePage,
  });
}

function projectContext(context: DesktopRouteContext): ChannelsRouteContext | null {
  const tenantId = exactIdentifier(context.tenantId);
  const projectId = exactIdentifier(context.projectId);
  return tenantId && projectId ? Object.freeze({ ...context, tenantId, projectId }) : null;
}

function exactIdentifier(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 && value === value.trim() ? value : null;
}
