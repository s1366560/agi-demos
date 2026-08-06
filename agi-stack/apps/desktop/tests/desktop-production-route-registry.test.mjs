import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledNavigationDirectory =
  '/tmp/agistack-desktop-test-dist/src/features/navigation';
mkdirSync(compiledNavigationDirectory, { recursive: true });
writeFileSync(`${compiledNavigationDirectory}/NativeUnavailableRoute.css`, '');
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  AGENT_WORKSPACE_ROUTE_ID,
  createAgentWorkspaceRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/agent-workspace/agentWorkspaceRouteModule.js');
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
  DESKTOP_PRODUCTION_ROUTE_IDS,
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
  TENANT_CREATION_ROUTE_ID,
  PROJECT_BLACKBOARD_ROUTE_ID,
  PROJECT_CRON_JOBS_ROUTE_ID,
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_SEARCH_ROUTE_ID,
  PROJECT_SUPPORT_ROUTE_ID,
  PROJECT_WORKSPACES_ROUTE_ID,
  TENANT_ANALYTICS_ROUTE_ID,
  TENANT_AGENT_DASHBOARD_ROUTE_ID,
  TENANT_AGENT_BINDINGS_ROUTE_ID,
  TENANT_AGENT_DEFINITIONS_ROUTE_ID,
  TENANT_OVERVIEW_ROUTE_ID,
  TENANT_DEAD_LETTER_QUEUE_ROUTE_ID,
  TENANT_CLUSTERS_ROUTE_ID,
  TENANT_DEPLOY_ROUTE_ID,
  TENANT_INSTANCE_TEMPLATES_ROUTE_ID,
  TENANT_INSTANCES_ROUTE_ID,
  TENANT_POOL_ROUTE_ID,
  TENANT_PROVIDERS_ROUTE_ID,
  TENANT_PLUGINS_ROUTE_ID,
  TENANT_PROJECTS_ROUTE_ID,
  TENANT_RUNTIMES_ROUTE_ID,
  TENANT_SKILLS_ROUTE_ID,
  TENANT_TASKS_ROUTE_ID,
  TENANT_WORKSPACES_ROUTE_ID,
  TENANT_MCP_SERVERS_ROUTE_ID,
  createDesktopProductionRouteRegistry,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');
