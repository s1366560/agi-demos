import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  CANONICAL_DESKTOP_NAVIGATION_GROUPS,
  CANONICAL_DESKTOP_NAVIGATION_METADATA,
  DESKTOP_AUXILIARY_NAVIGATION_METADATA,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/desktopCanonicalNavigationCatalog.js");
const {
  deriveDesktopNavigationDiscoveryEntries,
  deriveDesktopNavigationDiscoveryGroups,
  filterDesktopNavigationDiscoveryEntries,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/desktopNavigationDiscoveryModel.js");
const {
  CANONICAL_DESKTOP_ROUTE_IDS,
  createDesktopCanonicalRouteCatalog,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/desktopCanonicalRouteCatalog.js");
const {
  createDesktopRouteRegistry,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js");

const loaders = Object.fromEntries(
  CANONICAL_DESKTOP_ROUTE_IDS.map((routeId) => [
    routeId,
    async () => ({ default: routeId }),
  ]),
);
const registry = createDesktopCanonicalRouteCatalog(loaders);
const translate = (key, values) =>
  values?.label ? `${key}:${values.label}` : key;

function entries(overrides = {}) {
  return deriveDesktopNavigationDiscoveryEntries({
    registry,
    authenticated: true,
    context: {
      tenantId: "tenant-1",
      projectId: "project-1",
    },
    translate,
    ...overrides,
  });
}

test("Desktop discovery projects auxiliary routes only through selected navigation metadata", () => {
  assert.deepEqual(
    DESKTOP_AUXILIARY_NAVIGATION_METADATA.map(({ routeId }) => routeId),
    ["backend-stores", "project-playbooks", "project-support"],
  );
  const auxiliaryRegistry = createDesktopRouteRegistry([
    auxiliaryRoute("backend-stores", "/tenant/:tenantId/backend-stores", [
      "tenant",
    ]),
    auxiliaryRoute(
      "project-playbooks",
      "/tenant/:tenantId/project/:projectId/playbooks",
      ["tenant", "project"],
    ),
    auxiliaryRoute(
      "project-support",
      "/tenant/:tenantId/project/:projectId/support",
      ["tenant", "project"],
    ),
  ]);
  const auxiliaryEntries = deriveDesktopNavigationDiscoveryEntries({
    registry: auxiliaryRegistry,
    authenticated: true,
    context: { tenantId: "tenant-1", projectId: "project-1" },
    translate,
  });

  assert.deepEqual(
    auxiliaryEntries.map(
      ({ routeId, groupId, label, description, destinationPath }) => ({
        routeId,
        groupId,
        label,
        description,
        destinationPath,
      }),
    ),
    [
      {
        routeId: "backend-stores",
        groupId: "desktop-auxiliary",
        label: "backendStores.title",
        description: "backendStores.subtitle",
        destinationPath: "/tenant/tenant-1/backend-stores",
      },
      {
        routeId: "project-playbooks",
        groupId: "desktop-auxiliary",
        label: "projectPlaybooks.title",
        description: "projectPlaybooks.subtitle",
        destinationPath: "/tenant/tenant-1/project/project-1/playbooks",
      },
      {
        routeId: "project-support",
        groupId: "desktop-auxiliary",
        label: "projectSupport.title",
        description: "projectSupport.subtitle",
        destinationPath: "/tenant/tenant-1/project/project-1/support",
      },
    ],
  );
});

test("Desktop discovery retains the canonical nine-group order and every route once", () => {
  const groups = deriveDesktopNavigationDiscoveryGroups(entries());
  const routeIds = groups.flatMap(({ entries: groupEntries }) =>
    groupEntries.map(({ routeId }) => routeId),
  );
  assert.equal(new Set(routeIds).size, routeIds.length);
  assert.deepEqual(
    [...routeIds].sort(),
    [...CANONICAL_DESKTOP_ROUTE_IDS].sort(),
  );

  assert.deepEqual(
    groups.map(({ id }) => id),
    [
      "tenant-core-operations",
      "tenant-agent-building",
      "tenant-extensions-integrations",
      "tenant-runtime-infrastructure",
      "tenant-governance-management",
      "project-workspace",
      "project-knowledge-base",
      "project-discovery",
      "project-configuration",
    ],
  );
  assert.deepEqual(
    groups.map(({ id }) => id),
    CANONICAL_DESKTOP_NAVIGATION_GROUPS.map(({ id }) => id),
  );
  assert.deepEqual(
    groups.flatMap(({ entries: groupEntries }) =>
      groupEntries.map(({ routeId }) => routeId),
    ),
    CANONICAL_DESKTOP_NAVIGATION_GROUPS.flatMap(({ id }) =>
      CANONICAL_DESKTOP_NAVIGATION_METADATA.filter(
        ({ routeId }) => registry.byId.get(routeId)?.navGroup === id,
      ).map(({ routeId }) => routeId),
    ),
  );
});

test("Desktop discovery disables only missing authentication or required path context", () => {
  const anonymous = entries({ authenticated: false });
  assert.equal(
    anonymous.find(({ routeId }) => routeId === "tenant-tenant-overview")
      ?.disabledReason?.code,
    "desktop_navigation_authentication_required",
  );

  const tenantOnly = entries({ context: { tenantId: "tenant-1" } });
  const project = tenantOnly.find(
    ({ routeId }) => routeId === "project-project-overview",
  );
  assert.deepEqual(project?.disabledReason, {
    code: "desktop_route_context_missing",
    scope: "project",
  });
  assert.equal(project?.destinationPath, null);

  const optionalWorkspace = tenantOnly.find(
    ({ routeId }) => routeId === "tenant-tenant-workspaces",
  );
  assert.equal(optionalWorkspace?.disabledReason, null);
  assert.equal(
    optionalWorkspace?.destinationPath,
    "/tenant/tenant-1/workspaces",
  );

  const cloudOnly = tenantOnly.find(
    ({ routeId }) => routeId === "tenant-tenant-billing",
  );
  assert.equal(cloudOnly?.definition.localPolicy, "cloud_only");
  assert.equal(cloudOnly?.disabledReason, null);
});

test("Desktop discovery search covers localized copy, group, alias and route identity", () => {
  const allEntries = entries();
  assert.deepEqual(
    filterDesktopNavigationDiscoveryEntries(
      allEntries,
      "nav.billing",
      "en",
    ).map(({ routeId }) => routeId),
    ["tenant-tenant-billing"],
  );
  assert.deepEqual(
    filterDesktopNavigationDiscoveryEntries(
      allEntries,
      "tenant-governance-management",
      "en",
    ).map(({ routeId }) => routeId),
    allEntries
      .filter(({ groupId }) => groupId === "tenant-governance-management")
      .map(({ routeId }) => routeId),
  );
  assert.deepEqual(
    filterDesktopNavigationDiscoveryEntries(allEntries, "cron-jobs", "en").map(
      ({ routeId }) => routeId,
    ),
    ["project-project-cron-jobs"],
  );
  assert.deepEqual(
    filterDesktopNavigationDiscoveryEntries(
      allEntries,
      "project-project-graph",
      "en",
    ).map(({ routeId }) => routeId),
    ["project-project-graph"],
  );
});

function auxiliaryRoute(id, path, scope) {
  return {
    id,
    path,
    scope,
    navGroup: "desktop-auxiliary",
    capability: id,
    requiredPermission: [["authenticated", "tenant_member"]],
    localPolicy: "cloud_only",
    loader: async () => ({ routeId: id }),
  };
}
