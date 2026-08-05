import type { ComponentType, ReactNode } from 'react';

import type {
  DesktopRouteContext,
  DesktopRouteLocalPolicy,
} from './desktopRouteRegistry';

export type DesktopPlannedRouteReasonCode =
  | 'desktop_native_route_planned'
  | 'desktop_native_route_cloud_only_planned'
  | 'desktop_native_route_web_contract_blocked';

type DesktopRouteModuleBase = Readonly<{
  routeId: string;
  capability: string;
  localPolicy: DesktopRouteLocalPolicy;
  contentPolicy?: 'route_content';
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
  context: DesktopRouteContext;
  content?: ReactNode;
}>;

export type DesktopRouteModuleLoader = () => Promise<DesktopRouteModule>;
