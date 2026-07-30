import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(
  new URL('../src/App.tsx', import.meta.url),
  'utf8',
);
const routerSource = readFileSync(
  new URL(
    '../src/features/navigation/DesktopProductionRouter.tsx',
    import.meta.url,
  ),
  'utf8',
);

test('App owns one production route registry with a latest-config Project Overview binding', () => {
  assert.match(
    appSource,
    /createDesktopProductionRouteRegistry\(\{[\s\S]*PROJECT_OVERVIEW_ROUTE_ID[\s\S]*createProjectOverviewRouteModuleLoader\(\{[\s\S]*configRef\.current/u,
  );
  assert.match(
    appSource,
    /createProjectOverviewRouteBindingForRuntime\(\s*configRef\.current,\s*context,?\s*\)/u,
  );
  assert.doesNotMatch(
    appSource,
    /createCloudProjectOverviewClient|createLocalProjectOverviewClient/u,
  );
});

test('App injects exact permission and real capability snapshot resolvers', () => {
  assert.match(
    appSource,
    /desktopRoutePermissionsForContext\(auth,\s*context\)/u,
  );
  assert.match(
    appSource,
    /resolveDesktopRouteCapability\(\s*desktopCapabilityState\.snapshot,\s*capability,\s*context,?\s*\)/u,
  );
  assert.match(appSource, /resolvePermissions=\{resolveProductionRoutePermissions\}/u);
  assert.match(appSource, /resolveCapability=\{resolveProductionRouteCapability\}/u);
  assert.match(routerSource, /resolvePermissions/u);
  assert.match(
    routerSource,
    /resolvePermissions,\s*resolveCapability,\s*switchScope/u,
  );
});

test('App scope switching uses the abort-aware transaction and no reset helper', () => {
  assert.match(
    appSource,
    /createDesktopRouteScopeTransaction\(\{[\s\S]*getCurrent:[\s\S]*createAuthority:[\s\S]*commit:[\s\S]*refresh:/u,
  );
  assert.match(
    appSource,
    /switchWorkspaceContext\([\s\S]*signal[\s\S]*\)/u,
  );
  assert.match(appSource, /switchScope=\{switchProductionRouteScope\}/u);

  const transactionStart = appSource.indexOf(
    'createDesktopRouteScopeTransaction({',
  );
  const transactionEnd = appSource.indexOf(
    '\n  });',
    transactionStart,
  );
  const transactionSource =
    transactionStart >= 0 && transactionEnd > transactionStart
      ? appSource.slice(transactionStart, transactionEnd)
      : '';
  assert.doesNotMatch(
    transactionSource,
    /resetProjectScopedState|setAgentConversationSession|resetConversationTimeline|applySectionSideEffects/u,
  );
});

test('production routing wraps the existing workbench tree without keying or remounting it', () => {
  const routerStart = appSource.indexOf('<DesktopProductionRouter');
  const routerEnd = appSource.indexOf('</DesktopProductionRouter>', routerStart);
  const routedWorkbench =
    routerStart >= 0 && routerEnd > routerStart
      ? appSource.slice(routerStart, routerEnd)
      : '';

  assert.match(routedWorkbench, /<SessionWorkspace/u);
  assert.match(routedWorkbench, /<section className="workbench-layout">/u);
  assert.doesNotMatch(routedWorkbench, /\bkey=/u);
  assert.doesNotMatch(
    routedWorkbench,
    /<iframe|<webview|window\.open|shell\.openExternal/iu,
  );
  assert.match(appSource, /const socket = useAgentSocket\(/u);
});