const {
  NativeUnavailableRoute,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/NativeUnavailableRoute.js');
const {
  evaluateDesktopRouteAccess,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js');

const sourceRoot = new URL('../src/features/navigation/', import.meta.url);
const registrySource = readFileSync(
  new URL('desktopProductionRouteRegistry.ts', sourceRoot),
  'utf8',
);
const surfaceSource = readFileSync(
  new URL('NativeUnavailableRoute.tsx', sourceRoot),
  'utf8',
);
const stylesheet = readFileSync(
  new URL('NativeUnavailableRoute.css', sourceRoot),
  'utf8',
);
const messagesSource = readFileSync(
  new URL('locales/nativeUnavailableRouteMessages.ts', sourceRoot),
  'utf8',
);
const i18nSource = readFileSync(
  new URL('../src/i18n.tsx', import.meta.url),
  'utf8',
);
const globalStylesheet = readFileSync(
  new URL('../src/styles.css', import.meta.url),
  'utf8',
);
const productionRoutePolicies = new Map(
  createDesktopProductionRouteRegistry({ implementedLoaders: {} }).definitions.map(
    (definition) => [definition.id, definition.localPolicy],
  ),
);

function implementedProjectModule(overrides = {}) {
  function ProjectOverviewRoute() {
    return React.createElement('section', null, 'Project Overview route');
  }
  return Object.freeze({
    routeId: PROJECT_OVERVIEW_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: PROJECT_OVERVIEW_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: ProjectOverviewRoute,
    ...overrides,
  });
}

function implementedCatalogModule(routeId, overrides = {}) {
  function CatalogRoute() {
    return React.createElement('section', null, `${routeId} route`);
  }
  return Object.freeze({
    routeId,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: routeId,
    localPolicy: productionRoutePolicies.get(routeId),
    Surface: CatalogRoute,
    ...overrides,
  });
}

function implementedSearchModule(overrides = {}) {
  function ProjectSearchRoute() {
    return React.createElement('section', null, 'Project Search route');
  }
  return Object.freeze({
    routeId: PROJECT_SEARCH_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: PROJECT_SEARCH_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: ProjectSearchRoute,
    ...overrides,
  });
}

function implementedCronJobsModule(overrides = {}) {
  function ProjectCronJobsRoute() {
    return React.createElement('section', null, 'Project Cron Jobs route');
  }
  return Object.freeze({
    routeId: PROJECT_CRON_JOBS_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: PROJECT_CRON_JOBS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: ProjectCronJobsRoute,
    ...overrides,
  });
}

function implementedProjectSupportModule(overrides = {}) {
  function ProjectSupportRoute() {
    return React.createElement('section', null, 'Project Support route');
  }
  return Object.freeze({
    routeId: PROJECT_SUPPORT_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: PROJECT_SUPPORT_ROUTE_ID,
    localPolicy: 'cloud_only',
    Surface: ProjectSupportRoute,
    ...overrides,
  });
}

function implementedTenantModule(overrides = {}) {
  function TenantOverviewRoute() {
    return React.createElement('section', null, 'Tenant Overview route');
  }
  return Object.freeze({
    routeId: TENANT_OVERVIEW_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_OVERVIEW_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantOverviewRoute,
    ...overrides,
  });
}

function implementedTenantProjectsModule(overrides = {}) {
  function TenantProjectsRoute() {
    return React.createElement('section', null, 'Tenant Projects route');
  }
  return Object.freeze({
    routeId: TENANT_PROJECTS_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_PROJECTS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantProjectsRoute,
    ...overrides,
  });
}

function implementedTenantWorkspacesModule(overrides = {}) {
  function TenantWorkspacesRoute() {
    return React.createElement('section', null, 'Tenant Workspaces route');
  }
  return Object.freeze({
    routeId: TENANT_WORKSPACES_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_WORKSPACES_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantWorkspacesRoute,
    ...overrides,
  });
}

function implementedTenantTasksModule(overrides = {}) {
  function TenantTasksRoute() {
    return React.createElement('section', null, 'Tenant Tasks route');
  }
  return Object.freeze({
    routeId: TENANT_TASKS_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_TASKS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantTasksRoute,
    ...overrides,
  });
}

function implementedTenantAnalyticsModule(overrides = {}) {
  function TenantAnalyticsRoute() {
    return React.createElement('section', null, 'Tenant Analytics route');
  }
  return Object.freeze({
    routeId: TENANT_ANALYTICS_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_ANALYTICS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantAnalyticsRoute,
    ...overrides,
  });
}

function implementedTenantAgentBindingsModule(overrides = {}) {
  function TenantAgentBindingsRoute() {
    return React.createElement('section', null, 'Tenant Agent Bindings route');
  }
  return Object.freeze({
    routeId: TENANT_AGENT_BINDINGS_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_AGENT_BINDINGS_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantAgentBindingsRoute,
    ...overrides,
  });
}

function implementedTenantAgentDashboardModule(overrides = {}) {
  function TenantAgentDashboardRoute() {
    return React.createElement('section', null, 'Tenant Agent Dashboard route');
  }
  return Object.freeze({
    routeId: TENANT_AGENT_DASHBOARD_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_AGENT_DASHBOARD_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: TenantAgentDashboardRoute,
    ...overrides,
  });
}

function implementedDeadLetterQueueModule(overrides = {}) {
  function DeadLetterQueueRoute() {
    return React.createElement('section', null, 'Dead Letter Queue route');
  }
  return Object.freeze({
    routeId: TENANT_DEAD_LETTER_QUEUE_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_DEAD_LETTER_QUEUE_ROUTE_ID,
    localPolicy: 'cloud_only',
    Surface: DeadLetterQueueRoute,
    ...overrides,
  });
}

function implementedRuntimePoolModule(overrides = {}) {
  function RuntimePoolRoute() {
    return React.createElement('section', null, 'Runtime Pool route');
  }
  return Object.freeze({
    routeId: TENANT_POOL_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_POOL_ROUTE_ID,
    localPolicy: 'cloud_only',
    Surface: RuntimePoolRoute,
    ...overrides,
  });
}

function implementedRuntimeInstancesModule(overrides = {}) {
  function RuntimeInstancesRoute() {
    return React.createElement('section', null, 'Runtime Instances route');
  }
  return Object.freeze({
    routeId: TENANT_INSTANCES_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_INSTANCES_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: RuntimeInstancesRoute,
    ...overrides,
  });
}

function implementedRuntimeClustersModule(overrides = {}) {
  function RuntimeClustersRoute() {
    return React.createElement('section', null, 'Runtime Clusters route');
  }
  return Object.freeze({
    routeId: TENANT_CLUSTERS_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_CLUSTERS_ROUTE_ID,
    localPolicy: 'cloud_only',
    Surface: RuntimeClustersRoute,
    ...overrides,
  });
}

function implementedRuntimeDeploymentsModule(overrides = {}) {
  function RuntimeDeploymentsRoute() {
    return React.createElement('section', null, 'Runtime Deployments route');
  }
  return Object.freeze({
    routeId: TENANT_DEPLOY_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_DEPLOY_ROUTE_ID,
    localPolicy: 'cloud_only',
    Surface: RuntimeDeploymentsRoute,
    ...overrides,
  });
}

function implementedInstanceTemplatesModule(overrides = {}) {
  function InstanceTemplatesRoute() {
    return React.createElement('section', null, 'Instance Templates route');
  }
  return Object.freeze({
    routeId: TENANT_INSTANCE_TEMPLATES_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_INSTANCE_TEMPLATES_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: InstanceTemplatesRoute,
    ...overrides,
  });
}

function implementedUnifiedRuntimesModule(overrides = {}) {
  function UnifiedRuntimesRoute() {
    return React.createElement('section', null, 'Unified Runtimes route');
  }
  return Object.freeze({
    routeId: TENANT_RUNTIMES_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_RUNTIMES_ROUTE_ID,
    localPolicy: 'native_equivalent',
    Surface: UnifiedRuntimesRoute,
    ...overrides,
  });
}

function implementedDeviceApprovalModule(overrides = {}) {
  function DeviceApprovalRoute() {
    return React.createElement('section', null, 'Device Approval route');
  }
  return Object.freeze({
    routeId: DEVICE_APPROVAL_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: DEVICE_APPROVAL_ROUTE_ID,
    localPolicy: 'cloud_only',
    Surface: DeviceApprovalRoute,
    ...overrides,
  });
}

function implementedTenantCreationModule(overrides = {}) {
  function TenantCreationRoute() {
    return React.createElement('section', null, 'Tenant Creation route');
  }
  return Object.freeze({
    routeId: TENANT_CREATION_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: TENANT_CREATION_ROUTE_ID,
    localPolicy: 'cloud_only',
    Surface: TenantCreationRoute,
    ...overrides,
  });
}

function implementedInvitationAcceptanceModule(overrides = {}) {
  function InvitationAcceptanceRoute() {
    return React.createElement('section', null, 'Invitation Acceptance route');
  }
  return Object.freeze({
    routeId: INVITATION_ACCEPTANCE_ROUTE_ID,
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    capability: INVITATION_ACCEPTANCE_ROUTE_ID,
    localPolicy: 'cloud_only',
    Surface: InvitationAcceptanceRoute,
    ...overrides,
  });
}

function createRegistry(
  projectLoader = async () => implementedProjectModule(),
  searchLoader = async () => implementedSearchModule(),
  cronJobsLoader = async () => implementedCronJobsModule(),
  tenantLoader = async () => implementedTenantModule(),
  tenantProjectsLoader = async () => implementedTenantProjectsModule(),
  tenantWorkspacesLoader = async () => implementedTenantWorkspacesModule(),
  tenantTasksLoader = async () => implementedTenantTasksModule(),
  tenantAnalyticsLoader = async () => implementedTenantAnalyticsModule(),
  tenantAgentBindingsLoader = async () =>
    implementedTenantAgentBindingsModule(),
  deadLetterQueueLoader = async () => implementedDeadLetterQueueModule(),
  runtimePoolLoader = async () => implementedRuntimePoolModule(),
  unifiedRuntimesLoader = async () => implementedUnifiedRuntimesModule(),
  runtimeInstancesLoader = async () => implementedRuntimeInstancesModule(),
  runtimeClustersLoader = async () => implementedRuntimeClustersModule(),
  runtimeDeploymentsLoader = async () => implementedRuntimeDeploymentsModule(),
  instanceTemplatesLoader = async () => implementedInstanceTemplatesModule(),
  deviceApprovalLoader = async () => implementedDeviceApprovalModule(),
  tenantCreationLoader = async () => implementedTenantCreationModule(),
  invitationAcceptanceLoader = async () =>
    implementedInvitationAcceptanceModule(),
  projectSupportLoader = async () => implementedProjectSupportModule(),
  tenantAgentDashboardLoader = async () =>
    implementedTenantAgentDashboardModule(),
  agentWorkspaceLoader = createAgentWorkspaceRouteModuleLoader(),
) {
  return createDesktopProductionRouteRegistry({
    implementedLoaders: {
      ...Object.fromEntries(
        DESKTOP_IMPLEMENTED_ROUTE_IDS.map((routeId) => [
          routeId,
          async () => implementedCatalogModule(routeId),
        ]),
      ),
      [AGENT_WORKSPACE_ROUTE_ID]: agentWorkspaceLoader,
      [PROJECT_OVERVIEW_ROUTE_ID]: projectLoader,
      [PROJECT_SEARCH_ROUTE_ID]: searchLoader,
      [PROJECT_CRON_JOBS_ROUTE_ID]: cronJobsLoader,
      [PROJECT_SUPPORT_ROUTE_ID]: projectSupportLoader,
      [TENANT_OVERVIEW_ROUTE_ID]: tenantLoader,
      [TENANT_PROJECTS_ROUTE_ID]: tenantProjectsLoader,
      [TENANT_WORKSPACES_ROUTE_ID]: tenantWorkspacesLoader,
      [TENANT_TASKS_ROUTE_ID]: tenantTasksLoader,
      [TENANT_ANALYTICS_ROUTE_ID]: tenantAnalyticsLoader,
      [TENANT_AGENT_DASHBOARD_ROUTE_ID]: tenantAgentDashboardLoader,
      [TENANT_AGENT_BINDINGS_ROUTE_ID]: tenantAgentBindingsLoader,
      [TENANT_DEAD_LETTER_QUEUE_ROUTE_ID]: deadLetterQueueLoader,
      [TENANT_POOL_ROUTE_ID]: runtimePoolLoader,
      [TENANT_RUNTIMES_ROUTE_ID]: unifiedRuntimesLoader,
      [TENANT_INSTANCES_ROUTE_ID]: runtimeInstancesLoader,
      [TENANT_CLUSTERS_ROUTE_ID]: runtimeClustersLoader,
      [TENANT_DEPLOY_ROUTE_ID]: runtimeDeploymentsLoader,
      [TENANT_INSTANCE_TEMPLATES_ROUTE_ID]: instanceTemplatesLoader,
      [DEVICE_APPROVAL_ROUTE_ID]: deviceApprovalLoader,
      [TENANT_CREATION_ROUTE_ID]: tenantCreationLoader,
      [INVITATION_ACCEPTANCE_ROUTE_ID]: invitationAcceptanceLoader,
    },
  });
}

test('production registry downgrades absent App bindings and validates explicit loaders', () => {
  assert.equal(PROJECT_OVERVIEW_ROUTE_ID, 'project-project-overview');
  assert.equal(PROJECT_SEARCH_ROUTE_ID, 'project-project-search');
  assert.equal(PROJECT_CRON_JOBS_ROUTE_ID, 'project-project-cron-jobs');
  assert.equal(PROJECT_SUPPORT_ROUTE_ID, 'project-support');
  assert.equal(TENANT_OVERVIEW_ROUTE_ID, 'tenant-tenant-overview');
  assert.equal(TENANT_PROJECTS_ROUTE_ID, 'tenant-tenant-projects');
  assert.equal(TENANT_WORKSPACES_ROUTE_ID, 'tenant-tenant-workspaces');
  assert.equal(TENANT_TASKS_ROUTE_ID, 'tenant-tenant-tasks');
  assert.equal(TENANT_ANALYTICS_ROUTE_ID, 'tenant-tenant-analytics');
  assert.equal(
    TENANT_AGENT_DASHBOARD_ROUTE_ID,
    'tenant-tenant-agent-configuration',
  );
  assert.equal(TENANT_AGENT_BINDINGS_ROUTE_ID, 'tenant-tenant-agent-bindings');
  assert.equal(
    TENANT_DEAD_LETTER_QUEUE_ROUTE_ID,
    'tenant-tenant-dead-letter-queue',
  );
  assert.equal(TENANT_POOL_ROUTE_ID, 'tenant-tenant-pool');
  assert.equal(TENANT_RUNTIMES_ROUTE_ID, 'tenant-tenant-runtimes');
  assert.equal(TENANT_INSTANCES_ROUTE_ID, 'tenant-tenant-instances');
  assert.equal(TENANT_CLUSTERS_ROUTE_ID, 'tenant-tenant-clusters');
  assert.equal(TENANT_DEPLOY_ROUTE_ID, 'tenant-tenant-deploy');
  assert.equal(
    TENANT_INSTANCE_TEMPLATES_ROUTE_ID,
    'tenant-tenant-instance-templates',
  );
  assert.equal(DEVICE_APPROVAL_ROUTE_ID, 'device-approval');
  assert.equal(TENANT_CREATION_ROUTE_ID, 'tenant-creation');
  const missingBindingRegistry = createDesktopProductionRouteRegistry({
    implementedLoaders: {},
  });
  assert.deepEqual(
    missingBindingRegistry.byId.get(PROJECT_OVERVIEW_ROUTE_ID)
      ?.structuralReadiness,
    {
      status: 'unavailable',
      reasonCode: 'desktop_route_structural_app_binding_missing',
    },
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: 'not-callable',
          [PROJECT_SEARCH_ROUTE_ID]: async () => implementedSearchModule(),
          [PROJECT_CRON_JOBS_ROUTE_ID]: async () => implementedCronJobsModule(),
        },
      }),
    /desktop_production_route_loader_invalid:project-project-overview/u,
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: async () => implementedProjectModule(),
          [PROJECT_SEARCH_ROUTE_ID]: async () => implementedSearchModule(),
          [PROJECT_CRON_JOBS_ROUTE_ID]: async () => implementedCronJobsModule(),
          'external-web-handoff': async () => implementedProjectModule(),
        },
      }),
    /desktop_production_route_loader_unknown:external-web-handoff/u,
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: async () => implementedProjectModule(),
          [PROJECT_SEARCH_ROUTE_ID]: async () => implementedSearchModule(),
          [PROJECT_CRON_JOBS_ROUTE_ID]: async () => implementedCronJobsModule(),
          [TENANT_OVERVIEW_ROUTE_ID]: 'not-callable',
        },
      }),
    /desktop_production_route_loader_invalid:tenant-tenant-overview/u,
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: async () => implementedProjectModule(),
          [PROJECT_SEARCH_ROUTE_ID]: 'not-callable',
          [PROJECT_CRON_JOBS_ROUTE_ID]: async () => implementedCronJobsModule(),
        },
      }),
    /desktop_production_route_loader_invalid:project-project-search/u,
  );
  assert.throws(
    () =>
      createDesktopProductionRouteRegistry({
        implementedLoaders: {
          [PROJECT_OVERVIEW_ROUTE_ID]: async () => implementedProjectModule(),
          [PROJECT_SEARCH_ROUTE_ID]: async () => implementedSearchModule(),
          [PROJECT_CRON_JOBS_ROUTE_ID]: 'not-callable',
        },
      }),
    /desktop_production_route_loader_invalid:project-project-cron-jobs/u,
  );
});

