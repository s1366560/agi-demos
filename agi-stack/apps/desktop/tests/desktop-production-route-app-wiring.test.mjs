import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const registrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);
const projectSearchBindingProviderSource = readFileSync(
  new URL(
    '../src/features/search/projectSearchRouteBindingProviderV2.ts',
    import.meta.url,
  ),
  'utf8',
);
const projectCronJobsBindingProviderSource = readFileSync(
  new URL(
    '../src/features/automations/projectCronJobsRouteBindingProviderV2.ts',
    import.meta.url,
  ),
  'utf8',
);
const productionRouteAuthorityProviderSource = readFileSync(
  new URL(
    '../src/features/navigation/desktopProductionRouteAuthorityProviderV2.ts',
    import.meta.url,
  ),
  'utf8',
);
const rendererAppCompositionSource = readFileSync(
  new URL('../src/plugins/desktopRendererAppCompositionV2.tsx', import.meta.url),
  'utf8',
);
const authenticatedShellSource = readFileSync(
  new URL('../src/plugins/DesktopRendererAuthenticatedShellV2.tsx', import.meta.url),
  'utf8',
);
const authenticatedShellSurfaceSource = readFileSync(
  new URL('../src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx', import.meta.url),
  'utf8',
);
const authenticationRouterSource = readFileSync(
  new URL('../src/plugins/DesktopRendererAuthenticationRouterV2.tsx', import.meta.url),
  'utf8',
);
const rendererProductionRouterSource = readFileSync(
  new URL('../src/plugins/DesktopRendererProductionRouterV2.tsx', import.meta.url),
  'utf8',
);
const workbenchSurfaceSource = readFileSync(
  new URL('../src/plugins/DesktopWorkbenchSurfaceV2.tsx', import.meta.url),
  'utf8',
);
const routerSource = readFileSync(
  new URL('../src/features/navigation/DesktopProductionRouter.tsx', import.meta.url),
  'utf8',
);

