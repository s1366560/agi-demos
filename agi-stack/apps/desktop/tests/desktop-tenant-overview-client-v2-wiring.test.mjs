import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const routeRegistry = source('src/features/navigation/appRouteRegistry.ts');
const routeRuntime = source('src/features/navigation/desktopProductionRouteRuntime.ts');
const capability = source('src/features/tenant/tenantOverviewCapability.ts');
const workbench = source('src/features/runtime/workbenchCapabilityClient.ts');
const provider = source('src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts');
const dependencies = source('src/features/runtime/desktopWorkbenchSnapshotDependenciesV2.ts');
const snapshotAuthority = source('src/plugins/desktopWorkbenchSnapshotAuthorityModuleV2.ts');
const retiredClient = source('src/features/tenant/tenantOverviewHttpClient.ts');

test('route and capability consumers share one generation-backed operations facade', () => {
  assert.match(app, /createDesktopTenantOverviewOperationsV2/u);
  assert.match(app, /tenantOverviewOperationsV2:\s*desktopTenantOverviewOperationsV2/u);
  assert.match(routeRegistry, /tenantOverviewOperationsV2/u);
  assert.match(
    routeRuntime,
    /createTenantOverviewRouteBindingForRuntime\([\s\S]*tenantOverviewOperationsV2/u,
  );
  assert.match(capability, /tenantOverviewOperationsV2\.loadTenantOverview/u);
  assert.match(workbench, /tenantOverviewOperationsV2/u);
  assert.match(provider, /snapshotOperationsV2: DesktopWorkbenchSnapshotOperationsV2/u);
  assert.match(provider, /desktop_workbench_snapshot_operations_required/u);
  assert.match(provider, /operations\.loadSnapshot\(\{ config, signal:/u);
  assert.match(app, /snapshotOperationsV2:\s*desktopWorkbenchSnapshotOperationsV2/u);
  assert.match(snapshotAuthority, /createDesktopWorkbenchSnapshotDependenciesV2\(operationConfig, \(\) => actions\)/u);
  assert.match(dependencies, /createDesktopTenantOverviewOperationsV2\(resolveActions\)/u);
  assert.match(dependencies, /const resolveActions = \(\) => parentActions/u);
  assert.match(dependencies, /tenantOverviewOperationsV2,/u);
  assert.doesNotMatch(dependencies, /GenerationActionsRefV2|new DesktopApiClient/u);
});

test('the static tenant overview HTTP authority is retired without a direct fallback', () => {
  assert.equal(retiredClient, '');
  for (const productionSource of [app, routeRegistry, routeRuntime, capability, workbench, provider, dependencies]) {
    assert.doesNotMatch(productionSource, /createTenantOverviewHttpClient/u);
    assert.doesNotMatch(productionSource, /tenantOverviewHttpClient/u);
  }
  assert.doesNotMatch(routeRuntime, /desktopApiFetch/u);
  assert.doesNotMatch(capability, /desktopApiFetch/u);
});