test('all production loaders remain lazy and implemented routes follow the shared catalog', async () => {
  let projectLoadCount = 0;
  let searchLoadCount = 0;
  let cronJobsLoadCount = 0;
  let tenantLoadCount = 0;
  let tenantProjectsLoadCount = 0;
  let tenantWorkspacesLoadCount = 0;
  let tenantTasksLoadCount = 0;
  let tenantAnalyticsLoadCount = 0;
  let tenantAgentBindingsLoadCount = 0;
  let deadLetterQueueLoadCount = 0;
  let runtimePoolLoadCount = 0;
  let unifiedRuntimesLoadCount = 0;
  let runtimeInstancesLoadCount = 0;
  let runtimeClustersLoadCount = 0;
  let runtimeDeploymentsLoadCount = 0;
  let instanceTemplatesLoadCount = 0;
  let deviceApprovalLoadCount = 0;
  let tenantCreationLoadCount = 0;
  let invitationAcceptanceLoadCount = 0;
  let projectSupportLoadCount = 0;
  const projectModule = implementedProjectModule();
  const searchModule = implementedSearchModule();
  const cronJobsModule = implementedCronJobsModule();
  const tenantModule = implementedTenantModule();
  const tenantProjectsModule = implementedTenantProjectsModule();
  const tenantWorkspacesModule = implementedTenantWorkspacesModule();
  const tenantTasksModule = implementedTenantTasksModule();
  const tenantAnalyticsModule = implementedTenantAnalyticsModule();
  const tenantAgentBindingsModule = implementedTenantAgentBindingsModule();
  const deadLetterQueueModule = implementedDeadLetterQueueModule();
  const runtimePoolModule = implementedRuntimePoolModule();
  const unifiedRuntimesModule = implementedUnifiedRuntimesModule();
  const runtimeInstancesModule = implementedRuntimeInstancesModule();
  const runtimeClustersModule = implementedRuntimeClustersModule();
  const runtimeDeploymentsModule = implementedRuntimeDeploymentsModule();
  const instanceTemplatesModule = implementedInstanceTemplatesModule();
  const deviceApprovalModule = implementedDeviceApprovalModule();
  const tenantCreationModule = implementedTenantCreationModule();
  const invitationAcceptanceModule = implementedInvitationAcceptanceModule();
  const projectSupportModule = implementedProjectSupportModule();
  const registry = createRegistry(
    async () => {
      projectLoadCount += 1;
      return projectModule;
    },
    async () => {
      searchLoadCount += 1;
      return searchModule;
    },
    async () => {
      cronJobsLoadCount += 1;
      return cronJobsModule;
    },
    async () => {
      tenantLoadCount += 1;
      return tenantModule;
    },
    async () => {
      tenantProjectsLoadCount += 1;
      return tenantProjectsModule;
    },
    async () => {
      tenantWorkspacesLoadCount += 1;
      return tenantWorkspacesModule;
    },
    async () => {
      tenantTasksLoadCount += 1;
      return tenantTasksModule;
    },
    async () => {
      tenantAnalyticsLoadCount += 1;
      return tenantAnalyticsModule;
    },
    async () => {
      tenantAgentBindingsLoadCount += 1;
      return tenantAgentBindingsModule;
    },
    async () => {
      deadLetterQueueLoadCount += 1;
      return deadLetterQueueModule;
    },
    async () => {
      runtimePoolLoadCount += 1;
      return runtimePoolModule;
    },
    async () => {
      unifiedRuntimesLoadCount += 1;
      return unifiedRuntimesModule;
    },
    async () => {
      runtimeInstancesLoadCount += 1;
      return runtimeInstancesModule;
    },
    async () => {
      runtimeClustersLoadCount += 1;
      return runtimeClustersModule;
    },
    async () => {
      runtimeDeploymentsLoadCount += 1;
      return runtimeDeploymentsModule;
    },
    async () => {
      instanceTemplatesLoadCount += 1;
      return instanceTemplatesModule;
    },
    async () => {
      deviceApprovalLoadCount += 1;
      return deviceApprovalModule;
    },
    async () => {
      tenantCreationLoadCount += 1;
      return tenantCreationModule;
    },
    async () => {
      invitationAcceptanceLoadCount += 1;
      return invitationAcceptanceModule;
    },
    async () => {
      projectSupportLoadCount += 1;
      return projectSupportModule;
    },
  );

  assert.deepEqual(
    registry.definitions.map((definition) => definition.id),
    DESKTOP_PRODUCTION_ROUTE_IDS,
  );
  assert.equal(projectLoadCount, 0);
  assert.equal(searchLoadCount, 0);
  assert.equal(cronJobsLoadCount, 0);
  assert.equal(tenantLoadCount, 0);
  assert.equal(tenantProjectsLoadCount, 0);
  assert.equal(tenantWorkspacesLoadCount, 0);
  assert.equal(tenantTasksLoadCount, 0);
  assert.equal(tenantAnalyticsLoadCount, 0);
  assert.equal(tenantAgentBindingsLoadCount, 0);
  assert.equal(deadLetterQueueLoadCount, 0);
  assert.equal(runtimePoolLoadCount, 0);
  assert.equal(unifiedRuntimesLoadCount, 0);
  assert.equal(runtimeInstancesLoadCount, 0);
  assert.equal(runtimeClustersLoadCount, 0);
  assert.equal(runtimeDeploymentsLoadCount, 0);
  assert.equal(instanceTemplatesLoadCount, 0);
  assert.equal(deviceApprovalLoadCount, 0);
  assert.equal(tenantCreationLoadCount, 0);
  assert.equal(invitationAcceptanceLoadCount, 0);
  assert.equal(projectSupportLoadCount, 0);

  const loaded = await Promise.all(
    registry.definitions.map(async (definition) => ({
      definition,
      module: await definition.loader(),
    })),
  );
  assert.equal(projectLoadCount, 1);
  assert.equal(searchLoadCount, 1);
  assert.equal(cronJobsLoadCount, 1);
  assert.equal(tenantLoadCount, 1);
  assert.equal(tenantProjectsLoadCount, 1);
  assert.equal(tenantWorkspacesLoadCount, 1);
  assert.equal(tenantTasksLoadCount, 1);
  assert.equal(tenantAnalyticsLoadCount, 1);
  assert.equal(tenantAgentBindingsLoadCount, 1);
  assert.equal(deadLetterQueueLoadCount, 1);
  assert.equal(runtimePoolLoadCount, 1);
  assert.equal(unifiedRuntimesLoadCount, 1);
  assert.equal(runtimeInstancesLoadCount, 1);
  assert.equal(runtimeClustersLoadCount, 1);
  assert.equal(runtimeDeploymentsLoadCount, 1);
  assert.equal(instanceTemplatesLoadCount, 1);
  assert.equal(deviceApprovalLoadCount, 1);
  assert.equal(tenantCreationLoadCount, 1);
  assert.equal(invitationAcceptanceLoadCount, 1);
  assert.equal(projectSupportLoadCount, 1);

  const implemented = loaded.filter(
    ({ module }) => module.disposition === 'implemented',
  );
  const planned = loaded.filter(
    ({ module }) => module.disposition === 'planned',
  );
  assert.equal(implemented.length, DESKTOP_IMPLEMENTED_ROUTE_IDS.length);
  assert.deepEqual(
    implemented.map(({ definition }) => definition.id).sort(),
    [...DESKTOP_IMPLEMENTED_ROUTE_IDS].sort(),
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === PROJECT_OVERVIEW_ROUTE_ID,
    ).module,
    projectModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === PROJECT_SEARCH_ROUTE_ID,
    ).module,
    searchModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === PROJECT_CRON_JOBS_ROUTE_ID,
    ).module,
    cronJobsModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === PROJECT_SUPPORT_ROUTE_ID,
    ).module,
    projectSupportModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_OVERVIEW_ROUTE_ID,
    ).module,
    tenantModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_PROJECTS_ROUTE_ID,
    ).module,
    tenantProjectsModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_WORKSPACES_ROUTE_ID,
    ).module,
    tenantWorkspacesModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_TASKS_ROUTE_ID,
    ).module,
    tenantTasksModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_ANALYTICS_ROUTE_ID,
    ).module,
    tenantAnalyticsModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_AGENT_BINDINGS_ROUTE_ID,
    ).module,
    tenantAgentBindingsModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_DEAD_LETTER_QUEUE_ROUTE_ID,
    ).module,
    deadLetterQueueModule,
  );
  assert.equal(
    implemented.find(({ definition }) => definition.id === TENANT_POOL_ROUTE_ID)
      .module,
    runtimePoolModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_RUNTIMES_ROUTE_ID,
    ).module,
    unifiedRuntimesModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_INSTANCES_ROUTE_ID,
    ).module,
    runtimeInstancesModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_CLUSTERS_ROUTE_ID,
    ).module,
    runtimeClustersModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_DEPLOY_ROUTE_ID,
    ).module,
    runtimeDeploymentsModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_INSTANCE_TEMPLATES_ROUTE_ID,
    ).module,
    instanceTemplatesModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === DEVICE_APPROVAL_ROUTE_ID,
    ).module,
    deviceApprovalModule,
  );
  assert.equal(
    implemented.find(
      ({ definition }) => definition.id === TENANT_CREATION_ROUTE_ID,
    ).module,
    tenantCreationModule,
  );
  assert.equal(
    planned.length,
    registry.definitions.length - DESKTOP_IMPLEMENTED_ROUTE_IDS.length,
  );

  for (const { definition, module } of planned) {
    assert.equal(module.routeId, definition.id);
    assert.equal(module.capability, definition.capability);
    assert.equal(module.localPolicy, definition.localPolicy);
    assert.equal(module.availability, 'unavailable');
    assert.equal(module.Surface, NativeUnavailableRoute);
    assert.equal(module.reasonCode, plannedReason(definition.localPolicy));
    assert.notEqual(module.reasonCode, null);
  }
});

