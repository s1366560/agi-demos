import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const registrySource = readFileSync(
  new URL('../src/features/navigation/appRouteRegistry.ts', import.meta.url),
  'utf8',
);
const projectSearchBindingProviderSource = readFileSync(
  new URL(
    '../src/features/search/projectSearchRouteBindingProviderV2.ts',
    import.meta.url,
  ),
  'utf8',
);
const searchSource = readFileSync(
  new URL('../src/features/search/DesktopSearch.tsx', import.meta.url),
  'utf8',
);
const automationsSource = readFileSync(
  new URL('../src/features/automations/AutomationsPage.tsx', import.meta.url),
  'utf8',
);

test('App projects capabilities into V2 Search and Automation route bindings', () => {
  assert.match(appSource, /createDesktopWorkbenchCapabilityClient/u);
  assert.match(appSource, /useDesktopCapabilitySnapshot/u);
  assert.match(
    appSource,
    /projectSearchRouteBindingProviderV2\.publish\([\s\S]*capabilitySnapshot: desktopCapabilityState\.snapshot/u,
  );
  assert.match(
    projectSearchBindingProviderSource,
    /desktopCapability\(input\.capabilitySnapshot,\s*PROJECT_SEARCH_ROUTE_ID\)/u,
  );
  assert.doesNotMatch(appSource, /projectSearchCapability|PROJECT_SEARCH_ROUTE_ID/u);
  assert.match(
    appSource,
    /projectCronJobsRouteBindingRef\.current = Object\.freeze\([\s\S]*runCapability: automationRunCapability/u,
  );
  assert.match(registrySource, /projectSearchRouteBindingProviderV2\.resolve\(context\)/u);
  assert.match(registrySource, /current\?\.runCapability/u);
  assert.doesNotMatch(appSource, /capability=\{searchCapability\}/u);
  assert.doesNotMatch(appSource, /runCapability=\{automationRunCapability\}/u);
});

test('Search blocks requests until structured availability is declared', () => {
  assert.match(searchSource, /if \(!capability\.available\) return/u);
  assert.match(searchSource, /data-reason-code=\{capability\.reason_code/u);
});

test('Automation no longer classifies availability from HTTP status codes', () => {
  assert.doesNotMatch(automationsSource, /\[404,\s*405,\s*501\]/u);
  assert.doesNotMatch(automationsSource, /capabilityUnavailable/u);
  assert.match(automationsSource, /runCapability/u);
});
