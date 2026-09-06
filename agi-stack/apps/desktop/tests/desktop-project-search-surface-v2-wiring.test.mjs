import { desktopProductionRuntimeSource } from './support/desktop-production-runtime-source.mjs';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  return readFileSync(new URL(`../${relativePath}`, import.meta.url), 'utf8');
}

const app = source('src/App.tsx');
const generation = desktopProductionRuntimeSource();
const authority = source('src/plugins/desktopProjectSearchAuthorityModuleV2.ts');
const binding = source('src/features/search/projectSearchRouteBindingProviderV2.ts');
const routeModule = source('src/features/search/projectSearchRouteModule.tsx');
const routeRegistry = source('src/features/navigation/appRouteRegistry.ts');

test('Project Search routes transport through a stable generation authority facade', () => {
  assert.match(app, /createDesktopProjectSearchOperationsV2/u);
  assert.match(
    app,
    /projectSearchOperationsV2:[ ]*desktopProjectSearchOperationsV2/u,
  );
  assert.doesNotMatch(
    app,
    /projectSearchRouteBindingProviderV2\.publish\(\{(?:(?!\n {2}\}\);)[\s\S])*?\bapi,/u,
  );
  assert.doesNotMatch(binding, /DesktopApiClient|\bapi:/u);
  assert.match(routeModule, /projectSearchOperationsV2/u);
  assert.match(
    routeRegistry,
    /createProjectSearchRouteModuleLoader\(\{[\s\S]*projectSearchOperationsV2/u,
  );
});

test('Project Search authority is registered and exposes only searchProject', () => {
  assert.match(generation, /desktopProjectSearchAuthorityDefinitionV2/u);
  assert.match(authority, /acquireServiceOperationLease/u);
  assert.match(authority, /service:desktop-renderer\.project-search-authority/u);
  assert.match(authority, /searchProject\(/u);
  assert.doesNotMatch(
    authority,
    /createAgentConversation|createTaskSession|saveContent|runAutomationNow/u,
  );
});
