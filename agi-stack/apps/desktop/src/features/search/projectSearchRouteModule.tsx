import type { DesktopApiClient } from '../../api/client';
import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { DesktopCapabilityView } from '../runtime/capabilitySnapshot';

const PROJECT_SEARCH_ROUTE_ID = 'project-project-search' as const;
const PROJECT_SEARCH_LOCAL_POLICY = 'native_equivalent' as const;
const CONTEXT_UNAVAILABLE_REASON = 'project_search_route_context_unavailable';
const BINDING_SCOPE_MISMATCH_REASON =
  'project_search_route_binding_scope_mismatch';
const FALLBACK_SCOPE_VALUE = 'unavailable';

export type ProjectSearchRouteContext = Readonly<
  DesktopRouteContext & {
    tenantId: string;
    projectId: string;
  }
>;

export type ProjectSearchRouteScope = Readonly<{
  tenantId: string;
  projectId: string;
}>;

export type ProjectSearchRouteBinding = Readonly<{
  api: Pick<DesktopApiClient, 'searchProject'>;
  scope: ProjectSearchRouteScope;
  projectName: string | null;
  capability: DesktopCapabilityView;
  capabilityLoading: boolean;
  onRetryCapability?: () => void;
  onOpenProjectSettings?: () => void;
}>;

export type ProjectSearchRouteModuleOptions = Readonly<{
  createBinding: (
    context: ProjectSearchRouteContext,
  ) => ProjectSearchRouteBinding;
}>;

type DesktopSearchComponent =
  typeof import('./DesktopSearch').DesktopSearch;

export function createProjectSearchRouteModuleLoader({
  createBinding,
}: ProjectSearchRouteModuleOptions): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('project_search_route_binding_factory_invalid');
  }

  return async () => {
    const { DesktopSearch } = await import('./DesktopSearch');

    function ProjectSearchRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeProjectSearchContext(context);
      if (!routeContext) {
        return (
          <UnavailableProjectSearch
            context={context}
            DesktopSearch={DesktopSearch}
            reasonCode={CONTEXT_UNAVAILABLE_REASON}
          />
        );
      }

      const binding = createBinding(routeContext);
      if (!bindingScopeMatches(routeContext, binding.scope)) {
        return (
          <UnavailableProjectSearch
            context={routeContext}
            DesktopSearch={DesktopSearch}
            reasonCode={BINDING_SCOPE_MISMATCH_REASON}
          />
        );
      }

      return (
        <DesktopSearch
          api={binding.api}
          tenantId={routeContext.tenantId}
          projectId={routeContext.projectId}
          projectName={binding.projectName}
          capability={binding.capability}
          capabilityLoading={binding.capabilityLoading}
          onRetryCapability={binding.onRetryCapability}
          onOpenProjectSettings={binding.onOpenProjectSettings}
        />
      );
    }

    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: PROJECT_SEARCH_ROUTE_ID,
      capability: PROJECT_SEARCH_ROUTE_ID,
      localPolicy: PROJECT_SEARCH_LOCAL_POLICY,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: ProjectSearchRouteSurface,
    });
    return module;
  };
}

function UnavailableProjectSearch({
  context,
  DesktopSearch,
  reasonCode,
}: Readonly<{
  context: DesktopRouteContext;
  DesktopSearch: DesktopSearchComponent;
  reasonCode: string;
}>) {
  return (
    <DesktopSearch
      api={UNAVAILABLE_SEARCH_API}
      tenantId={
        nonEmptyContextValue(context.tenantId) ?? FALLBACK_SCOPE_VALUE
      }
      projectId={
        nonEmptyContextValue(context.projectId) ?? FALLBACK_SCOPE_VALUE
      }
      projectName={null}
      capability={unavailableCapability(reasonCode)}
      capabilityLoading={false}
    />
  );
}

const UNAVAILABLE_SEARCH_API: Pick<DesktopApiClient, 'searchProject'> =
  Object.freeze({
    async searchProject() {
      throw new Error('project_search_route_authority_unavailable');
    },
  });

function normalizeProjectSearchContext(
  context: DesktopRouteContext,
): ProjectSearchRouteContext | null {
  const tenantId = nonEmptyContextValue(context.tenantId);
  const projectId = nonEmptyContextValue(context.projectId);
  if (!tenantId || !projectId) return null;
  return Object.freeze({
    tenantId,
    projectId,
    ...(context.workspaceId === undefined
      ? {}
      : { workspaceId: context.workspaceId }),
    ...(context.instanceId === undefined
      ? {}
      : { instanceId: context.instanceId }),
  });
}

function bindingScopeMatches(
  context: ProjectSearchRouteContext,
  scope: ProjectSearchRouteScope,
): boolean {
  return (
    scope.tenantId === context.tenantId &&
    scope.projectId === context.projectId
  );
}

function unavailableCapability(reasonCode: string): DesktopCapabilityView {
  return Object.freeze({
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: Object.freeze([]),
    scope: Object.freeze({
      tenant_id: null,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: null,
    status: 'unavailable',
    available: false,
  });
}

function nonEmptyContextValue(value: string | undefined): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}
