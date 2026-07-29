import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { resolveCapabilityWebEntries } from "../contracts/desktop-web-parity/web-production-entry-projection.mjs";

const contractRoot = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../contracts/desktop-web-parity",
);
const inventory = JSON.parse(
  readFileSync(resolve(contractRoot, "web-route-inventory.v2.json"), "utf8"),
);

test("shared routed pages remain production entries for every owning capability", () => {
  const projectWorkspaceRouteKeys = new Set([
    "production-route-path-tenant-tenantid-project-projectid-workspaces",
    "production-route-path-tenant-tenantid-project-projectid-workspaces-new",
  ]);
  const ownedRoutes = inventory.production_routes.filter((route) =>
    projectWorkspaceRouteKeys.has(route.route_key),
  );

  assert.deepEqual(
    resolveCapabilityWebEntries({
      capabilityId: "project-project-workspaces",
      kind: "canonical",
      ownedRoutes,
      ownedSourceEntries: [],
      webMissing: false,
    }),
    [
      "web/src/pages/tenant/WorkspaceCreate.tsx",
      "web/src/pages/tenant/WorkspaceList.tsx",
    ],
  );
});

test("Web production entry projection is deterministic for exceptional capability kinds", () => {
  assert.deepEqual(
    resolveCapabilityWebEntries({
      capabilityId: "native-capability",
      kind: "native_only",
      ownedRoutes: [],
      ownedSourceEntries: [],
      webMissing: false,
    }),
    ["not_applicable:web/native-capability"],
  );
  assert.deepEqual(
    resolveCapabilityWebEntries({
      capabilityId: "missing-capability",
      kind: "canonical",
      ownedRoutes: [],
      ownedSourceEntries: [],
      webMissing: true,
    }),
    ["not_applicable:web-route-missing/missing-capability"],
  );
  assert.deepEqual(
    resolveCapabilityWebEntries({
      capabilityId: "fallback-capability",
      kind: "canonical",
      ownedRoutes: [],
      ownedSourceEntries: [],
      webMissing: false,
    }),
    ["web/src/App.tsx"],
  );
});
