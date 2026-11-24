import type {
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from "../features/navigation/desktopRouteModule";

/** Keep the desktop navigation entry and resolve its page from the active signed release. */
export function packageRoute(
  routeId: string,
  segment: string,
  scope: "tenant" | "project",
  native?: { isLocal(): boolean; load: DesktopRouteModuleLoader },
): DesktopRouteModuleLoader {
  return async () => {
    if (native?.isLocal()) return native.load();
    const { InstalledRoutePage } = await import("./InstalledRoutePage");
    function Surface({ context }: DesktopRouteSurfaceProps) {
      const projectId = scope === "project" ? context.projectId : null;
      if (!context.tenantId || projectId === undefined) return null;
      const workspace = context.workspaceId
        ? new URLSearchParams({ workspaceId: context.workspaceId })
        : null;
      const address = workspace ? segment + "?" + workspace.toString() : segment;
      return (
        <InstalledRoutePage
          key={JSON.stringify([context.tenantId, projectId, address])}
          tenantId={context.tenantId}
          projectId={projectId}
          segment={address}
        />
      );
    }
    return {
      routeId,
      capability: routeId,
      localPolicy: native ? "native_equivalent" : "cloud_only",
      disposition: "implemented",
      availability: "available",
      reasonCode: null,
      contentPolicy: "route_content",
      Surface,
    };
  };
}
