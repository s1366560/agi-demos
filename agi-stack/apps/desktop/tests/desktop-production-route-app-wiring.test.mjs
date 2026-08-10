import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const registrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);
const routerSource = readFileSync(
  new URL('../src/features/navigation/DesktopProductionRouter.tsx', import.meta.url),
  'utf8',
);

test('App owns one production route registry with the latest native route bindings', () => {
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
    /PROJECT_SEARCH_ROUTE_ID[\s\S]*createProjectSearchRouteModuleLoader\(\{[\s\S]*projectSearchRouteBindingRef\.current/u,
  );
  assert.match(
    appSource,
    /projectSearchRouteBindingRef\.current\s*=\s*Object\.freeze\(\{[\s\S]*api,[\s\S]*config,[\s\S]*project:[\s\S]*capability:[\s\S]*capabilityLoading:/u,
  );
  assert.match(
    registrySource,
    /PROJECT_CRON_JOBS_ROUTE_ID[\s\S]*createProjectCronJobsRouteModuleLoader\(\{[\s\S]*projectCronJobsRouteBindingRef\.current/u,
  );
  assert.match(
    appSource,
    /projectCronJobsRouteBindingRef\.current\s*=\s*Object\.freeze\(\{[\s\S]*api:\s*automationApi,[\s\S]*config,[\s\S]*project:\s*selectedProject,[\s\S]*runCapability:\s*automationRunCapability/u,
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

test('App wires Project Support through the native scoped Cloud authority', () => {
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

test('App injects async Cloud or Local permission authority and real capability snapshots', () => {
  assert.match(appSource, /desktopRouteBasePermissionsForAuth\(auth\)/u);
  assert.match(
    appSource,
    /const broker = desktopVaultBoundCloudRequestBroker\(\)[\s\S]*createVaultBoundCloudDesktopRoutePermissionClient\(config, broker\)/u,
  );
  assert.match(
    appSource,
    /createCloudDesktopRoutePermissionClient\(\s*config,\s*desktopVaultBoundCloudRequestBroker\(\),\s*\)/u,
  );
  assert.match(
    appSource,
    /createCloudDesktopRoutePermissionResolver\(options\)[\s\S]*createLocalDesktopRoutePermissionResolver\(options\)/u,
  );
  assert.doesNotMatch(appSource, /getActiveConversationId:\s*\(\)\s*=>/u);
  assert.doesNotMatch(appSource, /getActiveWorkspaceId:\s*\(\)\s*=>/u);
  assert.match(
    appSource,
    /resolveDesktopRouteCapability\(\s*desktopCapabilityState\.snapshot,\s*capability,\s*context,?\s*\)/u,
  );
  assert.match(
    appSource,
    /resolvePermissionSnapshot=\{\s*resolveProductionRoutePermissionSnapshot\s*\}/u,
  );
  assert.match(appSource, /resolveCapability=\{resolveProductionRouteCapability\}/u);
  assert.match(
    appSource,
    /observedRouteRuntimeMode\s*=\s*desktopCapabilityState\.snapshot\?\.runtime_state[\s\S]*observedRouteRuntimeMode\s*&&\s*observedRouteRuntimeMode\s*!==\s*['"]native['"]/u,
  );
  assert.match(appSource, /match\.definition\.localPolicy\s*===\s*['"]cloud_only['"]/u);
  assert.match(appSource, /mode=\{productionRouteRuntimeMode\}/u);
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

test('production routing wraps the existing workbench tree without keying or remounting it', () => {
  const routerStart = appSource.lastIndexOf('<DesktopProductionRouter');
  const routerEnd = appSource.indexOf('</DesktopProductionRouter>', routerStart);
  const routedWorkbench =
    routerStart >= 0 && routerEnd > routerStart ? appSource.slice(routerStart, routerEnd) : '';

  assert.match(routedWorkbench, /<SessionWorkspace/u);
  assert.match(routedWorkbench, /<section className="workbench-layout">/u);
  assert.doesNotMatch(routedWorkbench, /\bkey=/u);
  assert.doesNotMatch(routedWorkbench, /<iframe|<webview|window\.open|shell\.openExternal/iu);
  assert.match(appSource, /const socket = useAgentSocket\(/u);
});

test('anonymous unknown routes are handled natively before the login gate', () => {
  const forcedPasswordGate = appSource.lastIndexOf("auth.status === 'password_change_required'");
  const anonymousGate = appSource.indexOf('if (!identityAuthenticated)', forcedPasswordGate);
  const authenticatedShell = appSource.indexOf('\n  return (\n    <Theme', anonymousGate + 1);
  const anonymousSource =
    anonymousGate >= 0 && authenticatedShell > anonymousGate
      ? appSource.slice(anonymousGate, authenticatedShell)
      : '';

  assert.ok(forcedPasswordGate >= 0);
  assert.ok(anonymousGate > forcedPasswordGate);
  assert.match(
    anonymousSource,
    /<DesktopProductionRouter[\s\S]*<LoginScreen[\s\S]*<\/DesktopProductionRouter>/u,
  );
  assert.match(
    anonymousSource,
    /location=\{desktopProductionRouteLocation\}[\s\S]*mode=\{productionRouteRuntimeMode\}[\s\S]*navigation=\{desktopProductionRouteNavigation\}/u,
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