test('implemented loader results fail closed when the route module contract drifts', async () => {
  const cases = [
    {
      module: null,
      reason: 'desktop_route_module_invalid:project-project-overview',
    },
    {
      module: implementedProjectModule({ routeId: 'tenant-tenant-overview' }),
      reason: 'desktop_route_module_identity_mismatch:project-project-overview',
    },
    {
      module: implementedProjectModule({ disposition: 'planned' }),
      reason: 'desktop_route_module_invalid:project-project-overview',
    },
    {
      module: implementedProjectModule({ availability: 'unavailable' }),
      reason: 'desktop_route_module_invalid:project-project-overview',
    },
    {
      module: implementedProjectModule({
        capability: 'project-project-settings',
      }),
      reason: 'desktop_route_module_contract_mismatch:project-project-overview',
    },
    {
      module: implementedProjectModule({ localPolicy: 'cloud_only' }),
      reason: 'desktop_route_module_contract_mismatch:project-project-overview',
    },
    {
      module: implementedProjectModule({ Surface: 'ProjectOverviewPage' }),
      reason: 'desktop_route_module_invalid:project-project-overview',
    },
  ];

  for (const entry of cases) {
    const registry = createRegistry(async () => entry.module);
    await assert.rejects(
      registry.byId.get(PROJECT_OVERVIEW_ROUTE_ID).loader(),
      new RegExp(entry.reason),
    );
  }
});

