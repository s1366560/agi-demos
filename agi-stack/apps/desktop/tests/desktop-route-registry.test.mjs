import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildDesktopRoutePath,
  createDesktopRouteRegistry,
  matchDesktopRoute,
  restoreDesktopRoute,
  validateDesktopRouteContext,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js');

function definition(overrides = {}) {
  return {
    id: 'project-overview',
    path: '/tenant/:tenantId/project/:projectId/overview',
    scope: ['tenant', 'project'],
    navGroup: 'knowledge',
    capability: 'project-project-overview',
    requiredPermission: [['project:read']],
    localPolicy: 'native_equivalent',
    loader: async () => ({ default: 'ProjectOverview' }),
    ...overrides,
  };
}

test('route definitions expose only the fixed production registration fields', () => {
  const route = createDesktopRouteRegistry([definition()]).definitions[0];

  assert.deepEqual(Object.keys(route), [
    'id',
    'path',
    'scope',
    'navGroup',
    'capability',
    'requiredPermission',
    'localPolicy',
    'loader',
  ]);
  assert.equal(Object.isFrozen(route), true);
  assert.equal(Object.isFrozen(route.scope), true);
  assert.equal(Object.isFrozen(route.requiredPermission), true);
  assert.equal(Object.isFrozen(route.requiredPermission[0]), true);
});

test('registry rejects duplicate and structurally invalid route definitions', () => {
  assert.throws(
    () =>
      createDesktopRouteRegistry([
        definition(),
        definition({ path: '/tenant/:tenantId/project/:projectId/summary' }),
      ]),
    /duplicate route id/u,
  );
  assert.throws(
    () =>
      createDesktopRouteRegistry([
        definition(),
        definition({ id: 'project-summary' }),
      ]),
    /duplicate route path/u,
  );
  assert.throws(
    () =>
      createDesktopRouteRegistry([
        definition({
          id: 'project-without-project-scope',
          scope: ['tenant'],
        }),
      ]),
    /path parameters must be declared by scope/u,
  );
  assert.throws(
    () =>
      createDesktopRouteRegistry([
        definition({
          id: 'unknown-parameter',
          path: '/tenant/:tenantId/project/:projectId/:conversationId',
        }),
      ]),
    /unsupported route parameter/u,
  );
  assert.throws(
    () =>
      createDesktopRouteRegistry([
        definition({ requiredPermission: [['authenticated'], []] }),
      ]),
    /requiredPermission must contain unique non-empty permission alternatives/u,
  );
  assert.throws(
    () =>
      createDesktopRouteRegistry([
        definition({
          requiredPermission: [
            ['authenticated', 'project_member'],
            ['authenticated', 'project_member'],
          ],
        }),
      ]),
    /requiredPermission must contain unique non-empty permission alternatives/u,
  );
});

test('registry uses the audited canonical-route local policies and immutable lookup', () => {
  const registry = createDesktopRouteRegistry([
    definition({ localPolicy: 'blocked_by_web_contract' }),
  ]);

  assert.equal(
    registry.byId.get('project-overview')?.localPolicy,
    'blocked_by_web_contract',
  );
  assert.equal(typeof registry.byId.set, 'undefined');
  assert.equal(Object.isFrozen(registry.byId), true);
  assert.throws(
    () =>
      createDesktopRouteRegistry([definition({ localPolicy: 'native_only' })]),
    /unsupported local policy: native_only/u,
  );
});

test('context validation reports stable structural reason codes', () => {
  const route = definition();

  assert.deepEqual(
    validateDesktopRouteContext(route, {
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'ignored-workspace',
    }),
    {
      valid: true,
      context: {
        tenantId: 'tenant-1',
        projectId: 'project-1',
      },
    },
  );
  assert.deepEqual(
    validateDesktopRouteContext(route, { tenantId: 'tenant-1' }),
    {
      valid: false,
      reasonCode: 'desktop_route_context_missing',
      scope: 'project',
    },
  );
  assert.deepEqual(
    validateDesktopRouteContext(route, {
      tenantId: 'tenant-1',
      projectId: '   ',
    }),
    {
      valid: false,
      reasonCode: 'desktop_route_context_invalid',
      scope: 'project',
    },
  );
});

