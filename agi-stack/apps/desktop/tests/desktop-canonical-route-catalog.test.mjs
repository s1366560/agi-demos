import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  CANONICAL_DESKTOP_ROUTE_IDS,
  createDesktopCanonicalRouteCatalog,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/desktopCanonicalRouteCatalog.js");
const {
  buildDesktopRoutePath,
  matchDesktopRoute,
  restoreDesktopRoute,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js");

function createCompleteLoaders() {
  return Object.fromEntries(
    CANONICAL_DESKTOP_ROUTE_IDS.map((id) => [
      id,
      async () => ({ default: { routeId: id } }),
    ]),
  );
}

test("catalog gates route entry independently from action permission inventory", () => {
  const registry = createDesktopCanonicalRouteCatalog(createCompleteLoaders());
  const projectSettings = registry.byId.get("project-project-settings");
  const runtimes = registry.byId.get("tenant-tenant-runtimes");
  const providers = registry.byId.get("tenant-tenant-providers");
  const agentWorkspace = registry.byId.get(
    "agent-workspace-tenant-agent-workspace",
  );
  const tenantWorkspaces = registry.byId.get("tenant-tenant-workspaces");
  const projectWorkspaces = registry.byId.get("project-project-workspaces");
  const blackboard = registry.byId.get(
    "project-blackboard-dynamic-project-blackboard",
  );

  assert.deepEqual(agentWorkspace.requiredPermission, [
    ["authenticated", "tenant_member"],
  ]);
  assert.deepEqual(tenantWorkspaces.requiredPermission, [
    ["authenticated", "tenant_member"],
  ]);
  assert.deepEqual(projectWorkspaces.requiredPermission, [
    ["authenticated", "project_member"],
  ]);
  assert.deepEqual(blackboard.requiredPermission, [
    ["authenticated", "project_member"],
  ]);
  assert.deepEqual(projectSettings.requiredPermission, [
    ["authenticated", "project_member"],
  ]);
  assert.deepEqual(runtimes.requiredPermission, [
    ["authenticated", "global_admin"],
    ["authenticated", "tenant_member"],
  ]);
  assert.deepEqual(providers.requiredPermission, [["authenticated"]]);
});

test("catalog preserves the route-family distribution and project Agent prefix", () => {
  const registry = createDesktopCanonicalRouteCatalog(createCompleteLoaders());
  const counts = registry.definitions.reduce(
    (result, definition) => {
      if (definition.id === "agent-workspace-tenant-agent-workspace") {
        result.agentWorkspace += 1;
      } else if (
        definition.id === "project-blackboard-dynamic-project-blackboard"
      ) {
        result.blackboard += 1;
      } else if (definition.id.startsWith("tenant-")) {
        result.tenant += 1;
      } else {
        result.project += 1;
      }
      return result;
    },
    { tenant: 0, agentWorkspace: 0, project: 0, blackboard: 0 },
  );

  assert.deepEqual(counts, {
    tenant: 33,
    agentWorkspace: 1,
    project: 16,
    blackboard: 1,
  });
  assert.equal(
    registry.byId.get("project-agent-dashboard").path,
    "/tenant/:tenantId/project/:projectId/agent",
  );
  assert.equal(
    registry.byId.get("project-agent-logs").path,
    "/tenant/:tenantId/project/:projectId/agent/logs",
  );
  assert.equal(
    registry.byId.get("project-agent-patterns").path,
    "/tenant/:tenantId/project/:projectId/agent/patterns",
  );
});

test("catalog fails closed when any loader is missing, unknown, or non-callable", () => {
  const missing = createCompleteLoaders();
  delete missing["tenant-tenant-billing"];
  assert.throws(
    () => createDesktopCanonicalRouteCatalog(missing),
    /desktop_route_loader_missing:tenant-tenant-billing/u,
  );

  const unknown = {
    ...createCompleteLoaders(),
    "external-web-handoff": async () => ({ default: "external" }),
  };
  assert.throws(
    () => createDesktopCanonicalRouteCatalog(unknown),
    /desktop_route_loader_unknown:external-web-handoff/u,
  );

  const nonCallable = createCompleteLoaders();
  nonCallable["tenant-tenant-billing"] = "https://example.test/billing";
  assert.throws(
    () => createDesktopCanonicalRouteCatalog(nonCallable),
    /desktop_route_loader_invalid:tenant-tenant-billing/u,
  );
});

test("Blackboard structurally preserves optional workspaceId query context", () => {
  const registry = createDesktopCanonicalRouteCatalog(createCompleteLoaders());
  const blackboard = registry.byId.get(
    "project-blackboard-dynamic-project-blackboard",
  );
  assert.ok(blackboard);

  assert.equal(
    buildDesktopRoutePath(blackboard, {
      tenantId: "tenant north",
      projectId: "project/one",
      workspaceId: "workspace?draft",
    }),
    "/tenant/tenant%20north/project/project%2Fone/blackboard?workspaceId=workspace%3Fdraft",
  );

  const match = matchDesktopRoute(
    registry,
    "#/tenant/tenant%20north/project/project%2Fone/blackboard?workspaceId=workspace%3Fdraft",
  );
  assert.deepEqual(match?.context, {
    tenantId: "tenant north",
    projectId: "project/one",
    workspaceId: "workspace?draft",
  });
  assert.equal(
    match?.canonicalPath,
    "/tenant/tenant%20north/project/project%2Fone/blackboard?workspaceId=workspace%3Fdraft",
  );

  const withoutWorkspace = restoreDesktopRoute(
    registry,
    "#/tenant/tenant-1/project/project-1/blackboard",
  );
  assert.equal(withoutWorkspace.status, "matched");
  assert.deepEqual(withoutWorkspace.match.context, {
    tenantId: "tenant-1",
    projectId: "project-1",
  });
});

test("canonical catalog loaders stay declarative until the matched route is loaded", async () => {
  let loadCount = 0;
  const loaders = createCompleteLoaders();
  loaders["tenant-tenant-overview"] = async () => {
    loadCount += 1;
    return { default: { routeId: "tenant-tenant-overview" } };
  };

  const registry = createDesktopCanonicalRouteCatalog(loaders);
  const match = matchDesktopRoute(registry, "#/tenant/tenant-1/overview");

  assert.equal(loadCount, 0);
  assert.equal(match?.definition.id, "tenant-tenant-overview");
  assert.deepEqual(await match?.definition.loader(), {
    default: { routeId: "tenant-tenant-overview" },
  });
  assert.equal(loadCount, 1);
});
