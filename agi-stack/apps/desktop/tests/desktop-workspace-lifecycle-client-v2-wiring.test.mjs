import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const authorityModule = source(
  'src/plugins/desktopWorkspaceLifecycleAuthorityModuleV2.ts',
);
const tenantClient = source('src/features/tenant/tenantWorkspacesV2Client.ts');
const routeRuntime = source('src/features/navigation/desktopProductionRouteRuntime.ts');
const routeRegistry = source('src/features/navigation/appRouteRegistry.ts');
const testTypeScriptConfig = source('tsconfig.test.json');
const legacyProviderPath = new URL(
  '../src/features/workspace/desktopWorkspaceLifecycleClientProviderV2.ts',
  import.meta.url,
);
const legacyTenantClientPath = new URL(
  '../src/features/tenant/tenantWorkspacesHttpClient.ts',
  import.meta.url,
);

test('App owns one stable generation-bound workspace lifecycle operation set', () => {
  assert.match(app, /createDesktopWorkspaceLifecycleOperationsV2/u);
  assert.match(
    app,
    /const desktopWorkspaceLifecycleOperationsV2 = useMemo\([\s\S]*?createDesktopWorkspaceLifecycleOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.doesNotMatch(app, /createDesktopWorkspaceLifecycleClientProviderV2/u);
  assert.doesNotMatch(app, /desktopWorkspaceLifecycleClientProviderV2\.publish/u);
  assert.equal(existsSync(legacyProviderPath), false);
});

test('workspace lifecycle handlers acquire exact V2 operations for submitted scope', () => {
  const createHandler = asyncArrowFunctionSource(app, 'createWorkspaceFromDialog');
  assert.match(
    createHandler,
    /desktopWorkspaceLifecycleOperationsV2\.createWorkspace\(\{/u,
  );
  assert.match(createHandler, /tenantId: submittedScope\.tenantId/u);
  assert.match(createHandler, /projectId: submittedScope\.projectId/u);
  assert.match(createHandler, /workspaceId: ''/u);
  assert.match(createHandler, /input,/u);
  assert.match(createHandler, /signal,/u);
  assert.doesNotMatch(
    createHandler,
    /new DesktopApiClient\(|bindOperation|createWorkspaceForProject/u,
  );

  const updateHandler = asyncArrowFunctionSource(app, 'updateWorkspaceFromDialog');
  assert.match(
    updateHandler,
    /desktopWorkspaceLifecycleOperationsV2\.updateWorkspace\(\{/u,
  );
  assert.match(updateHandler, /tenantId: submittedScope\.tenantId/u);
  assert.match(updateHandler, /projectId: submittedScope\.projectId/u);
  assert.match(updateHandler, /workspaceId: submittedScope\.workspaceId/u);
  assert.match(updateHandler, /input,/u);
  assert.match(updateHandler, /signal,/u);
  assert.doesNotMatch(
    updateHandler,
    /new DesktopApiClient\(|bindOperation|updateWorkspaceForProject/u,
  );
});

test('Tenant Workspaces composes catalog reads and lifecycle creates without HTTP authority', () => {
  assert.match(tenantClient, /DesktopWorkspaceCatalogOperationsV2/u);
  assert.match(tenantClient, /DesktopWorkspaceLifecycleOperationsV2/u);
  assert.match(
    tenantClient,
    /dependencies\.catalogOperations\.listWorkspacesForProject\(\{/u,
  );
  assert.match(
    tenantClient,
    /dependencies\.lifecycleOperations\.createWorkspace\(\{/u,
  );
  assert.doesNotMatch(tenantClient, /DesktopApiClient|fetch\(/u);
  assert.match(routeRuntime, /createTenantWorkspacesV2Client\(config, dependencies\)/u);
  assert.doesNotMatch(routeRuntime, /createTenantWorkspacesHttpClient/u);
  assert.match(
    routeRegistry,
    /catalogOperations: desktopWorkspaceCatalogOperationsV2/u,
  );
  assert.match(
    routeRegistry,
    /lifecycleOperations: desktopWorkspaceLifecycleOperationsV2/u,
  );
  assert.equal(existsSync(legacyTenantClientPath), false);
});

test('workspace lifecycle module owns only two mutations behind project leases', () => {
  assert.match(
    testTypeScriptConfig,
    /src\/plugins\/desktopWorkspaceLifecycleAuthorityModuleV2\.ts/u,
  );
  assert.match(
    testTypeScriptConfig,
    /src\/plugins\/desktopWorkspaceLifecycleContractV2\.ts/u,
  );
  assert.doesNotMatch(
    testTypeScriptConfig,
    /src\/features\/workspace\/desktopWorkspaceLifecycleClientProviderV2\.ts/u,
  );
  for (const method of ['createWorkspace', 'updateWorkspace']) {
    assert.match(authorityModule, new RegExp(method));
  }
  assert.match(authorityModule, /acquireServiceOperationLease/u);
  assert.match(authorityModule, /kind: 'project'/u);
  assert.match(authorityModule, /new DesktopApiClient\(operationConfig\)/u);
  assert.doesNotMatch(
    authorityModule,
    /listWorkspacesForProject|addWorkspaceMemberForProject|updateWorkspaceMemberRoleForProject|removeWorkspaceMemberForProject/u,
  );
  assert.doesNotMatch(
    authorityModule,
    /listWorkspaceAutonomyAttentions|resolveWorkspaceAutonomyAttention|retryWorkspaceAutonomyAttention/u,
  );
});

function asyncArrowFunctionSource(sourceText, name) {
  const start = sourceText.indexOf(`const ${name} = async`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  };', start);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end + 5);
}