test('path building encodes opaque context ids for every supported scope', () => {
  const registry = createDesktopRouteRegistry([
    definition({
      id: 'tenant-overview',
      path: '/tenant/:tenantId/overview',
      scope: ['tenant'],
      capability: 'tenant-tenant-overview',
      requiredPermission: [['tenant:read']],
    }),
    definition(),
    definition({
      id: 'workspace-overview',
      path: '/tenant/:tenantId/project/:projectId/workspace/:workspaceId/overview',
      scope: ['tenant', 'project', 'workspace'],
      capability: 'project-project-workspaces',
      requiredPermission: [['workspace:read']],
    }),
    definition({
      id: 'instance-overview',
      path: '/tenant/:tenantId/instance/:instanceId/overview',
      scope: ['tenant', 'instance'],
      capability: 'tenant-tenant-instances',
      requiredPermission: [['instance:read']],
      localPolicy: 'cloud_only',
    }),
  ]);

  assert.equal(
    buildDesktopRoutePath(registry.byId.get('tenant-overview'), {
      tenantId: 'tenant/north',
    }),
    '/tenant/tenant%2Fnorth/overview',
  );
  assert.equal(
    buildDesktopRoutePath(registry.byId.get('project-overview'), {
      tenantId: 'tenant north',
      projectId: 'project#1',
    }),
    '/tenant/tenant%20north/project/project%231/overview',
  );
  assert.equal(
    buildDesktopRoutePath(registry.byId.get('workspace-overview'), {
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace?draft',
    }),
    '/tenant/tenant-1/project/project-1/workspace/workspace%3Fdraft/overview',
  );
  assert.equal(
    buildDesktopRoutePath(registry.byId.get('instance-overview'), {
      tenantId: 'tenant-1',
      instanceId: 'instance/1',
    }),
    '/tenant/tenant-1/instance/instance%2F1/overview',
  );
  assert.throws(
    () =>
      buildDesktopRoutePath(registry.byId.get('project-overview'), {
        tenantId: 'tenant-1',
      }),
    /desktop_route_context_missing:project/u,
  );
});

test('matching restores context without invoking declarative loaders', async () => {
  let loadCount = 0;
  const registry = createDesktopRouteRegistry([
    definition({
      loader: async () => {
        loadCount += 1;
        return { default: 'ProjectOverview' };
      },
    }),
  ]);

  const match = matchDesktopRoute(
    registry,
    '/tenant/tenant%20north/project/project%2Fone/overview?tab=recent',
  );

  assert.equal(loadCount, 0);
  assert.equal(match?.definition.id, 'project-overview');
  assert.deepEqual(match?.context, {
    tenantId: 'tenant north',
    projectId: 'project/one',
  });
  assert.equal(
    match?.canonicalPath,
    '/tenant/tenant%20north/project/project%2Fone/overview',
  );
  await match?.definition.loader();
  assert.equal(loadCount, 1);
});

test('deep-link restoration accepts hash and full URL forms and fails closed', () => {
  const registry = createDesktopRouteRegistry([definition()]);

  const hashResult = restoreDesktopRoute(
    registry,
    '#/tenant/tenant-1/project/project-1/overview/',
  );
  assert.equal(hashResult.status, 'matched');
  assert.equal(
    hashResult.match.canonicalPath,
    '/tenant/tenant-1/project/project-1/overview',
  );

  const fullUrlResult = restoreDesktopRoute(
    registry,
    'agistack://desktop#/tenant/tenant-1/project/project-2/overview?tab=recent',
  );
  assert.equal(fullUrlResult.status, 'matched');
  assert.equal(fullUrlResult.match.context.projectId, 'project-2');

  assert.deepEqual(
    restoreDesktopRoute(
      registry,
      '#/tenant/tenant-1/project/%E0%A4%A/overview',
    ),
    {
      status: 'not_found',
      reasonCode: 'desktop_route_malformed',
    },
  );
  assert.deepEqual(restoreDesktopRoute(registry, '#/unknown'), {
    status: 'not_found',
    reasonCode: 'desktop_route_not_found',
  });
});
