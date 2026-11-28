import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
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

test('Runtime Clusters resolves the installed tenant page from full navigation', async () => {
  const require = createRequire(import.meta.url);
  require.extensions['.css'] = () => {};
  const { createAppRuntimeInfrastructureRouteRegistry } = require(
    '/tmp/agistack-desktop-test-dist/src/features/navigation/appRouteRegistry.js'
  );
  const registry = createAppRuntimeInfrastructureRouteRegistry({ configRef: { current: { mode: 'cloud' } } });
  const definition = registry.byId.get('tenant-tenant-clusters');
  const module = await definition.loader();
  assert.equal(module.localPolicy, 'cloud_only');
  assert.equal(module.Surface({ context: {} }), null);
  const page = module.Surface({ context: { tenantId: 't-1', projectId: 'p-1' } });
  assert.equal(page.type.name, 'InstalledRoutePage');
  assert.deepEqual(page.props, { tenantId: 't-1', projectId: null, segment: 'clusters' });
});

test('Workbench observes Runtime Clusters only through the V2 probe', () => {
  const dependencies = readFileSync(new URL('../src/features/runtime/desktopWorkbenchSnapshotDependenciesV2.ts', import.meta.url), 'utf8');
  const snapshotAuthority = readFileSync(new URL('../src/plugins/desktopWorkbenchSnapshotAuthorityModuleV2.ts', import.meta.url), 'utf8');
  assert.match(providerSource, /snapshotOperationsV2: DesktopWorkbenchSnapshotOperationsV2/u);
  assert.match(providerSource, /desktop_workbench_snapshot_operations_required/u);
  assert.match(providerSource, /operations\.loadSnapshot/u);
  assert.match(appSource, /snapshotOperationsV2:\s*desktopWorkbenchSnapshotOperationsV2/u);
  assert.match(snapshotAuthority, /createDesktopWorkbenchSnapshotDependenciesV2\(operationConfig, \(\) => actions\)/u);
  assert.match(dependencies, /createDesktopRuntimeClustersOperationsV2\(resolveActions\)/u);
  assert.match(dependencies, /const resolveActions = \(\) => parentActions/u);
  assert.match(dependencies, /runtimeClustersOperationsV2,/u);
  assert.doesNotMatch(dependencies, /GenerationActionsRefV2|new DesktopApiClient/u);
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
