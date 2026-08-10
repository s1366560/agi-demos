import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  CANONICAL_DESKTOP_NAVIGATION_GROUPS,
  CANONICAL_DESKTOP_NAVIGATION_METADATA,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopCanonicalNavigationCatalog.js');
const {
  deriveDesktopNavigationDiscoveryEntries,
  deriveDesktopNavigationDiscoveryGroups,
  filterDesktopNavigationDiscoveryEntries,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopNavigationDiscoveryModel.js');
const {
  CANONICAL_DESKTOP_ROUTE_IDS,
  createDesktopCanonicalRouteCatalog,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopCanonicalRouteCatalog.js');

const inventory = JSON.parse(
  readFileSync(
    new URL('../contracts/desktop-web-parity/web-route-inventory.v2.json', import.meta.url),
    'utf8',
  ),
);

const loaders = Object.fromEntries(
  CANONICAL_DESKTOP_ROUTE_IDS.map((routeId) => [routeId, async () => ({ default: routeId })]),
);
const registry = createDesktopCanonicalRouteCatalog(loaders);
const translate = (key, values) => (values?.label ? `${key}:${values.label}` : key);

function entries(overrides = {}) {
  return deriveDesktopNavigationDiscoveryEntries({
    registry,
    authenticated: true,
    context: {
      tenantId: 'tenant-1',
      projectId: 'project-1',
    },
    translate,
    ...overrides,
  });
}

test('Desktop discovery metadata exactly mirrors all 51 canonical Web navigation targets', () => {
  const expected = inventory.canonical_navigation_targets.map((target) => ({
    routeId: target.route_key,
    labelKey: target.label,
    displayRole: target.display_role,
    groupId: target.group_id,
  }));
  const actual = CANONICAL_DESKTOP_NAVIGATION_METADATA.map((metadata) => ({
    routeId: metadata.routeId,
    labelKey: metadata.labelKey,
    displayRole: metadata.displayRole,
    groupId: registry.byId.get(metadata.routeId)?.navGroup,
  }));

  assert.equal(actual.length, 51);
  assert.equal(new Set(actual.map(({ routeId }) => routeId)).size, 51);
  assert.deepEqual(actual, expected);
});

test('Desktop discovery retains the canonical nine-group order and every route once', () => {
  const groups = deriveDesktopNavigationDiscoveryGroups(entries());

  assert.deepEqual(
    groups.map(({ id }) => id),
    inventory.canonical_navigation_targets
      .map(({ group_id }) => group_id)
      .filter((groupId, index, ids) => ids.indexOf(groupId) === index),
  );
  assert.deepEqual(
    groups.map(({ id }) => id),
    CANONICAL_DESKTOP_NAVIGATION_GROUPS.map(({ id }) => id),
  );
  assert.deepEqual(
    groups.flatMap(({ entries: groupEntries }) => groupEntries.map(({ routeId }) => routeId)),
    CANONICAL_DESKTOP_NAVIGATION_GROUPS.flatMap(({ id }) =>
      inventory.canonical_navigation_targets
        .filter(({ group_id }) => group_id === id)
        .map(({ route_key }) => route_key),
    ),
  );
});

test('Desktop discovery disables only missing authentication or required path context', () => {
  const anonymous = entries({ authenticated: false });
  assert.equal(
    anonymous.find(({ routeId }) => routeId === 'tenant-tenant-overview')?.disabledReason?.code,
    'desktop_navigation_authentication_required',
  );

  const tenantOnly = entries({ context: { tenantId: 'tenant-1' } });
  const project = tenantOnly.find(({ routeId }) => routeId === 'project-project-overview');
  assert.deepEqual(project?.disabledReason, {
    code: 'desktop_route_context_missing',
    scope: 'project',
  });
  assert.equal(project?.destinationPath, null);

  const optionalWorkspace = tenantOnly.find(
    ({ routeId }) => routeId === 'tenant-tenant-workspaces',
  );
  assert.equal(optionalWorkspace?.disabledReason, null);
  assert.equal(optionalWorkspace?.destinationPath, '/tenant/tenant-1/workspaces');

  const cloudOnly = tenantOnly.find(({ routeId }) => routeId === 'tenant-tenant-billing');
  assert.equal(cloudOnly?.definition.localPolicy, 'cloud_only');
  assert.equal(cloudOnly?.disabledReason, null);
});

test('Desktop discovery search covers localized copy, group, alias and route identity', () => {
  const allEntries = entries();
  assert.deepEqual(
    filterDesktopNavigationDiscoveryEntries(allEntries, 'nav.billing', 'en').map(
      ({ routeId }) => routeId,
    ),
    ['tenant-tenant-billing'],
  );
  assert.deepEqual(
    filterDesktopNavigationDiscoveryEntries(allEntries, 'tenant-governance-management', 'en').map(
      ({ routeId }) => routeId,
    ),
    allEntries
      .filter(({ groupId }) => groupId === 'tenant-governance-management')
      .map(({ routeId }) => routeId),
  );
  assert.deepEqual(
    filterDesktopNavigationDiscoveryEntries(allEntries, 'cron-jobs', 'en').map(
      ({ routeId }) => routeId,
    ),
    ['project-project-cron-jobs'],
  );
  assert.deepEqual(
    filterDesktopNavigationDiscoveryEntries(allEntries, 'project-project-graph', 'en').map(
      ({ routeId }) => routeId,
    ),
    ['project-project-graph'],
  );
});
