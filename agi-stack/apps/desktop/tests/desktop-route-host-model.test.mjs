import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  desktopRouteScopeKey,
  evaluateDesktopRouteAccess,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js");
const {
  createDesktopRouteRegistry,
  matchDesktopRoute,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js");

function route(overrides = {}) {
  return {
    id: "tenant-overview",
    path: "/tenant/:tenantId/overview",
    scope: ["tenant"],
    navGroup: "tenant-core",
    capability: "tenant-tenant-overview",
    requiredPermission: [["authenticated", "tenant_member"]],
    localPolicy: "native_equivalent",
    loader: async () => ({ default: "TenantOverview" }),
    ...overrides,
  };
}

function match(definition = route()) {
  const registry = createDesktopRouteRegistry([definition]);
  const result = matchDesktopRoute(registry, "#/tenant/tenant-1/overview");
  assert.ok(result);
  return result;
}

function capability(overrides = {}) {
  return {
    availability: "available",
    reason_code: null,
    service_version: "3.0.0",
    contract_version: "3.0.0",
    allowed_actions: ["view"],
    scope: {
      tenant_id: "tenant-1",
      project_id: null,
      workspace_id: null,
      instance_id: null,
    },
    authority_revision: 12,
    authority_source: "cloud_service",
    provenance: "observed",
    ...overrides,
  };
}

test("permission gate uses exact membership and reports every missing permission", () => {
  const result = evaluateDesktopRouteAccess({
    match: match(),
    mode: "cloud",
    permissions: new Set(["authenticated", "tenant_member_extra"]),
    capability: capability(),
  });

  assert.deepEqual(result, {
    status: "forbidden",
    reasonCode: "desktop_route_permission_denied",
    missingPermissions: ["tenant_member"],
  });
});

test("permission alternatives are OR while every permission within a row is all-of", () => {
  const definition = route({
    requiredPermission: [
      ["authenticated", "tenant_member"],
      ["authenticated", "global_admin"],
    ],
  });
  const allowed = evaluateDesktopRouteAccess({
    match: match(definition),
    mode: "cloud",
    permissions: new Set(["authenticated", "global_admin"]),
    capability: capability(),
  });
  const denied = evaluateDesktopRouteAccess({
    match: match(definition),
    mode: "cloud",
    permissions: new Set(["authenticated"]),
    capability: capability(),
  });

  assert.equal(allowed.status, "allowed");
  assert.deepEqual(denied, {
    status: "forbidden",
    reasonCode: "desktop_route_permission_denied",
    missingPermissions: ["tenant_member"],
  });
});

test("Local cloud-only and blocked Web contracts fail closed with stable reason codes", () => {
  const cloudOnly = evaluateDesktopRouteAccess({
    match: match(route({ localPolicy: "cloud_only" })),
    mode: "local",
    permissions: new Set(["authenticated", "tenant_member"]),
    capability: capability(),
  });
  const blocked = evaluateDesktopRouteAccess({
    match: match(route({ localPolicy: "blocked_by_web_contract" })),
    mode: "local",
    permissions: new Set(["authenticated", "tenant_member"]),
    capability: capability(),
  });

  assert.deepEqual(cloudOnly, {
    status: "unavailable",
    reasonCode: "desktop_route_local_cloud_only",
    capability: null,
  });
  assert.deepEqual(blocked, {
    status: "unavailable",
    reasonCode: "desktop_route_local_blocked_by_web_contract",
    capability: null,
  });
});

test("Local cloud-only disposition requires authentication but not Cloud-only administration", () => {
  const definition = route({
    requiredPermission: [["authenticated", "global_admin"]],
    localPolicy: "cloud_only",
  });
  const localCapability = capability({
    availability: "not_applicable",
    reason_code: "cloud_runtime_pool_not_applicable",
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    authority_revision: null,
  });

  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: match(definition),
      mode: "local",
      permissions: new Set(["authenticated"]),
      capability: localCapability,
    }),
    {
      status: "unavailable",
      reasonCode: "cloud_runtime_pool_not_applicable",
      capability: localCapability,
    },
  );
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: match(definition),
      mode: "local",
      permissions: new Set(),
      capability: localCapability,
    }),
    {
      status: "forbidden",
      reasonCode: "desktop_route_permission_denied",
      missingPermissions: ["authenticated", "global_admin"],
    },
  );
});

test("capability availability preserves structured unavailable and degraded authority", () => {
  const unavailableCapability = capability({
    availability: "unavailable",
    reason_code: "tenant_overview_service_unavailable",
    allowed_actions: [],
  });
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: match(),
      mode: "cloud",
      permissions: new Set(["authenticated", "tenant_member"]),
      capability: unavailableCapability,
    }),
    {
      status: "unavailable",
      reasonCode: "tenant_overview_service_unavailable",
      capability: unavailableCapability,
    },
  );

  const degradedCapability = capability({
    availability: "degraded",
    reason_code: "tenant_overview_read_only",
  });
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: match(),
      mode: "cloud",
      permissions: new Set(["authenticated", "tenant_member"]),
      capability: degradedCapability,
    }),
    {
      status: "allowed",
      presentation: "degraded",
      capability: degradedCapability,
    },
  );
});

test("active capability authority requires a revision and at least one reachable action", () => {
  const revisionlessCapability = capability({ authority_revision: null });
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: match(),
      mode: "cloud",
      permissions: new Set(["authenticated", "tenant_member"]),
      capability: revisionlessCapability,
    }),
    {
      status: "unavailable",
      reasonCode: "desktop_route_capability_authority_revision_invalid",
      capability: revisionlessCapability,
    },
  );

  const actionlessCapability = capability({ allowed_actions: [] });
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: match(),
      mode: "cloud",
      permissions: new Set(["authenticated", "tenant_member"]),
      capability: actionlessCapability,
    }),
    {
      status: "unavailable",
      reasonCode: "desktop_route_capability_actions_missing",
      capability: actionlessCapability,
    },
  );
});

test("missing and cross-scope capability authority cannot load a matched route", () => {
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: match(),
      mode: "cloud",
      permissions: new Set(["authenticated", "tenant_member"]),
      capability: null,
    }),
    {
      status: "unavailable",
      reasonCode: "desktop_route_capability_missing",
      capability: null,
    },
  );

  const crossScope = capability({
    scope: {
      tenant_id: "tenant-2",
      project_id: null,
      workspace_id: null,
      instance_id: null,
    },
  });
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: match(),
      mode: "cloud",
      permissions: new Set(["authenticated", "tenant_member"]),
      capability: crossScope,
    }),
    {
      status: "unavailable",
      reasonCode: "desktop_route_capability_scope_mismatch",
      capability: crossScope,
    },
  );
});

test("route scope keys are structural, ordered, and omit absent optional contexts", () => {
  assert.equal(
    desktopRouteScopeKey({
      tenantId: "tenant/1",
      projectId: "project one",
      workspaceId: "workspace?draft",
    }),
    "tenantId=tenant%2F1&projectId=project%20one&workspaceId=workspace%3Fdraft",
  );
  assert.equal(
    desktopRouteScopeKey({ tenantId: "tenant-1" }),
    "tenantId=tenant-1",
  );
});