test('Local cloud-only routes stay owned by the Host gate after Web blockers close', () => {
  const registry = createRegistry();
  const cloudOnly = registry.definitions.find(
    (definition) => definition.localPolicy === 'cloud_only',
  );
  assert.ok(cloudOnly);
  assert.equal(
    registry.definitions.some(
      (definition) => definition.localPolicy === 'blocked_by_web_contract',
    ),
    false,
  );

  const localAccess = (definition) =>
    evaluateDesktopRouteAccess({
      match: {
        definition,
        context: {
          tenantId: 'tenant-1',
          projectId: definition.scope.includes('project')
            ? 'project-1'
            : undefined,
        },
        canonicalPath: definition.path,
      },
      mode: 'local',
      permissions: new Set(definition.requiredPermission.flat()),
      capability: null,
    });

  assert.deepEqual(localAccess(cloudOnly), {
    status: 'unavailable',
    reasonCode: 'desktop_route_local_cloud_only',
    capability: null,
  });
});

test('generic unavailable surface renders structured route authority without a Web escape', async () => {
  const registry = createDesktopProductionRouteRegistry({ implementedLoaders: {} });
  const definition = registry.byId.get('tenant-tenant-evolution');
  assert.ok(definition);
  const module = await definition.loader();
  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, { module }),
    ),
  );

  assert.match(markup, /Native route planned/);
  assert.match(markup, /tenant-tenant-evolution/);
  assert.match(markup, /desktop_native_route_planned/);
  assert.match(markup, /native_equivalent/);
  assert.match(markup, /Unavailable/);
  assert.doesNotMatch(
    markup,
    /Complete|WebView|Open in browser|href=|<iframe|<webview/i,
  );
  assert.doesNotMatch(
    surfaceSource,
    /shell\.openExternal|window\.open|<iframe|<webview/i,
  );
  assert.doesNotMatch(
    registrySource,
    /https?:\/\/|window\.open|shell\.openExternal/,
  );
});

