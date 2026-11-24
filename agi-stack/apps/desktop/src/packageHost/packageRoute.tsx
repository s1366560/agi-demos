import type {
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from "../features/navigation/desktopRouteModule";

/** Keep the desktop navigation entry and resolve its page from the active signed release. */
export function packageRoute(
  routeId: string,
  segment: string,
  scope: "tenant" | "project",
): DesktopRouteModuleLoader {
  return async () => {
    const { InstalledRoutePage } = await import("./InstalledRoutePage");
    function Surface({ context }: DesktopRouteSurfaceProps) {
      const projectId = scope === "project" ? context.projectId : null;
      if (!context.tenantId || projectId === undefined) return null;
      return (
        <InstalledRoutePage
          key={JSON.stringify([context.tenantId, projectId, segment])}
          tenantId={context.tenantId}
          projectId={projectId}
          segment={segment}
        />
      );
    }
    return {
      routeId,
      capability: routeId,
      localPolicy: "cloud_only",
      disposition: "implemented",
      availability: "available",
      reasonCode: null,
      contentPolicy: "route_content",
      Surface,
    };
  };
}
