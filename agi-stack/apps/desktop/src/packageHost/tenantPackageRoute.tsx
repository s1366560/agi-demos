import type {
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../features/navigation/desktopRouteModule';

/** Keep the desktop navigation entry and resolve its page from the active signed release. */
export function tenantPackageRoute(routeId: string, segment: string): DesktopRouteModuleLoader {
  return async () => {
    const { TenantPackagePage } = await import('./TenantPackagePage');
    function Surface({ context }: DesktopRouteSurfaceProps) {
      if (!context.tenantId) return null;
      return (
        <TenantPackagePage key={context.tenantId} tenantId={context.tenantId} segment={segment} />
      );
    }
    return {
      routeId,
      capability: routeId,
      localPolicy: 'cloud_only',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      contentPolicy: 'route_content',
      Surface,
    };
  };
}
