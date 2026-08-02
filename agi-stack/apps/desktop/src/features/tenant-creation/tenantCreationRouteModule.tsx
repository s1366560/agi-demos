import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { TenantCreationPageProps } from './TenantCreationPage';

const ROUTE_ID = 'tenant-creation' as const;
const LOCAL_POLICY = 'cloud_only' as const;

export type TenantCreationRouteBinding = TenantCreationPageProps;

export function createTenantCreationRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding(): TenantCreationRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('tenant_creation_route_binding_factory_invalid');
  }
  return async () => {
    const { TenantCreationPage } = await import('./TenantCreationPage');

    function TenantCreationRouteSurface(_: DesktopRouteSurfaceProps) {
      const binding = useMemo(() => createBinding(), [createBinding]);
      return <TenantCreationPage {...binding} />;
    }

    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: ROUTE_ID,
      capability: ROUTE_ID,
      localPolicy: LOCAL_POLICY,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: TenantCreationRouteSurface,
    });
    return module;
  };
}
