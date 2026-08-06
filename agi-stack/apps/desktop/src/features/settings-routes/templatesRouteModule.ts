import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { TemplatesRouteScope } from './templatesRouteClient';
import type { TemplatesRouteController } from './templatesRouteController';
import { createNativeSettingsRouteModuleLoader } from './nativeSettingsRouteModule';
import {
  buildTemplatesRoutePresentation,
  TEMPLATES_ROUTE_ID,
} from './templatesRoutePresentationModel';

export type TemplatesRouteContext = Readonly<DesktopRouteContext & { tenantId: string }>;
export type TemplatesRouteBinding = Readonly<{
  controller: TemplatesRouteController;
  scope: TemplatesRouteScope;
}>;

export function createTemplatesRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TemplatesRouteContext) => TemplatesRouteBinding;
}>): DesktopRouteModuleLoader {
  return createNativeSettingsRouteModuleLoader({
    routeId: TEMPLATES_ROUTE_ID,
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
      buildTemplatesRoutePresentation({
        kind: 'failure',
        scope,
        state: 'unavailable',
        reasonCode,
        retryable: false,
      }),
    loadContent: async () => (await import('./TemplatesRoutePage')).TemplatesRoutePage,
  });
}

function tenantContext(context: DesktopRouteContext): TemplatesRouteContext | null {
  const tenantId = exactIdentifier(context.tenantId);
  return tenantId ? Object.freeze({ ...context, tenantId }) : null;
}

function exactIdentifier(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 && value === value.trim() ? value : null;
}
