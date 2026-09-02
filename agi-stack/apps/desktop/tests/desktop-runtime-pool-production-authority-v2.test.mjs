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
const unifiedClientSource = readFileSync(
  new URL('../src/features/unified-runtimes/unifiedRuntimesClient.ts', import.meta.url),
  'utf8',
);
const workbenchSource = readFileSync(
  new URL('../src/features/runtime/workbenchCapabilityClient.ts', import.meta.url),
  'utf8',
);
const projectionSource = readFileSync(
  new URL('../src/plugins/desktopRuntimePoolHttpProjectionV2.ts', import.meta.url),
  'utf8',
);

test('Runtime Pool and Unified Runtimes require the same V2 operations facade', () => {
  assert.match(
    appSource,
    /const desktopRuntimePoolOperationsV2 = useMemo\([\s\S]*createDesktopRuntimePoolOperationsV2\([\s\S]*desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*\[\],?\s*\);/u,
  );
  assert.match(appSource, /runtimePoolOperationsV2:\s*desktopRuntimePoolOperationsV2/u);
  assert.match(
    routeRegistrySource,
    /TENANT_POOL_ROUTE_ID[\s\S]*createRuntimePoolRouteBindingForRuntime\(\s*configRef\.current,\s*context,\s*runtimePoolOperationsV2/u,
  );
  assert.match(
    routeRegistrySource,
    /TENANT_RUNTIMES_ROUTE_ID[\s\S]*createUnifiedRuntimesRouteBindingForRuntime\(\s*configRef\.current,\s*context,\s*runtimePoolOperationsV2/u,
  );
  assert.doesNotMatch(routeRuntimeSource, /createRuntimePoolHttpClient/u);
  assert.doesNotMatch(unifiedClientSource, /createRuntimePoolHttpClient|poolClient\s*\?/u);
  assert.match(unifiedClientSource, /poolClient:\s*Pick<RuntimePoolClient/u);
  assert.match(projectionSource, /createRuntimePoolHttpClient/u);
});

test('Workbench observes Cloud Runtime Pool only through the V2 probe and keeps Local cloud-only', () => {
  assert.match(workbenchSource, /runtimePoolOperationsV2/u);
  assert.match(workbenchSource, /probeRuntimePool/u);
  assert.match(workbenchSource, /['"]tenant-tenant-pool['"]:\s*\(config\.mode === ['"]local['"]/u);
  assert.doesNotMatch(workbenchSource, /declared\(runtimePoolCapability\(config\)\)/u);
  assert.doesNotMatch(workbenchSource, /from ['"]\.\.\/runtime-pool\/runtimePoolCapability['"]/u);
});
