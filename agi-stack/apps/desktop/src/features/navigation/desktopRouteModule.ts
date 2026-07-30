import type { ComponentType } from 'react';

import type { CanonicalDesktopRouteId } from './desktopCanonicalRouteCatalog';
import type { DesktopRouteLocalPolicy } from './desktopRouteRegistry';

export type DesktopPlannedRouteReasonCode =
  | 'desktop_native_route_planned'
  | 'desktop_native_route_cloud_only_planned'
  | 'desktop_native_route_web_contract_blocked';

type DesktopRouteModuleBase = Readonly<{
  routeId: CanonicalDesktopRouteId;
  capability: string;
  localPolicy: DesktopRouteLocalPolicy;
  Surface: ComponentType<DesktopRouteSurfaceProps>;
}>;

export type DesktopImplementedRouteModule = DesktopRouteModuleBase &
  Readonly<{
    disposition: 'implemented';
    availability: 'available';
    reasonCode: null;
  }>;

export type DesktopUnavailableRouteModule = DesktopRouteModuleBase &
  Readonly<{
    disposition: 'planned';
    availability: 'unavailable';
    reasonCode: DesktopPlannedRouteReasonCode;
  }>;

export type DesktopRouteModule =
  | DesktopImplementedRouteModule
  | DesktopUnavailableRouteModule;

export type DesktopRouteSurfaceProps = Readonly<{
  module: DesktopRouteModule;
}>;

export type DesktopRouteModuleLoader = () => Promise<DesktopRouteModule>;
