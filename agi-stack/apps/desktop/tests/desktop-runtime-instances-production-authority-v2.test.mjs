import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const routeRegistrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);
const routeRuntimeSource = readFileSync(
  new URL('../src/features/navigation/desktopProductionRouteRuntime.ts', import.meta.url),
  'utf8',
);
const workbenchSource = readFileSync(
  new URL('../src/features/runtime/workbenchCapabilityClient.ts', import.meta.url),
  'utf8',
);
const providerSource = readFileSync(
  new URL('../src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts', import.meta.url),
  'utf8',
);
const projectionSource = readFileSync(
  new URL('../src/plugins/desktopRuntimeInstancesHttpProjectionV2.ts', import.meta.url),
  'utf8',
);

test('Runtime Instances route requires one stable V2 operations facade', () => {
  assert.match(
    appSource,
    /const desktopRuntimeInstancesOperationsV2 = useMemo\([\s\S]*createDesktopRuntimeInstancesOperationsV2\([\s\S]*desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*\[\],?\s*\);/u,
  );
  assert.match(
    appSource,
    /runtimeInstancesOperationsV2:\s*desktopRuntimeInstancesOperationsV2/u,
  );
  assert.match(
    routeRegistrySource,
    /TENANT_INSTANCES_ROUTE_ID[\s\S]*createRuntimeInstancesRouteBindingForRuntime\(\s*configRef\.current,\s*context,\s*runtimeInstancesOperationsV2/u,
  );
  assert.match(routeRuntimeSource, /createDesktopRuntimeInstancesClientV2/u);
  assert.doesNotMatch(routeRuntimeSource, /createRuntimeInstancesClient/u);
  assert.match(routeRuntimeSource, /desktop_runtime_instances_authority_required/u);
});

test('Workbench observes Runtime Instances only through the V2 probe', () => {
  const dependencies = readFileSync(new URL('../src/features/runtime/desktopWorkbenchSnapshotDependenciesV2.ts', import.meta.url), 'utf8');
  const snapshotAuthority = readFileSync(new URL('../src/plugins/desktopWorkbenchSnapshotAuthorityModuleV2.ts', import.meta.url), 'utf8');
  assert.match(providerSource, /snapshotOperationsV2: DesktopWorkbenchSnapshotOperationsV2/u);
  assert.match(providerSource, /desktop_workbench_snapshot_operations_required/u);
  assert.match(providerSource, /operations\.loadSnapshot/u);
  assert.match(appSource, /snapshotOperationsV2:\s*desktopWorkbenchSnapshotOperationsV2/u);
  assert.match(snapshotAuthority, /createDesktopWorkbenchSnapshotDependenciesV2\(operationConfig, \(\) => actions\)/u);
  assert.match(dependencies, /createDesktopRuntimeInstancesOperationsV2\(resolveActions\)/u);
  assert.match(dependencies, /const resolveActions = \(\) => parentActions/u);
  assert.match(dependencies, /runtimeInstancesOperationsV2,/u);
  assert.doesNotMatch(dependencies, /GenerationActionsRefV2|new DesktopApiClient/u);
  assert.match(workbenchSource, /runtimeInstancesOperationsV2/u);
  assert.match(workbenchSource, /probeRuntimeInstances/u);
  assert.match(
    workbenchSource,
    /['"]tenant-tenant-instances['"]:\s*observed\(runtimeInstances\)/u,
  );
  assert.doesNotMatch(workbenchSource, /runtimeInstancesCapability/u);
  assert.match(projectionSource, /desktopApiFetch/u);
  assert.doesNotMatch(projectionSource, /new DesktopApiClient|globalThis\.fetch/u);
});