test('unavailable route UI uses bilingual domain i18n and declared Desktop tokens', () => {
  assert.match(surfaceSource, /useI18n\(\)/);
  assert.match(
    i18nSource,
    /nativeUnavailableRouteEnUS,[\s\S]*nativeUnavailableRouteZhCN/,
  );
  assert.match(i18nSource, /\.\.\.nativeUnavailableRouteEnUS/);
  assert.match(i18nSource, /\.\.\.nativeUnavailableRouteZhCN/);
  for (const key of [
    'nativeUnavailableRoute.title',
    'nativeUnavailableRoute.description',
    'nativeUnavailableRoute.routeId',
    'nativeUnavailableRoute.capability',
    'nativeUnavailableRoute.localPolicy',
    'nativeUnavailableRoute.reasonCode',
    'nativeUnavailableRoute.availability',
  ]) {
    assert.equal(messagesSource.split(`'${key}'`).length, 3);
  }

  assert.match(stylesheet, /var\(--desktop-surface-3\)/);
  assert.match(stylesheet, /@media \(max-width:/);
  assert.match(stylesheet, /:focus-visible/);
  const referencedTokens = new Set(
    [...stylesheet.matchAll(/var\((--desktop-[a-z0-9-]+)/g)].map(
      (match) => match[1],
    ),
  );
  for (const token of referencedTokens) {
    assert.match(globalStylesheet, new RegExp(`${token}\\s*:`));
  }
});

function plannedReason(localPolicy) {
  if (localPolicy === 'cloud_only') {
    return 'desktop_native_route_cloud_only_planned';
  }
  if (localPolicy === 'blocked_by_web_contract') {
    return 'desktop_native_route_web_contract_blocked';
  }
  return 'desktop_native_route_planned';
}
