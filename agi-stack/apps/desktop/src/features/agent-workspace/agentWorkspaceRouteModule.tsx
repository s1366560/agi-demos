import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';

export const AGENT_WORKSPACE_ROUTE_ID =
  'agent-workspace-tenant-agent-workspace' as const;

const LOCAL_POLICY = 'native_equivalent' as const;

export function createAgentWorkspaceRouteModuleLoader(): DesktopRouteModuleLoader {
  return async () => {
    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: AGENT_WORKSPACE_ROUTE_ID,
      capability: AGENT_WORKSPACE_ROUTE_ID,
      localPolicy: LOCAL_POLICY,
      contentPolicy: 'route_content',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: AgentWorkspaceRouteSurface,
    });
    return module;
  };
}

function AgentWorkspaceRouteSurface({
  content,
  context,
}: DesktopRouteSurfaceProps) {
  return (
    <section
      data-agent-workspace-route-surface="true"
      data-tenant-id={context.tenantId ?? ''}
    >
      {content}
    </section>
  );
}
