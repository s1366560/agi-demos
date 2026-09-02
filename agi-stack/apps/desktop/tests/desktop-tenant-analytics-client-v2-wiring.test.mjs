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
const capability = source('src/features/tenant/tenantAnalyticsCapability.ts');
const workbench = source('src/features/runtime/workbenchCapabilityClient.ts');
const provider = source('src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts');
const retiredClient = source('src/features/tenant/tenantAnalyticsHttpClient.ts');

test('route and capability consumers share one generation-backed analytics facade', () => {
  assert.match(app, /createDesktopTenantAnalyticsOperationsV2/u);
  assert.match(app, /tenantAnalyticsOperationsV2:\s*desktopTenantAnalyticsOperationsV2/u);
  assert.match(routeRegistry, /tenantAnalyticsOperationsV2/u);
  assert.match(
    routeRuntime,
    /createTenantAnalyticsRouteBindingForRuntime\([\s\S]*tenantAnalyticsOperationsV2/u,
  );
  assert.match(capability, /tenantAnalyticsOperationsV2\.loadTenantAnalytics/u);
  assert.match(workbench, /tenantAnalyticsOperationsV2/u);
  assert.match(provider, /tenantAnalyticsOperationsV2/u);
});

test('the static analytics HTTP authority is retired without a direct fallback', () => {
  assert.equal(retiredClient, '');
  for (const productionSource of [app, routeRegistry, routeRuntime, capability, workbench, provider]) {
    assert.doesNotMatch(productionSource, /createTenantAnalyticsHttpClient/u);
    assert.doesNotMatch(productionSource, /tenantAnalyticsHttpClient/u);
  }
  assert.doesNotMatch(routeRuntime, /desktopApiFetch/u);
  assert.doesNotMatch(capability, /desktopApiFetch/u);
});
