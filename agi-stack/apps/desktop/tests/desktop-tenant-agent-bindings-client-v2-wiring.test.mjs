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
const capability = source('src/features/tenant/tenantAgentBindingsCapability.ts');
const workbench = source('src/features/runtime/workbenchCapabilityClient.ts');
const provider = source('src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts');
const dependencies = source('src/features/runtime/desktopWorkbenchSnapshotDependenciesV2.ts');
const snapshotAuthority = source('src/plugins/desktopWorkbenchSnapshotAuthorityModuleV2.ts');
const retiredClient = source('src/features/tenant/tenantAgentBindingsHttpClient.ts');

test('route and capability consumers share one required generation-backed bindings facade', () => {
  assert.match(app, /createDesktopTenantAgentBindingsOperationsV2/u);
  assert.match(
    app,
    /tenantAgentBindingsOperationsV2:\s*desktopTenantAgentBindingsOperationsV2/u,
  );
  assert.match(routeRegistry, /tenantAgentBindingsOperationsV2/u);
  assert.match(
    routeRuntime,
    /createTenantAgentBindingsRouteBindingForRuntime\([\s\S]*tenantAgentBindingsOperationsV2/u,
  );
  assert.match(capability, /tenantAgentBindingsOperationsV2\.listTenantAgentBindings/u);
  assert.match(workbench, /desktop_tenant_agent_bindings_authority_required/u);
  assert.match(provider, /snapshotOperationsV2: DesktopWorkbenchSnapshotOperationsV2/u);
  assert.match(provider, /desktop_workbench_snapshot_operations_required/u);
  assert.match(provider, /operations\.loadSnapshot\(\{ config, signal:/u);
  assert.match(app, /snapshotOperationsV2:\s*desktopWorkbenchSnapshotOperationsV2/u);
  assert.match(snapshotAuthority, /createDesktopWorkbenchSnapshotDependenciesV2\(operationConfig, \(\) => actions\)/u);
  assert.match(dependencies, /createDesktopTenantAgentBindingsOperationsV2\(resolveActions\)/u);
  assert.match(dependencies, /const resolveActions = \(\) => parentActions/u);
  assert.match(dependencies, /tenantAgentBindingsOperationsV2,/u);
  assert.doesNotMatch(dependencies, /GenerationActionsRefV2|new DesktopApiClient/u);
});

test('the static bindings HTTP authority is retired without a direct fallback', () => {
  assert.equal(retiredClient, '');
  for (const productionSource of [app, routeRegistry, routeRuntime, capability, workbench, provider, dependencies]) {
    assert.doesNotMatch(productionSource, /createTenantAgentBindingsHttpClient/u);
    assert.doesNotMatch(productionSource, /tenantAgentBindingsHttpClient/u);
  }
  assert.doesNotMatch(routeRuntime, /desktopApiFetch/u);
  assert.doesNotMatch(capability, /desktopApiFetch/u);
});