test('V2 route factories retain the latest native route bindings', () => {
  const projectDiscoveryFactoryStart = registrySource.indexOf(
    'export function createAppProjectDiscoveryRouteRegistry',
  );
  const tenantCoreFactoryStart = registrySource.indexOf(
    'export function createAppTenantCoreRouteRegistry',
  );
  assert.notEqual(projectDiscoveryFactoryStart, -1);
  assert.notEqual(tenantCoreFactoryStart, -1);
  const projectDiscoveryFactorySource = registrySource.slice(
    projectDiscoveryFactoryStart,
    tenantCoreFactoryStart,
  );
  const projectAdministrationFactoryStart = registrySource.indexOf(
    'export function createAppProjectAdministrationRouteRegistry',
  );
  const runtimeInfrastructureFactoryStart = registrySource.indexOf(
    'export function createAppRuntimeInfrastructureRouteRegistry',
  );
  const projectAdministrationFactorySource = registrySource.slice(
    projectAdministrationFactoryStart,
    runtimeInfrastructureFactoryStart,
  );
  assert.match(
    registrySource,
    /createDesktopProductionRouteRegistry\(\{[\s\S]*PROJECT_OVERVIEW_ROUTE_ID[\s\S]*createProjectOverviewRouteModuleLoader\(\{[\s\S]*configRef\.current/u,
  );
  assert.match(
    registrySource,
    /createProjectOverviewRouteBindingForRuntime\(\s*configRef\.current,\s*context,?\s*\)/u,
  );
  assert.doesNotMatch(
    registrySource,
    /createCloudProjectOverviewClient|createLocalProjectOverviewClient/u,
  );
  assert.match(
    registrySource,
    /PROJECT_SEARCH_ROUTE_ID[\s\S]*createProjectSearchRouteModuleLoader\(\{[\s\S]*projectSearchRouteBindingProviderV2\.resolve\(context\)/u,
  );
  assert.match(
    appSource,
    /projectSearchRouteBindingProviderV2\.publish\(\{[\s\S]*api,[\s\S]*scope:[\s\S]*projects:[\s\S]*capabilitySnapshot:[\s\S]*capabilityLoading:/u,
  );
  assert.doesNotMatch(appSource, /projectSearchRouteBindingRef|PROJECT_SEARCH_ROUTE_ID/u);
  assert.doesNotMatch(
    projectDiscoveryFactorySource,
    /new DesktopApiClient\(currentConfig\)|desktopCapability\(null,\s*PROJECT_SEARCH_ROUTE_ID\)/u,
  );
  assert.match(
    projectSearchBindingProviderSource,
    /desktopCapability\(input\.capabilitySnapshot,\s*PROJECT_SEARCH_ROUTE_ID\)/u,
  );
  assert.match(
    registrySource,
    /PROJECT_CRON_JOBS_ROUTE_ID[\s\S]*createProjectCronJobsRouteModuleLoader\(\{[\s\S]*projectCronJobsRouteBindingProviderV2\.resolve\(context\)/u,
  );
  assert.match(
    appSource,
    /projectCronJobsRouteBindingProviderV2\.publish\(\{[\s\S]*api:\s*desktopAutomationApiV2\.api,[\s\S]*scope:[\s\S]*projects:\s*auth\.projects,[\s\S]*capabilitySnapshot:\s*desktopCapabilityState\.snapshot/u,
  );
  assert.doesNotMatch(appSource, /projectCronJobsRouteBindingRef|automationRunCapability/u);
  assert.doesNotMatch(
    projectAdministrationFactorySource,
    /new DesktopApiClient\(currentConfig\)|desktopCapability\(null,\s*['"]automation_run['"]\)|\(\) => undefined/u,
  );
  assert.match(
    projectCronJobsBindingProviderSource,
    /desktopCapability\(input\.capabilitySnapshot,\s*AUTOMATION_RUN_CAPABILITY_ID\)/u,
  );
  assert.match(
    registrySource,
    /BACKEND_STORES_ROUTE_ID[\s\S]*createBackendStoresRouteModuleLoader\(\{[\s\S]*createBackendStoresController\(\{[\s\S]*createBackendStoresClient\([\s\S]*desktopVaultBoundCloudRequestBroker\(\)/u,
  );
  assert.match(
    registrySource,
    /PROJECT_PLAYBOOKS_ROUTE_ID[\s\S]*createProjectPlaybooksRouteModuleLoader\(\{[\s\S]*createProjectPlaybooksController\(\{[\s\S]*createProjectPlaybooksClient\([\s\S]*desktopVaultBoundCloudRequestBroker\(\)/u,
  );
  assert.match(
    registrySource,
    /BACKEND_STORES_ROUTE_ID[\s\S]*authority:\s*['"]cloud['"][\s\S]*PROJECT_PLAYBOOKS_ROUTE_ID[\s\S]*authority:\s*['"]cloud['"]/u,
  );
  assert.doesNotMatch(
    registrySource,
    /(?:BACKEND_STORES_ROUTE_ID|PROJECT_PLAYBOOKS_ROUTE_ID)[\s\S]{0,700}authority:\s*currentConfig\.mode/u,
  );
});

test('auxiliary V2 route composition binds its three native loaders and Profile route', () => {
  const auxiliaryFactoryStart = registrySource.indexOf(
    'export function createAppAuxiliaryRouteRegistry',
  );
  const projectKnowledgeFactoryStart = registrySource.indexOf(
    'export function createAppProjectKnowledgeRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(auxiliaryFactoryStart, -1);
  assert.notEqual(projectKnowledgeFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const auxiliaryFactorySource = registrySource.slice(
    auxiliaryFactoryStart,
    projectKnowledgeFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  for (const routeId of [
    'BACKEND_STORES_ROUTE_ID',
    'PROJECT_PLAYBOOKS_ROUTE_ID',
    'PROJECT_SUPPORT_ROUTE_ID',
  ]) {
    assert.match(auxiliaryFactorySource, new RegExp(`\\[${routeId}\\]`));
    assert.doesNotMatch(tenantCreationFactorySource, new RegExp(`\\[${routeId}\\]`));
  }
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppAuxiliaryRouteRegistry/u,
  );
  assert.match(auxiliaryFactorySource, /id:\s*PROFILE_ROUTE_ID/u);
  assert.match(
    auxiliaryFactorySource,
    /createProfileRouteModuleLoader[\s\S]*createProfileRouteBindingForRuntime[\s\S]*id:\s*PROFILE_ROUTE_ID/u,
  );
  assert.doesNotMatch(
    appSource,
    /createProfileRouteModuleLoader|createProfileRouteBindingForRuntime/u,
  );
});

test('project knowledge V2 route composition binds only its five native loaders', () => {
  const projectKnowledgeFactoryStart = registrySource.indexOf(
    'export function createAppProjectKnowledgeRouteRegistry',
  );
  const projectAgentFactoryStart = registrySource.indexOf(
    'export function createAppProjectAgentRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(projectKnowledgeFactoryStart, -1);
  assert.notEqual(projectAgentFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const projectKnowledgeFactorySource = registrySource.slice(
    projectKnowledgeFactoryStart,
    projectAgentFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  for (const routeId of [
    'PROJECT_TEAM_ROUTE_ID',
    'PROJECT_MEMORIES_ROUTE_ID',
    'PROJECT_ENTITIES_ROUTE_ID',
    'PROJECT_COMMUNITIES_ROUTE_ID',
    'PROJECT_GRAPH_ROUTE_ID',
  ]) {
    assert.match(projectKnowledgeFactorySource, new RegExp(`\\[${routeId}\\]`));
    assert.doesNotMatch(tenantCreationFactorySource, new RegExp(`\\[${routeId}\\]`));
  }
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppProjectKnowledgeRouteRegistry/u,
  );
});

test('project agent V2 route composition binds only its three native loaders', () => {
  const projectAgentFactoryStart = registrySource.indexOf(
    'export function createAppProjectAgentRouteRegistry',
  );
  const projectAdministrationFactoryStart = registrySource.indexOf(
    'export function createAppProjectAdministrationRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(projectAgentFactoryStart, -1);
  assert.notEqual(projectAdministrationFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const projectAgentFactorySource = registrySource.slice(
    projectAgentFactoryStart,
    projectAdministrationFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  for (const routeId of [
    'PROJECT_AGENT_DASHBOARD_ROUTE_ID',
    'PROJECT_AGENT_LOGS_ROUTE_ID',
    'PROJECT_AGENT_PATTERNS_ROUTE_ID',
  ]) {
    assert.match(projectAgentFactorySource, new RegExp(`\\[${routeId}\\]`));
    assert.doesNotMatch(tenantCreationFactorySource, new RegExp(`\\[${routeId}\\]`));
  }
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppProjectAgentRouteRegistry/u,
  );
});

test('project administration V2 route composition binds its five configuration loaders', () => {
  const projectAdministrationFactoryStart = registrySource.indexOf(
    'export function createAppProjectAdministrationRouteRegistry',
  );
  const runtimeInfrastructureFactoryStart = registrySource.indexOf(
    'export function createAppRuntimeInfrastructureRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(projectAdministrationFactoryStart, -1);
  assert.notEqual(runtimeInfrastructureFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const projectAdministrationFactorySource = registrySource.slice(
    projectAdministrationFactoryStart,
    runtimeInfrastructureFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  for (const routeId of [
    'PROJECT_SCHEMA_ROUTE_ID',
    'PROJECT_CHANNELS_ROUTE_ID',
    'PROJECT_MAINTENANCE_ROUTE_ID',
    'PROJECT_CRON_JOBS_ROUTE_ID',
    'PROJECT_SETTINGS_ROUTE_ID',
  ]) {
    assert.match(projectAdministrationFactorySource, new RegExp(`\\[${routeId}\\]`));
    assert.doesNotMatch(tenantCreationFactorySource, new RegExp(`\\[${routeId}\\]`));
  }
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppProjectAdministrationRouteRegistry/u,
  );
});

test('runtime infrastructure V2 route composition binds its seven canonical loaders', () => {
  const runtimeInfrastructureFactoryStart = registrySource.indexOf(
    'export function createAppRuntimeInfrastructureRouteRegistry',
  );
  const projectWorkspaceFactoryStart = registrySource.indexOf(
    'export function createAppProjectWorkspaceRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(runtimeInfrastructureFactoryStart, -1);
  assert.notEqual(projectWorkspaceFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const runtimeInfrastructureFactorySource = registrySource.slice(
    runtimeInfrastructureFactoryStart,
    projectWorkspaceFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  for (const routeId of [
    'TENANT_POOL_ROUTE_ID',
    'TENANT_INSTANCES_ROUTE_ID',
    'TENANT_CLUSTERS_ROUTE_ID',
    'TENANT_DEPLOY_ROUTE_ID',
    'TENANT_INSTANCE_TEMPLATES_ROUTE_ID',
    'TENANT_RUNTIMES_ROUTE_ID',
    'TENANT_GENES_ROUTE_ID',
  ]) {
    assert.match(runtimeInfrastructureFactorySource, new RegExp(`\\[${routeId}\\]`));
    assert.doesNotMatch(tenantCreationFactorySource, new RegExp(`\\[${routeId}\\]`));
  }
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_RUNTIME_INFRASTRUCTURE_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppRuntimeInfrastructureRouteRegistry/u,
  );
});

test('project workspace V2 route composition binds only its three native loaders', () => {
  const projectWorkspaceFactoryStart = registrySource.indexOf(
    'export function createAppProjectWorkspaceRouteRegistry',
  );
  const projectDiscoveryFactoryStart = registrySource.indexOf(
    'export function createAppProjectDiscoveryRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(projectWorkspaceFactoryStart, -1);
  assert.notEqual(projectDiscoveryFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const projectWorkspaceFactorySource = registrySource.slice(
    projectWorkspaceFactoryStart,
    projectDiscoveryFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  for (const routeId of [
    'PROJECT_OVERVIEW_ROUTE_ID',
    'PROJECT_WORKSPACES_ROUTE_ID',
    'PROJECT_BLACKBOARD_ROUTE_ID',
  ]) {
    assert.match(projectWorkspaceFactorySource, new RegExp(`\\[${routeId}\\]`));
    assert.doesNotMatch(tenantCreationFactorySource, new RegExp(`\\[${routeId}\\]`));
  }
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_PROJECT_WORKSPACE_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppProjectWorkspaceRouteRegistry/u,
  );
});

test('project discovery V2 route composition binds only its search loader', () => {
  const projectDiscoveryFactoryStart = registrySource.indexOf(
    'export function createAppProjectDiscoveryRouteRegistry',
  );
  const tenantCoreFactoryStart = registrySource.indexOf(
    'export function createAppTenantCoreRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(projectDiscoveryFactoryStart, -1);
  assert.notEqual(tenantCoreFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const projectDiscoveryFactorySource = registrySource.slice(
    projectDiscoveryFactoryStart,
    tenantCoreFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  assert.match(projectDiscoveryFactorySource, /\[PROJECT_SEARCH_ROUTE_ID\]/u);
  assert.doesNotMatch(tenantCreationFactorySource, /\[PROJECT_SEARCH_ROUTE_ID\]/u);
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_PROJECT_DISCOVERY_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppProjectDiscoveryRouteRegistry/u,
  );
});

test('tenant core V2 route composition binds its six canonical loaders', () => {
  const tenantCoreFactoryStart = registrySource.indexOf(
    'export function createAppTenantCoreRouteRegistry',
  );
  const tenantAgentBuildingFactoryStart = registrySource.indexOf(
    'export function createAppTenantAgentBuildingRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(tenantCoreFactoryStart, -1);
  assert.notEqual(tenantAgentBuildingFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const tenantCoreFactorySource = registrySource.slice(
    tenantCoreFactoryStart,
    tenantAgentBuildingFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  for (const routeId of [
    'AGENT_WORKSPACE_ROUTE_ID',
    'TENANT_OVERVIEW_ROUTE_ID',
    'TENANT_PROJECTS_ROUTE_ID',
    'TENANT_WORKSPACES_ROUTE_ID',
    'TENANT_TASKS_ROUTE_ID',
    'TENANT_ANALYTICS_ROUTE_ID',
  ]) {
    assert.match(tenantCoreFactorySource, new RegExp(`\\[${routeId}\\]`));
    assert.doesNotMatch(tenantCreationFactorySource, new RegExp(`\\[${routeId}\\]`));
  }
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppTenantCoreRouteRegistry/u,
  );
});

test('tenant agent building V2 route composition binds its six canonical loaders', () => {
  const tenantAgentBuildingFactoryStart = registrySource.indexOf(
    'export function createAppTenantAgentBuildingRouteRegistry',
  );
  const tenantExtensionsIntegrationsFactoryStart = registrySource.indexOf(
    'export function createAppTenantExtensionsIntegrationsRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(tenantAgentBuildingFactoryStart, -1);
  assert.notEqual(tenantExtensionsIntegrationsFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const tenantAgentBuildingFactorySource = registrySource.slice(
    tenantAgentBuildingFactoryStart,
    tenantExtensionsIntegrationsFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  for (const routeId of [
    'TENANT_AGENT_DASHBOARD_ROUTE_ID',
    'TENANT_AGENT_BINDINGS_ROUTE_ID',
    'TENANT_AGENT_DEFINITIONS_ROUTE_ID',
    'TENANT_SKILLS_ROUTE_ID',
    'TENANT_EVOLUTION_ROUTE_ID',
    'TENANT_PATTERNS_ROUTE_ID',
  ]) {
    assert.match(tenantAgentBuildingFactorySource, new RegExp(`\\[${routeId}\\]`));
    assert.doesNotMatch(tenantCreationFactorySource, new RegExp(`\\[${routeId}\\]`));
  }
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_TENANT_AGENT_BUILDING_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppTenantAgentBuildingRouteRegistry/u,
  );
});

test('tenant extensions and integrations V2 route composition binds its six canonical loaders', () => {
  const tenantExtensionsIntegrationsFactoryStart = registrySource.indexOf(
    'export function createAppTenantExtensionsIntegrationsRouteRegistry',
  );
  const tenantGovernanceFactoryStart = registrySource.indexOf(
    'export function createAppTenantGovernanceRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(tenantExtensionsIntegrationsFactoryStart, -1);
  assert.notEqual(tenantGovernanceFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const tenantExtensionsIntegrationsFactorySource = registrySource.slice(
    tenantExtensionsIntegrationsFactoryStart,
    tenantGovernanceFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  for (const routeId of [
    'TENANT_PLUGINS_ROUTE_ID',
    'TENANT_MCP_SERVERS_ROUTE_ID',
    'TENANT_ACP_ROUTE_ID',
    'TENANT_TEMPLATES_ROUTE_ID',
    'TENANT_PROVIDERS_ROUTE_ID',
    'TENANT_WEBHOOKS_ROUTE_ID',
  ]) {
    assert.match(tenantExtensionsIntegrationsFactorySource, new RegExp(`\\[${routeId}\\]`));
    assert.doesNotMatch(tenantCreationFactorySource, new RegExp(`\\[${routeId}\\]`));
  }
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppTenantExtensionsIntegrationsRouteRegistry/u,
  );
});

test('tenant governance V2 route composition binds its nine canonical loaders', () => {
  const tenantGovernanceFactoryStart = registrySource.indexOf(
    'export function createAppTenantGovernanceRouteRegistry',
  );
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(tenantGovernanceFactoryStart, -1);
  assert.notEqual(tenantCreationFactoryStart, -1);
  const tenantGovernanceFactorySource = registrySource.slice(
    tenantGovernanceFactoryStart,
    tenantCreationFactoryStart,
  );
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  for (const routeId of [
    'TENANT_USERS_ROUTE_ID',
    'TENANT_AUDIT_LOGS_ROUTE_ID',
    'TENANT_EVENTS_ROUTE_ID',
    'TENANT_DEAD_LETTER_QUEUE_ROUTE_ID',
    'TENANT_TRUST_POLICIES_ROUTE_ID',
    'TENANT_DECISION_RECORDS_ROUTE_ID',
    'TENANT_BILLING_ROUTE_ID',
    'TENANT_ORGANIZATION_SETTINGS_ROUTE_ID',
    'TENANT_SETTINGS_ROUTE_ID',
  ]) {
    assert.match(tenantGovernanceFactorySource, new RegExp(`\\[${routeId}\\]`));
    assert.doesNotMatch(tenantCreationFactorySource, new RegExp(`\\[${routeId}\\]`));
  }
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_TENANT_GOVERNANCE_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppTenantGovernanceRouteRegistry/u,
  );
});

test('tenant creation V2 route composition preserves catalog refresh and navigation semantics', () => {
  const tenantCreationFactoryStart = registrySource.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(tenantCreationFactoryStart, -1);
  const tenantCreationFactorySource = registrySource.slice(tenantCreationFactoryStart);

  assert.match(tenantCreationFactorySource, /\[TENANT_CREATION_ROUTE_ID\]/u);
  assert.match(
    tenantCreationFactorySource,
    /createBinding:\s*\(\) => \{[\s\S]*const currentConfig = configRef\.current/u,
  );
  assert.match(
    tenantCreationFactorySource,
    /client:\s*createTenantCreationClient\(currentConfig\)/u,
  );
  assert.match(
    tenantCreationFactorySource,
    /tenants:\s*\[\.\.\.upsertCreatedTenant\(current\.tenants, created\)\]/u,
  );
  assert.match(
    tenantCreationFactorySource,
    /await tenantCatalogClient\.listTenants\(signal\)[\s\S]*if \(signal\.aborted\)[\s\S]*tenants:\s*authoritativeTenants/u,
  );
  assert.match(
    tenantCreationFactorySource,
    /onNavigateBack:\s*desktopProductionRouteNavigation\.clearHash/u,
  );
  assert.match(
    rendererAppCompositionSource,
    /DESKTOP_TENANT_CREATION_ROUTE_ARTIFACT_ID_V2[\s\S]*createAppTenantCreationRouteRegistry/u,
  );
  assert.doesNotMatch(registrySource, /export function createAppRouteRegistry/u);
});

test('auxiliary V2 route factory wires Project Support through scoped Cloud authority', () => {
  assert.match(
    registrySource,
    /PROJECT_SUPPORT_ROUTE_ID[\s\S]*createProjectSupportRouteModuleLoader\(\{[\s\S]*createProjectSupportRouteBindingForRuntime\(\s*configRef\.current,\s*context,?\s*\)/u,
  );
  assert.doesNotMatch(
    registrySource,
    /project-support[\s\S]{0,500}(?:iframe|webview|openExternal|window\.open)/iu,
  );
});

test('App wires the native Runtime Pool loader through the scoped runtime binding', () => {
  assert.match(
    registrySource,
    /TENANT_POOL_ROUTE_ID[\s\S]*createRuntimePoolRouteModuleLoader\(\{[\s\S]*createRuntimePoolRouteBindingForRuntime\(\s*configRef\.current,\s*context,?\s*\)/u,
  );
});

test('App wires Runtime Instances through one scoped Cloud or Local binding', () => {
  assert.match(
    registrySource,
    /TENANT_INSTANCES_ROUTE_ID[\s\S]*createRuntimeInstancesRouteModuleLoader\(\{[\s\S]*createRuntimeInstancesRouteBindingForRuntime\(\s*configRef\.current,\s*context,?\s*\)/u,
  );
});

test('App wires Runtime Clusters through one scoped Cloud or Local binding', () => {
  assert.match(
    registrySource,
    /TENANT_CLUSTERS_ROUTE_ID[\s\S]*createRuntimeClustersRouteModuleLoader\(\{[\s\S]*createRuntimeClustersRouteBindingForRuntime\(\s*configRef\.current,\s*context,?\s*\)/u,
  );
});

test('App wires Runtime Deployments through one instance-scoped Cloud or Local binding', () => {
  assert.match(
    registrySource,
    /TENANT_DEPLOY_ROUTE_ID[\s\S]*createRuntimeDeploymentsRouteModuleLoader\(\{[\s\S]*createRuntimeDeploymentsRouteBindingForRuntime\(\s*configRef\.current,\s*context,?\s*\)/u,
  );
});

test('App wires Instance Templates through one tenant-scoped Cloud or Local binding', () => {
  assert.match(
    registrySource,
    /TENANT_INSTANCE_TEMPLATES_ROUTE_ID[\s\S]*createInstanceTemplatesRouteModuleLoader\(\{[\s\S]*createInstanceTemplatesRouteBindingForRuntime\(\s*configRef\.current,\s*context,?\s*\)/u,
  );
});

test('App wires Unified Runtimes through one scoped Cloud or Local binding', () => {
  assert.match(
    registrySource,
    /TENANT_RUNTIMES_ROUTE_ID[\s\S]*createUnifiedRuntimesRouteModuleLoader\(\{[\s\S]*createUnifiedRuntimesRouteBindingForRuntime\(\s*configRef\.current,\s*context,?\s*\)/u,
  );
});

test('App publishes one V2 production route authority binding for both route hosts', () => {
  assert.match(
    appSource,
    /createDesktopProductionRouteAuthorityProviderV2\(\)/u,
  );
  assert.match(
    appSource,
    /desktopProductionRouteAuthorityProviderV2\.publish\(\{[\s\S]*auth,[\s\S]*config,[\s\S]*capabilitySnapshot:\s*desktopCapabilityState\.snapshot,[\s\S]*cloudRequestBroker:\s*desktopVaultBoundCloudRequestBroker\(\)/u,
  );
  assert.match(
    productionRouteAuthorityProviderSource,
    /desktopRouteBasePermissionsForAuth\(input\.auth\)/u,
  );
  assert.match(
    productionRouteAuthorityProviderSource,
    /createCloudDesktopRoutePermissionClient\([\s\S]*createLocalDesktopRoutePermissionClient\([\s\S]*createVaultBoundCloudDesktopRoutePermissionClient\(/u,
  );
  assert.match(
    productionRouteAuthorityProviderSource,
    /createCloudDesktopRoutePermissionResolver\([\s\S]*createLocalDesktopRoutePermissionResolver\(/u,
  );
  assert.match(
    productionRouteAuthorityProviderSource,
    /resolveDesktopRouteCapability\(input\.capabilitySnapshot,\s*capability,\s*context\)/u,
  );
  assert.match(
    productionRouteAuthorityProviderSource,
    /observedRuntimeMode\s*&&\s*observedRuntimeMode\s*!==\s*['"]native['"][\s\S]*match\.definition\.localPolicy\s*===\s*['"]cloud_only['"]/u,
  );
  assert.match(
    appSource,
    /mode=\{desktopProductionRouteAuthorityV2\.mode\}[\s\S]*permissions=\{desktopProductionRouteAuthorityV2\.permissions\}[\s\S]*resolveCapability=\{desktopProductionRouteAuthorityV2\.resolveCapability\}/u,
  );
  assert.match(
    appSource,
    /router:\s*\{[\s\S]*mode:\s*desktopProductionRouteAuthorityV2\.mode,[\s\S]*permissions:\s*desktopProductionRouteAuthorityV2\.permissions,[\s\S]*resolveCapability:\s*desktopProductionRouteAuthorityV2\.resolveCapability/u,
  );
  assert.doesNotMatch(
    appSource,
    /desktopRouteBasePermissionsForAuth|resolveDesktopRouteCapability|create(?:Cloud|Local|VaultBoundCloud)DesktopRoutePermission|deviceApprovalCapability|tenantCreationCapability|invitationAcceptanceCapability/u,
  );
  assert.doesNotMatch(appSource, /getActiveConversationId:\s*\(\)\s*=>/u);
  assert.doesNotMatch(appSource, /getActiveWorkspaceId:\s*\(\)\s*=>/u);
  assert.match(routerSource, /resolvePermissionSnapshot/u);
  assert.match(
    routerSource,
    /resolvePermissions,\s*resolvePermissionSnapshot,\s*resolveCapability,\s*switchScope/u,
  );
});

test('App scope switching uses the abort-aware transaction and no reset helper', () => {
  assert.match(
    appSource,
    /createDesktopRouteScopeTransaction\(\{[\s\S]*getCurrent:[\s\S]*createAuthority:[\s\S]*commit:[\s\S]*refresh:/u,
  );
  assert.match(appSource, /switchWorkspaceContext\([\s\S]*signal[\s\S]*\)/u);
  assert.match(appSource, /switchScope=\{switchProductionRouteScope\}/u);

  const transactionStart = appSource.indexOf('createDesktopRouteScopeTransaction({');
  const transactionEnd = appSource.indexOf(
    '\n  const switchProductionRouteScope',
    transactionStart,
  );
  const transactionSource =
    transactionStart >= 0 && transactionEnd > transactionStart
      ? appSource.slice(transactionStart, transactionEnd)
      : '';
  assert.doesNotMatch(
    transactionSource,
    /resetProjectScopedState|setAgentConversationSession|resetConversationTimeline|applySectionSideEffects/u,
  );
});

test('production routing passes a typed model to the module-owned workbench without remount keys', () => {
  const routerStart = authenticatedShellSurfaceSource.lastIndexOf(
    '<DesktopRendererProductionRouterV2',
  );
  const routerEnd = authenticatedShellSurfaceSource.indexOf('/>', routerStart);
  const routedWorkbench =
    routerStart >= 0 && routerEnd > routerStart
      ? authenticatedShellSurfaceSource.slice(routerStart, routerEnd)
      : '';

  assert.match(routedWorkbench, /\{\.\.\.surfaces\.router\}/u);
  assert.match(
    appSource,
    /router:\s*\{[\s\S]*viewModel:\s*desktopWorkbenchSurfaceViewModelV2/u,
  );
  assert.doesNotMatch(routedWorkbench, /\bkey=/u);
  assert.doesNotMatch(routedWorkbench, /<iframe|<webview|window\.open|shell\.openExternal/iu);
  assert.doesNotMatch(rendererProductionRouterSource, /childrenAuthority|ReactNode/u);
  assert.match(workbenchSurfaceSource, /<WorkspaceOverview\b/u);
  assert.doesNotMatch(appSource, /<WorkspaceOverview\b/u);
  assert.match(workbenchSurfaceSource, /<DesktopRendererActivityInboxV2/u);
  assert.match(workbenchSurfaceSource, /<DesktopRendererConversationV2/u);
  assert.match(workbenchSurfaceSource, /<DesktopRendererMyWorkQueueV2/u);
  assert.match(workbenchSurfaceSource, /<DesktopRendererNewThreadComposerV2/u);
  assert.match(workbenchSurfaceSource, /<DesktopRendererSessionWorkspaceV2/u);
  assert.match(workbenchSurfaceSource, /<DesktopRendererWorkspaceCollaborationV2/u);
  assert.doesNotMatch(
    workbenchSurfaceSource,
    /<ActivityInbox\b|view\.inbox|<ChatPanel\b|<PlatformPluginConversationSlots\b|<MyWorkQueue\b|view\.queue|<NewThreadComposer\b|view\.composer|<SessionWorkspace\b|<WorkspaceCollaborationCanvas\b/u,
  );
  assert.match(rendererAppCompositionSource, /DesktopWorkbenchSurfaceV2/u);
  assert.match(workbenchSurfaceSource, /<section className="workbench-layout">/u);
  assert.match(appSource, /const socket = useAgentSocket\(/u);
});

test('authenticated shell contribution owns the complete signed-in app shell', () => {
  const authenticatedStart = appSource.indexOf('\n  const activeTenantName =');
  const shellStart = appSource.indexOf('<DesktopRendererAuthenticatedShellV2', authenticatedStart);
  const shellEnd = appSource.indexOf('/>', shellStart);
  const shellBoundary =
    shellStart >= 0 && shellEnd > shellStart ? appSource.slice(shellStart, shellEnd) : '';

  assert.ok(authenticatedStart >= 0);
  assert.ok(shellStart > authenticatedStart);
  assert.match(shellBoundary, /viewModel=\{desktopAuthenticatedShellViewModelV2\}/u);
  assert.match(authenticatedShellSurfaceSource, /<div[\s\S]*className=\{shellClassName\}/u);
  for (const component of [
    'DesktopRendererTitlebarV2',
    'DesktopRendererSidebarV2',
    'DesktopRendererWorkbenchTabBarV2',
    'DesktopRendererProductionRouterV2',
    'DesktopRendererRightSidebarV2',
    'DesktopRendererStatusBarV2',
    'DesktopRendererCommandPaletteV2',
    'DesktopRendererKeyboardShortcutsV2',
    'DesktopRendererNewTaskFlowV2',
    'DesktopRendererWorkspaceCreateV2',
    'DesktopRendererWorkspaceSettingsV2',
    'DesktopRendererSettingsWindowV2',
  ]) {
    assert.match(authenticatedShellSurfaceSource, new RegExp(`<${component}\\b`, 'u'));
    assert.doesNotMatch(appSource, new RegExp(`<${component}\\b`, 'u'));
  }
  assert.doesNotMatch(authenticatedShellSurfaceSource, /<WorkspaceSettingsDialog\b/u);
  assert.doesNotMatch(
    authenticatedShellSource,
    /\b(?:enabled|mode|variant|workbench|authenticated)\??:\s*boolean/u,
  );
  assert.match(authenticatedShellSource, /readonly viewModel:\s*DesktopAuthenticatedShellViewModelV2/u);
  assert.doesNotMatch(authenticatedShellSource, /ReactNode|children/u);
  assert.doesNotMatch(shellBoundary, /\bkey=/u);
});

test('workbench selections release an active native production route before changing sections', () => {
  const workspaceSelectionStart = appSource.indexOf('const selectWorkspace =');
  const workspaceSelectionEnd = appSource.indexOf(
    '\n  const createWorkspaceFromDialog',
    workspaceSelectionStart,
  );
  const workspaceSelectionSource = appSource.slice(workspaceSelectionStart, workspaceSelectionEnd);
  const conversationSelectionStart = appSource.indexOf('const selectConversation =');
  const conversationSelectionEnd = appSource.indexOf(
    '\n  const sendChatMessage',
    conversationSelectionStart,
  );
  const conversationSelectionSource = appSource.slice(
    conversationSelectionStart,
    conversationSelectionEnd,
  );

  assert.match(
    workspaceSelectionSource,
    /desktopProductionRouteNavigation\.clearHash\(\)[\s\S]*applySectionSideEffects\('workspace'\)/u,
  );
  assert.match(
    conversationSelectionSource,
    /desktopProductionRouteNavigation\.clearHash\(\)[\s\S]*applySectionSideEffects\(targetSection\)/u,
  );
});

test('anonymous unknown routes are handled natively before the login gate', () => {
  const forcedPasswordGate = appSource.lastIndexOf("auth.status === 'password_change_required'");
  const anonymousGate = appSource.indexOf('if (!identityAuthenticated)', forcedPasswordGate);
  const anonymousGateEnd = appSource.indexOf('\n  const activeTenantName =', anonymousGate + 1);
  const anonymousSource =
    anonymousGate >= 0 && anonymousGateEnd > anonymousGate
      ? appSource.slice(anonymousGate, anonymousGateEnd)
      : '';

  assert.ok(forcedPasswordGate >= 0);
  assert.ok(anonymousGate > forcedPasswordGate);
  assert.match(
    anonymousSource,
    /<DesktopRendererAuthenticationRouterV2[\s\S]*<LoginScreen[\s\S]*<\/DesktopRendererAuthenticationRouterV2>/u,
  );
  assert.doesNotMatch(anonymousSource, /DesktopRendererAuthenticatedShellV2/u);
  assert.doesNotMatch(authenticationRouterSource, /projectDesktopWorkbenchCompositionV2/u);
  assert.match(
    anonymousSource,
    /location=\{desktopProductionRouteLocation\}[\s\S]*mode=\{desktopProductionRouteAuthorityV2\.mode\}[\s\S]*navigation=\{desktopProductionRouteNavigation\}/u,
  );
});

test('invitation sign-in hands the preserved hash to LoginScreen and resets after authentication', () => {
  assert.match(appSource, /forceLegacyChildren=\{invitationSignInRequested\}/u);
  assert.match(
    appSource,
    /useEffect\(\(\) => \{[\s\S]*identityAuthenticated[\s\S]*setInvitationSignInRequested\(false\)[\s\S]*\}, \[identityAuthenticated, invitationSignInRequested\]\)/u,
  );
  assert.match(
    registrySource,
    /onRequireSignIn:\s*\(\)\s*=>\s*setInvitationSignInRequested\(true\)/u,
  );
});
