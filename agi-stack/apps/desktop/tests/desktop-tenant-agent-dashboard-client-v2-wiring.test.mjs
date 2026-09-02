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
const capability = source('src/features/tenant/tenantAgentDashboardCapability.ts');
const workbench = source('src/features/runtime/workbenchCapabilityClient.ts');
const provider = source('src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts');
const retiredClient = source('src/features/tenant/tenantAgentDashboardHttpClient.ts');

test('route and capability consumers share one required generation-backed dashboard facade', () => {
  assert.match(app, /createDesktopTenantAgentDashboardOperationsV2/u);
  assert.match(
    app,
    /tenantAgentDashboardOperationsV2:\s*desktopTenantAgentDashboardOperationsV2/u,
  );
  assert.match(routeRegistry, /tenantAgentDashboardOperationsV2/u);
  assert.match(
    routeRuntime,
    /createTenantAgentDashboardRouteBindingForRuntime\([\s\S]*tenantAgentDashboardOperationsV2/u,
  );
  assert.match(capability, /tenantAgentDashboardOperationsV2\.loadTenantAgentDashboard/u);
  assert.match(workbench, /desktop_tenant_agent_dashboard_authority_required/u);
  assert.match(provider, /tenantAgentDashboardOperationsV2/u);
  assert.doesNotMatch(capability, /config\.mode\s*===\s*['"]local['"]/u);
});

test('the static dashboard HTTP authority is retired without a direct fallback', () => {
  assert.equal(retiredClient, '');
  for (const productionSource of [app, routeRegistry, routeRuntime, capability, workbench, provider]) {
    assert.doesNotMatch(productionSource, /createTenantAgentDashboardHttpClient/u);
    assert.doesNotMatch(productionSource, /tenantAgentDashboardHttpClient/u);
  }
  assert.doesNotMatch(routeRuntime, /desktopApiFetch/u);
  assert.doesNotMatch(capability, /desktopApiFetch/u);
});
