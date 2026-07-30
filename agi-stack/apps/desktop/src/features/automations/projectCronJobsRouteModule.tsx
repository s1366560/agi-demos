import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { DesktopCapabilityView } from '../runtime/capabilitySnapshot';
import type { DesktopAutomationApi } from './automationClient';

const PROJECT_CRON_JOBS_ROUTE_ID = 'project-project-cron-jobs' as const;
const PROJECT_CRON_JOBS_LOCAL_POLICY = 'native_equivalent' as const;
const CONTEXT_UNAVAILABLE_REASON =
  'project_cron_jobs_route_context_unavailable';
const BINDING_SCOPE_MISMATCH_REASON =
  'project_cron_jobs_route_binding_scope_mismatch';
const noop = (): void => {};

export type ProjectCronJobsRouteContext = Readonly<
  DesktopRouteContext & {
    tenantId: string;
    projectId: string;
  }
>;

export type ProjectCronJobsRouteScope = Readonly<{
  tenantId: string;
  projectId: string;
}>;

export type ProjectCronJobsRouteBinding = Readonly<{
  api: DesktopAutomationApi;
  scope: ProjectCronJobsRouteScope;
  projectName: string | null;
  runCapability: DesktopCapabilityView;
  onOpenProjectSettings: () => void;
  onOpenConnection: () => void;
}>;

export type ProjectCronJobsRouteModuleOptions = Readonly<{
  createBinding: (
    context: ProjectCronJobsRouteContext,
  ) => ProjectCronJobsRouteBinding;
}>;

type AutomationsPageComponent =
  typeof import('./AutomationsPage').AutomationsPage;

export function createProjectCronJobsRouteModuleLoader({
  createBinding,
}: ProjectCronJobsRouteModuleOptions): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('project_cron_jobs_route_binding_factory_invalid');
  }

  return async () => {
    const { AutomationsPage } = await import('./AutomationsPage');

    function ProjectCronJobsRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeProjectCronJobsContext(context);
      if (!routeContext) {
        return (
          <UnavailableProjectCronJobs
            context={context}
            AutomationsPage={AutomationsPage}
            reasonCode={CONTEXT_UNAVAILABLE_REASON}
          />
        );
      }
      return (
        <BoundProjectCronJobsRoute
          context={routeContext}
          createBinding={createBinding}
          AutomationsPage={AutomationsPage}
        />
      );
    }

    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: PROJECT_CRON_JOBS_ROUTE_ID,
      capability: PROJECT_CRON_JOBS_ROUTE_ID,
      localPolicy: PROJECT_CRON_JOBS_LOCAL_POLICY,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: ProjectCronJobsRouteSurface,
    });
    return module;
  };
}

function BoundProjectCronJobsRoute({
  context,
  createBinding,
  AutomationsPage,
}: Readonly<{
  context: ProjectCronJobsRouteContext;
  createBinding: ProjectCronJobsRouteModuleOptions['createBinding'];
  AutomationsPage: AutomationsPageComponent;
}>) {
  const binding = createBinding(context);
  if (!bindingScopeMatches(context, binding.scope)) {
    return (
      <UnavailableProjectCronJobs
        context={context}
        AutomationsPage={AutomationsPage}
        reasonCode={BINDING_SCOPE_MISMATCH_REASON}
      />
    );
  }
  return (
    <AutomationsPage
      key={`${context.tenantId}:${context.projectId}`}
      api={binding.api}
      projectId={context.projectId}
      projectName={binding.projectName}
      runCapability={binding.runCapability}
      onOpenProjectSettings={binding.onOpenProjectSettings}
      onOpenConnection={binding.onOpenConnection}
    />
  );
}

function UnavailableProjectCronJobs({
  context,
  AutomationsPage,
  reasonCode,
}: Readonly<{
  context: DesktopRouteContext;
  AutomationsPage: AutomationsPageComponent;
  reasonCode: string;
}>) {
  return (
    <div
      className="project-cron-jobs-route-unavailable"
      data-reason-code={reasonCode}
    >
      <AutomationsPage
        api={UNAVAILABLE_AUTOMATION_API}
        projectId=""
        projectName={null}
        runCapability={unavailableCapability(reasonCode)}
        onOpenProjectSettings={noop}
        onOpenConnection={noop}
      />
    </div>
  );
}

const UNAVAILABLE_AUTOMATION_API: DesktopAutomationApi = Object.freeze({
  async createAutomation() {
    throw unavailableAuthorityError();
  },
  async deleteAutomation() {
    throw unavailableAuthorityError();
  },
  async getAutomationCapabilities() {
    throw unavailableAuthorityError();
  },
  async listAutomations() {
    throw unavailableAuthorityError();
  },
  async listAutomationRuns() {
    throw unavailableAuthorityError();
  },
  async runAutomation() {
    throw unavailableAuthorityError();
  },
  async toggleAutomation() {
    throw unavailableAuthorityError();
  },
  async updateAutomation() {
    throw unavailableAuthorityError();
  },
});

function unavailableAuthorityError(): Error {
  return new Error('project_cron_jobs_route_authority_unavailable');
}

function normalizeProjectCronJobsContext(
  context: DesktopRouteContext,
): ProjectCronJobsRouteContext | null {
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
  context: ProjectCronJobsRouteContext,
  scope: ProjectCronJobsRouteScope,
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
