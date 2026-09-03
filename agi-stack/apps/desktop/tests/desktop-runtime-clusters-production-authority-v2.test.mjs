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
  new URL('../src/plugins/desktopRuntimeClustersHttpProjectionV2.ts', import.meta.url),
  'utf8',
);

test('Runtime Clusters route requires one stable V2 operations facade', () => {
  assert.match(
    appSource,
    /const desktopRuntimeClustersOperationsV2 = useMemo\([\s\S]*createDesktopRuntimeClustersOperationsV2\([\s\S]*desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*\[\],?\s*\);/u,
  );
  assert.match(
    appSource,
    /runtimeClustersOperationsV2:\s*desktopRuntimeClustersOperationsV2/u,
  );
  assert.match(
    routeRegistrySource,
    /TENANT_CLUSTERS_ROUTE_ID[\s\S]*createRuntimeClustersRouteBindingForRuntime\(\s*configRef\.current,\s*context,\s*runtimeClustersOperationsV2/u,
  );
  assert.match(routeRuntimeSource, /createDesktopRuntimeClustersClientV2/u);
  assert.doesNotMatch(routeRuntimeSource, /createRuntimeClustersClient/u);
  assert.match(routeRuntimeSource, /desktop_runtime_clusters_authority_required/u);
});

test('Workbench observes Runtime Clusters only through the V2 probe', () => {
  assert.match(providerSource, /runtimeClustersOperationsV2:\s*input\.runtimeClustersOperationsV2/u);
  assert.match(workbenchSource, /runtimeClustersOperationsV2/u);
  assert.match(workbenchSource, /probeRuntimeClusters/u);
  assert.match(
    workbenchSource,
    /['"]tenant-tenant-clusters['"]:\s*\(config\.mode === ['"]local['"] \? declared : observed\)/u,
  );
  assert.doesNotMatch(workbenchSource, /runtimeClustersCapability/u);
  assert.match(projectionSource, /desktopApiFetch/u);
  assert.doesNotMatch(projectionSource, /new DesktopApiClient|globalThis\.fetch/u);
});
