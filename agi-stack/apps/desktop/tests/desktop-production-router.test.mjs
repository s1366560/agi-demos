import assert from 'node:assert/strict';
import { copyFileSync, mkdirSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledNavigationDirectory = '/tmp/agistack-desktop-test-dist/src/features/navigation';
mkdirSync(compiledNavigationDirectory, { recursive: true });
copyFileSync(
  new URL('../src/features/navigation/DesktopProductionRouter.css', import.meta.url),
  `${compiledNavigationDirectory}/DesktopProductionRouter.css`,
);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  DesktopProductionRouter,
  DesktopProductionRouterView,
  handleDesktopProductionRouteBoundaryEscape,
  retryDesktopProductionRoute,
  returnToDesktopWorkbench,
  shouldPassThroughAuthenticationBoundary,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/DesktopProductionRouter.js');
const {
  createDesktopRouteRegistry,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js');
const {
  DesktopRendererGenerationProviderV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererGenerationContextV2.js');
const {
  DesktopRendererProductionRouterV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/DesktopRendererProductionRouterV2.js');
const {
  DesktopRendererAuthenticationRouterV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/DesktopRendererAuthenticationRouterV2.js');
const {
  DesktopRendererAuthenticatedShellV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/DesktopRendererAuthenticatedShellV2.js');
const {
  DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2,
  DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererCompositionPortV2.js');

const source = readFileSync(
  new URL('../src/features/navigation/DesktopProductionRouter.tsx', import.meta.url),
  'utf8',
);
const stylesheet = readFileSync(
  new URL('../src/features/navigation/DesktopProductionRouter.css', import.meta.url),
  'utf8',
);
const messages = readFileSync(
  new URL('../src/features/navigation/locales/desktopProductionRouterMessages.ts', import.meta.url),
  'utf8',
);
const globalStylesheet = readFileSync(new URL('../src/styles/tokens.css', import.meta.url), 'utf8');

const routeContext = Object.freeze({
  tenantId: 'tenant-1',
  projectId: 'project-1',
});
const module = Object.freeze({
  routeId: 'project-project-overview',
  capability: 'project-project-overview',
  localPolicy: 'native_equivalent',
  disposition: 'implemented',
  availability: 'available',
  reasonCode: null,
  Surface({ module: routeModule, context }) {
    return React.createElement('output', {
      'data-surface-route': routeModule.routeId,
      'data-surface-tenant': context.tenantId,
      'data-surface-project': context.projectId,
    });
  },
});
const registry = createDesktopRouteRegistry([
  {
    id: 'project-project-overview',
    path: '/tenant/:tenantId/project/:projectId',
    scope: ['tenant', 'project'],
    navGroup: 'project-workspace',
    capability: 'project-project-overview',
    requiredPermission: [['authenticated', 'project_member']],
    localPolicy: 'native_equivalent',
    loader: async () => module,
  },
]);
const match = Object.freeze({
  definition: registry.definitions[0],
  context: routeContext,
  canonicalPath: '/tenant/tenant-1/project/project-1',
});
const capability = Object.freeze({
  availability: 'available',
  reason_code: null,
  service_version: '3.0.0',
  contract_version: '3.0.0',
  allowed_actions: ['view'],
  scope: {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: null,
    instance_id: null,
  },
  authority_revision: 4,
});
const shellMarkers = [
  'desktop-titlebar',
  'desktop-sidebar',
  'workbench-tab-bar',
  'desktop-right-sidebar',
  'desktop-status-bar',
  'command-palette',
  'keyboard-shortcuts-dialog',
  'new-task-flow',
  'workspace-create-dialog',
  'workspace-settings-dialog',
  'settings-window',
];

test('production router delegates to the React host and keeps legacy children mounted', () => {
  const location = hashLocation('');
  const markup = render(
    React.createElement(
      DesktopProductionRouter,
      {
        registry,
        location: location.port,
        mode: 'cloud',
        permissions: new Set(['authenticated', 'project_member']),
        resolveCapability: () => capability,
        switchScope: async () => {},
        navigation: { clearHash() {} },
      },
      React.createElement('article', { 'data-legacy': true }, 'Legacy workbench'),
    ),
  );

  assert.match(markup, /data-legacy="true"/u);
  assert.match(markup, /Legacy workbench/u);
  assert.doesNotMatch(markup, /desktop-production-route-stage/u);
  assert.match(source, /useDesktopHashRouteHost\(/u);
  assert.match(source, /const hostOptions = useMemo</u);
  assert.doesNotMatch(source, /useState|features\/session|stores\//u);
});

test('production V2 router admits an empty-hash workbench only through its contribution', () => {
  const contributed = renderRendererRouter({ workbenchContributed: true });
  assert.match(contributed, /data-workbench-contribution="true"/u);
  assert.match(contributed, /data-business-workbench="true"/u);

  const missing = renderRendererRouter({ workbenchContributed: false });
  assert.doesNotMatch(missing, /data-business-workbench="true"/u);
  assert.match(missing, /data-reason-code="desktop_renderer_workbench_contribution_missing"/u);

  const authenticationKernel = renderWithGeneration(
    authenticatedShellGeneration({
      authenticatedShell: false,
      workbench: false,
    }),
    authenticationRouter(React.createElement('main', { 'data-authentication-kernel': true }), {
      permissions: new Set(),
    }),
  );
  assert.match(authenticationKernel, /data-authentication-kernel="true"/u);
  assert.doesNotMatch(authenticationKernel, /desktop_renderer_workbench_contribution_missing/u);
});

test('missing authenticated shell contribution prevents every authenticated child from mounting', () => {
  const markup = renderAuthenticatedShell(
    authenticatedShellGeneration({ authenticatedShell: false }),
  );

  for (const marker of shellMarkers) {
    assert.doesNotMatch(markup, new RegExp(`data-shell-component="${marker}"`, 'u'));
  }
  assert.match(
    markup,
    /data-reason-code="desktop_renderer_authenticated_shell_contribution_missing"/u,
  );
});

test('ready authenticated shell contribution owns the complete shell child tree', () => {
  const markup = renderAuthenticatedShell(authenticatedShellGeneration());

  assert.match(markup, /data-authenticated-shell-contribution="true"/u);
  for (const marker of shellMarkers) {
    assert.match(markup, new RegExp(`data-shell-component="${marker}"`, 'u'));
  }
});

test('authenticated shell can mount while its nested workbench remains fail closed', () => {
  const value = authenticatedShellGeneration({ workbench: false });
  const markup = renderWithGeneration(
    value,
    React.createElement(
      DesktopRendererAuthenticatedShellV2,
      null,
      rendererRouter(WORKBENCH_VIEW_MODEL, {
        permissions: new Set(['authenticated']),
      }),
    ),
  );

  assert.match(markup, /data-authenticated-shell-contribution="true"/u);
  assert.doesNotMatch(markup, /data-business-workbench="true"/u);
  assert.match(markup, /data-reason-code="desktop_renderer_workbench_contribution_missing"/u);
});

test('authentication kernel remains independent from the authenticated shell contribution', () => {
  const value = authenticatedShellGeneration({
    authenticatedShell: false,
    workbench: false,
  });
  const markup = renderWithGeneration(
    value,
    authenticationRouter(React.createElement('main', { 'data-authentication-kernel': true }), {
      permissions: new Set(),
    }),
  );

  assert.match(markup, /data-authentication-kernel="true"/u);
  assert.doesNotMatch(markup, /desktop_renderer_authenticated_shell_contribution_missing/u);
});

test('ready and degraded states render the exact module Surface and route context', () => {
  for (const status of ['ready', 'degraded']) {
    const markup = renderView({
      state: {
        status,
        match,
        capability: {
          ...capability,
          availability: status === 'degraded' ? 'degraded' : 'available',
          reason_code: status === 'degraded' ? 'project_overview_read_only' : null,
        },
        module,
      },
    });

    assert.match(markup, /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u);
    assert.match(markup, /data-legacy="true"/u);
    assert.match(markup, new RegExp(`data-route-state="${status}"`, 'u'));
    assert.match(markup, /data-surface-route="project-project-overview"/u);
    assert.match(markup, /data-surface-tenant="tenant-1"/u);
    assert.match(markup, /data-surface-project="project-1"/u);
    assert.match(markup, /aria-label="Route breadcrumb"/u);
    assert.match(markup, /Return to workbench/u);
  }
});

test('a route_content module moves legacy content into one production route surface', () => {
  const contentModule = Object.freeze({
    ...module,
    contentPolicy: 'route_content',
    Surface({ content }) {
      return React.createElement('section', { 'data-route-content-owner': true }, content);
    },
  });
  const markup = renderView({
    state: {
      status: 'ready',
      match,
      capability,
      module: contentModule,
    },
  });

  assert.equal((markup.match(/data-legacy="true"/gu) ?? []).length, 1);
  assert.match(markup, /data-route-content-owner="true"/u);
  assert.match(markup, /desktop-production-route-stage/u);
});

test('only an empty hash retains legacy while every rejected deep link uses native recovery', () => {
  const emptyMarkup = renderView({
    state: {
      status: 'malformed',
      location: '',
      reasonCode: 'desktop_route_malformed',
    },
  });
  assert.match(emptyMarkup, /data-legacy="true"/u);
  assert.doesNotMatch(emptyMarkup, /desktop-production-route-stage/u);

  for (const [state, expected] of [
    [
      {
        status: 'malformed',
        location: '#/tenant/%E0%A4%A/project/project-1',
        reasonCode: 'desktop_route_malformed',
      },
      'Route could not be restored',
    ],
    [
      {
        status: 'not_found',
        location: '#/unknown?token=untrusted',
        reasonCode: 'desktop_route_not_found',
      },
      'Native route not found',
    ],
  ]) {
    const markup = renderView({ state });
    assert.match(markup, /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u);
    assert.match(markup, /data-legacy="true"/u);
    assert.match(markup, new RegExp(expected, 'u'));
    assert.match(markup, new RegExp(`data-reason-code="${state.reasonCode}"`, 'u'));
    assert.doesNotMatch(markup, new RegExp(`<code>${state.reasonCode}</code>`, 'u'));
    assert.match(markup, /data-action="return-workbench"[^>]*autofocus=""/u);
    assert.doesNotMatch(markup, /unknown\?token=untrusted/u);
  }
});

test('loading, forbidden, unavailable, and error states expose structured boundaries', () => {
  const cases = [
    [
      {
        status: 'loading',
        match,
        capability,
        attempt: 2,
      },
      ['Loading native route', 'project-project-overview'],
    ],
    [
      {
        status: 'forbidden',
        match,
        reasonCode: 'desktop_route_permission_denied',
        missingPermissions: ['project_member'],
      },
      [
        'Permission required',
        'Your current role does not have access to this route.',
        'project_member',
      ],
    ],
    [
      {
        status: 'unavailable',
        match,
        reasonCode: 'project_overview_authority_unavailable',
        capability: null,
      },
      [
        'Native route unavailable',
        'The required service or authority is currently unavailable.',
        'Retry',
      ],
    ],
    [
      {
        status: 'error',
        match,
        reasonCode: 'desktop_route_module_load_failed',
        retryable: true,
      },
      [
        'Native route failed',
        'Desktop could not load this route. Retry when the action is available.',
        'Retry',
      ],
    ],
  ];

  for (const [state, expectedValues] of cases) {
    const markup = renderView({ state });
    for (const expected of expectedValues) {
      assert.match(markup, new RegExp(expected, 'u'));
    }
  }
});

test('local cloud-only boundaries keep protocol codes non-visible and explain the recovery', () => {
  const markup = renderView({
    state: {
      status: 'unavailable',
      match,
      reasonCode: 'desktop_route_local_cloud_only',
      capability: null,
    },
  });

  assert.match(markup, /data-reason-code="desktop_route_local_cloud_only"/u);
  assert.match(
    markup,
    /This feature requires the tenant cloud service. Switch to the Cloud workspace and retry./u,
  );
  assert.doesNotMatch(markup, /<code>desktop_route_local_cloud_only<\/code>/u);
});

test('authentication-required route can preserve its deep link behind the login surface', () => {
  const deviceMatch = {
    definition: {
      ...match.definition,
      id: 'device-approval',
      path: '/device',
      scope: ['global'],
      capability: 'device-approval',
      requiredPermission: [['authenticated']],
      localPolicy: 'cloud_only',
    },
    context: {},
    canonicalPath: '/device',
  };
  const state = {
    status: 'forbidden',
    match: deviceMatch,
    reasonCode: 'desktop_route_permission_denied',
    missingPermissions: ['authenticated'],
  };
  assert.equal(shouldPassThroughAuthenticationBoundary(state, new Set(['device-approval'])), true);
  assert.equal(shouldPassThroughAuthenticationBoundary(state, new Set()), false);
  const markup = renderView({
    state,
    authenticationPassthroughRouteIds: new Set(['device-approval']),
  });
  assert.match(markup, /data-legacy="true"/u);
  assert.doesNotMatch(markup, /desktop-production-route-stage/u);
});

test('an explicit legacy-child handoff hides a ready native route without clearing its hash', () => {
  const markup = renderView({
    state: {
      status: 'ready',
      match,
      capability,
      module,
    },
    forceLegacyChildren: true,
  });

  assert.match(markup, /data-legacy="true"/u);
  assert.doesNotMatch(markup, /desktop-production-route-stage/u);
  assert.doesNotMatch(markup, /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u);
});

test('a route-scoped legacy passthrough waits for capability and scope authority', () => {
  const legacyPassthroughRouteIds = new Set(['project-project-overview']);
  for (const status of ['ready', 'degraded']) {
    const markup = renderView({
      state: {
        status,
        match,
        capability: {
          ...capability,
          availability: status === 'degraded' ? 'degraded' : 'available',
          reason_code: status === 'degraded' ? 'workspace_projection_partial' : null,
        },
        module,
      },
      legacyPassthroughRouteIds,
    });
    assert.match(markup, /data-legacy="true"/u);
    assert.doesNotMatch(markup, /desktop-production-route-stage/u);
    assert.doesNotMatch(markup, /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u);
  }

  for (const state of [
    { status: 'loading', match, capability, attempt: 1 },
    {
      status: 'forbidden',
      match,
      reasonCode: 'desktop_route_permission_denied',
      missingPermissions: ['project_member'],
    },
    {
      status: 'unavailable',
      match,
      reasonCode: 'desktop_route_capability_scope_mismatch',
      capability,
    },
  ]) {
    const markup = renderView({ state, legacyPassthroughRouteIds });
    assert.match(markup, /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u);
    assert.match(markup, /desktop-production-route-stage/u);
  }
});

test('breadcrumb return and retry actions use only the injected ports', async () => {
  let clearCalls = 0;
  let retryCalls = 0;
  returnToDesktopWorkbench({
    clearHash() {
      clearCalls += 1;
    },
  });
  assert.equal(clearCalls, 1);

  await retryDesktopProductionRoute(async () => {
    retryCalls += 1;
  });
  assert.equal(retryCalls, 1);
  assert.match(source, /data-action="return-workbench"[\s\S]*returnToDesktopWorkbench/u);
  assert.match(source, /data-action="retry-route"[\s\S]*retryDesktopProductionRoute/u);
});

test('Escape returns rejected deep links through the injected navigation port only', () => {
  let clearCalls = 0;
  let prevented = 0;
  const navigation = {
    clearHash() {
      clearCalls += 1;
    },
  };
  const event = {
    key: 'Escape',
    preventDefault() {
      prevented += 1;
    },
  };

  assert.equal(handleDesktopProductionRouteBoundaryEscape('not_found', navigation, event), true);
  assert.equal(clearCalls, 1);
  assert.equal(prevented, 1);
  assert.equal(handleDesktopProductionRouteBoundaryEscape('ready', navigation, event), false);
  assert.equal(clearCalls, 1);
  assert.equal(prevented, 1);
});

test('router styling and copy remain native, responsive, and bilingual', () => {
  assert.doesNotMatch(source, /<iframe|<webview|shell\.openExternal|window\.open|href=/iu);
  assert.match(stylesheet, /var\(--desktop-surface-3\)/u);
  assert.match(stylesheet, /@media \(max-width:/u);
  assert.match(stylesheet, /:focus-visible/u);
  assert.match(messages, /desktopProductionRouterEnUS/u);
  assert.match(messages, /desktopProductionRouterZhCN/u);
  for (const key of [
    'desktopProductionRouter.breadcrumb',
    'desktopProductionRouter.returnWorkbench',
    'desktopProductionRouter.loading.title',
    'desktopProductionRouter.forbidden.title',
    'desktopProductionRouter.unavailable.title',
    'desktopProductionRouter.error.title',
    'desktopProductionRouter.malformed.title',
    'desktopProductionRouter.notFound.title',
  ]) {
    assert.equal(messages.split(`'${key}'`).length, 3);
  }
  const referencedTokens = new Set(
    [...stylesheet.matchAll(/var\((--desktop-[a-z0-9-]+)/gu)].map((entry) => entry[1]),
  );
  for (const token of referencedTokens) {
    assert.match(globalStylesheet, new RegExp(`${token}\\s*:`, 'u'));
  }
});

function renderView({
  state,
  authenticationPassthroughRouteIds,
  forceLegacyChildren,
  legacyPassthroughRouteIds,
}) {
  return render(
    React.createElement(
      DesktopProductionRouterView,
      {
        state,
        registry,
        retry: async () => {},
        navigation: { clearHash() {} },
        authenticationPassthroughRouteIds,
        forceLegacyChildren,
        legacyPassthroughRouteIds,
      },
      React.createElement('article', { 'data-legacy': true }, 'Legacy workbench'),
    ),
  );
}

function render(element) {
  return renderToStaticMarkup(React.createElement(I18nProvider, null, element));
}

function renderRendererRouter({ workbenchContributed }) {
  return renderWithGeneration(
    authenticatedShellGeneration({
      authenticatedShell: false,
      workbench: workbenchContributed,
    }),
    rendererRouter(WORKBENCH_VIEW_MODEL),
  );
}

function renderAuthenticatedShell(value) {
  return renderWithGeneration(
    value,
    React.createElement(
      DesktopRendererAuthenticatedShellV2,
      null,
      React.createElement(
        React.Fragment,
        null,
        ...shellMarkers.map((marker) =>
          React.createElement('output', {
            'data-shell-component': marker,
            key: marker,
          }),
        ),
      ),
    ),
  );
}

function authenticatedShellGeneration({ authenticatedShell = true, workbench = true } = {}) {
  const slotDefinitions = [];
  if (authenticatedShell) {
    slotDefinitions.push({
      pluginId: 'builtin-shell',
      slot: 'authenticated_shell_surface',
      id: 'authenticated-shell',
      contract: 'ui-builtin:desktop-authenticated-shell-surface',
      moduleRef: DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2,
      permission: 'ui.authenticated-shell',
      sandbox: true,
    });
  }
  if (workbench) {
    slotDefinitions.push({
      pluginId: 'builtin-shell',
      slot: 'workbench_surface',
      id: 'workbench',
      contract: 'ui-builtin:desktop-workbench-surface',
      moduleRef: DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2,
      permission: 'ui.workbench',
      sandbox: true,
    });
  }
  return Object.freeze({
    actions: Object.freeze({
      acquireOperationLease: () => ({ release: async () => undefined }),
    }),
    composition: Object.freeze({
      createAuthenticationRouteRegistry: () => registry,
      createRouteRegistry: () => registry,
      resolveAuthenticatedShellSurface: ({ moduleRef }) =>
        moduleRef === DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2
          ? AuthenticatedShellSurface
          : null,
      resolveWorkbenchSurface: ({ moduleRef }) =>
        moduleRef === DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2 ? WorkbenchSurface : null,
    }),
    meta: Object.freeze({
      digest: 'sha256:test-generation',
      error: undefined,
      status: 'ready',
      target: 'desktop-renderer',
    }),
    state: Object.freeze({
      authority: Object.freeze({
        navigationArtifactIds: [],
        navigationDiscoveryRouteIds: [],
        navigationRouteIds: [],
        routeArtifactIds: [],
        routeArtifacts: [],
        routeIds: [],
        slotDefinitions,
        status: 'ready',
        uiSlotArtifactIds: [],
      }),
      navigationRegistry: createDesktopRouteRegistry([]),
      routeRegistry: registry,
    }),
  });
}

function AuthenticatedShellSurface({ children }) {
  return React.createElement(
    'section',
    { 'data-authenticated-shell-contribution': true },
    children,
  );
}

function WorkbenchSurface({ viewModel }) {
  return React.createElement(
    'section',
    { 'data-workbench-contribution': true },
    React.createElement('article', {
      'data-business-workbench': true,
      'data-business-workbench-kind': viewModel.view.kind,
    }),
  );
}

function renderWithGeneration(value, element) {
  return render(React.createElement(DesktopRendererGenerationProviderV2, { value }, element));
}

function rendererRouter(viewModel, overrides = {}) {
  return React.createElement(DesktopRendererProductionRouterV2, {
    location: hashLocation('').port,
    mode: 'cloud',
    navigation: { clearHash() {} },
    permissions: new Set(['authenticated', 'project_member']),
    resolveCapability: () => capability,
    switchScope: async () => undefined,
    viewModel,
    ...overrides,
  });
}

function authenticationRouter(children, overrides = {}) {
  return React.createElement(
    DesktopRendererAuthenticationRouterV2,
    {
      location: hashLocation('').port,
      mode: 'cloud',
      navigation: { clearHash() {} },
      permissions: new Set(['authenticated', 'project_member']),
      resolveCapability: () => capability,
      switchScope: async () => undefined,
      ...overrides,
    },
    children,
  );
}

const WORKBENCH_VIEW_MODEL = Object.freeze({
  error: null,
  paneStageClassName: 'pane-stage',
  session: null,
  view: Object.freeze({ kind: 'board', queue: Object.freeze({}) }),
});

function hashLocation(initialHash) {
  return {
    port: {
      readHash: () => initialHash,
      subscribe: () => () => {},
    },
  };
}
