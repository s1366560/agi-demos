import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { EvolutionRouteScope } from './evolutionRouteClient';
import type { EvolutionRouteController } from './evolutionRouteController';
import {
  buildEvolutionRoutePresentation,
  EVOLUTION_ROUTE_ID,
} from './evolutionRoutePresentationModel';
import { createNativeSettingsRouteModuleLoader } from './nativeSettingsRouteModule';

export type EvolutionRouteContext = Readonly<DesktopRouteContext & { tenantId: string }>;
export type EvolutionRouteBinding = Readonly<{
  controller: EvolutionRouteController;
  scope: EvolutionRouteScope;
}>;

export function createEvolutionRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: EvolutionRouteContext) => EvolutionRouteBinding;
}>): DesktopRouteModuleLoader {
  return createNativeSettingsRouteModuleLoader({
    routeId: EVOLUTION_ROUTE_ID,
    localPolicy: 'native_equivalent',
    createBinding,
    normalizeContext: tenantContext,
    fallbackScope: (context) => ({
      authority: 'cloud',
      tenantId: exactIdentifier(context.tenantId) ?? 'unavailable',
    }),
    scopeMatches: (context, scope) => context.tenantId === scope.tenantId,
    contextKey: (context) => context.tenantId,
    unavailableModel: (scope, reasonCode) =>
      buildEvolutionRoutePresentation({
        kind: 'failure',
        scope,
        state: 'unavailable',
        reasonCode,
        retryable: false,
      }),
    loadContent: async () => (await import('./EvolutionRoutePage')).EvolutionRoutePage,
  });
}

function tenantContext(context: DesktopRouteContext): EvolutionRouteContext | null {
  const tenantId = exactIdentifier(context.tenantId);
  return tenantId ? Object.freeze({ ...context, tenantId }) : null;
}

function exactIdentifier(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 && value === value.trim() ? value : null;
}
