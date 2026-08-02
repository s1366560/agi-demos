import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DeviceApprovalPageProps } from './DeviceApprovalPage';

const ROUTE_ID = 'device-approval' as const;
const LOCAL_POLICY = 'cloud_only' as const;

export type DeviceApprovalRouteBinding = DeviceApprovalPageProps;

export function createDeviceApprovalRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding(): DeviceApprovalRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('device_approval_route_binding_factory_invalid');
  }
  return async () => {
    const { DeviceApprovalPage } = await import('./DeviceApprovalPage');

    function DeviceApprovalRouteSurface(_: DesktopRouteSurfaceProps) {
      const binding = useMemo(() => createBinding(), [createBinding]);
      return <DeviceApprovalPage {...binding} />;
    }

    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: ROUTE_ID,
      capability: ROUTE_ID,
      localPolicy: LOCAL_POLICY,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: DeviceApprovalRouteSurface,
    });
    return module;
  };
}
