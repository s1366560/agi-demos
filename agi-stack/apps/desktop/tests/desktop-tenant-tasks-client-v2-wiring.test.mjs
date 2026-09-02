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
const capability = source('src/features/tenant/tenantTasksCapability.ts');
const workbench = source('src/features/runtime/workbenchCapabilityClient.ts');
const provider = source('src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts');
const retiredClient = source('src/features/tenant/tenantTasksHttpClient.ts');

test('route and capability consumers share one required generation-backed Tasks facade', () => {
  assert.match(app, /createDesktopTenantTasksOperationsV2/u);
  assert.match(app, /tenantTasksOperationsV2:\s*desktopTenantTasksOperationsV2/u);
  assert.match(routeRegistry, /tenantTasksOperationsV2/u);
  assert.match(
    routeRuntime,
    /createTenantTasksRouteBindingForRuntime\([\s\S]*tenantTasksOperationsV2/u,
  );
  assert.match(capability, /tenantTasksOperationsV2\.loadTenantTasks/u);
  assert.match(workbench, /desktop_tenant_tasks_authority_required/u);
  assert.match(provider, /tenantTasksOperationsV2/u);
});

test('the static Tasks HTTP authority and mode-only verdict are retired without fallback', () => {
  assert.equal(retiredClient, '');
  for (const productionSource of [app, routeRegistry, routeRuntime, capability, workbench, provider]) {
    assert.doesNotMatch(productionSource, /createTenantTasksHttpClient/u);
    assert.doesNotMatch(productionSource, /tenantTasksHttpClient/u);
  }
  assert.doesNotMatch(capability, /config\.mode\s*===\s*'local'\s*\?\s*'degraded'/u);
  assert.doesNotMatch(routeRuntime, /desktopApiFetch/u);
  assert.doesNotMatch(capability, /desktopApiFetch/u);
});
