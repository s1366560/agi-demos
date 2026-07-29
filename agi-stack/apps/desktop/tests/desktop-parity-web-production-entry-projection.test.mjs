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
const projectChannelsRoute = inventory.production_routes.find(
  (route) =>
    route.route_key ===
    "production-route-path-tenant-tenantid-project-projectid-channels",
);
const pluginHubEntry = "web/src/pages/tenant/PluginHub.tsx";
const reviewedPluginHubRedirect = {
  source_entry: pluginHubEntry,
  source_owner_capability_id: "tenant-tenant-plugins",
  route_registration_id:
    "production-route-path-tenant-tenantid-project-projectid-channels",
  relationship: "canonical_redirect_target",
};

function resolveReviewedAdditionalEntries(
  reviewedAdditionalWebEntries,
  overrides = {},
) {
  return resolveCapabilityWebEntries({
    capabilityId: "project-project-channels",
    kind: "canonical",
    ownedRoutes: [projectChannelsRoute],
    ownedSourceEntries: [],
    reviewedAdditionalWebEntries,
    auditedSourceEntries: new Set(
      inventory.audited_sources.map((source) => source.source_entry),
    ),
    sourceOwnerByEntry: new Map([
      [pluginHubEntry, "tenant-tenant-plugins"],
    ]),
    knownCapabilityIds: new Set([
      "project-project-channels",
      "tenant-tenant-plugins",
    ]),
    webMissing: false,
    ...overrides,
  });
}

test("a reviewed canonical redirect may share its audited target production entry", () => {
  assert.ok(projectChannelsRoute);
  assert.deepEqual(
    resolveReviewedAdditionalEntries([reviewedPluginHubRedirect]),
    [pluginHubEntry],
  );
});

test("reviewed additional Web entries reject malformed or unowned sharing", () => {
  assert.throws(
    () => resolveReviewedAdditionalEntries({ source_entry: pluginHubEntry }),
    /must be an array/u,
  );

  const invalidCases = [
    {
      name: "non-record",
      declarations: [pluginHubEntry],
      pattern: /must be an exact record/u,
    },
    {
      name: "extra field",
      declarations: [{ ...reviewedPluginHubRedirect, rationale: "redirect" }],
      pattern: /must contain exactly/u,
    },
    {
      name: "unsupported relationship",
      declarations: [
        { ...reviewedPluginHubRedirect, relationship: "redirect_text_match" },
      ],
      pattern: /canonical_redirect_target/u,
    },
    {
      name: "foreign route",
      declarations: [
        { ...reviewedPluginHubRedirect, route_registration_id: "foreign-route" },
      ],
      pattern: /does not own production route/u,
    },
    {
      name: "unaudited source",
      declarations: [reviewedPluginHubRedirect],
      overrides: { auditedSourceEntries: new Set() },
      pattern: /is not an audited routed source/u,
    },
    {
      name: "owner mismatch",
      declarations: [
        {
          ...reviewedPluginHubRedirect,
          source_owner_capability_id: "project-project-channels",
        },
      ],
      pattern: /owner mismatch/u,
    },
    {
      name: "unknown owner",
      declarations: [reviewedPluginHubRedirect],
      overrides: {
        knownCapabilityIds: new Set(["project-project-channels"]),
      },
      pattern: /unknown source owner/u,
    },
    {
      name: "duplicate source",
      declarations: [
        reviewedPluginHubRedirect,
        reviewedPluginHubRedirect,
      ],
      pattern: /duplicates source entry/u,
    },
    {
      name: "self-owned source",
      declarations: [
        {
          ...reviewedPluginHubRedirect,
          source_owner_capability_id: "project-project-channels",
        },
      ],
      overrides: {
        sourceOwnerByEntry: new Map([
          [pluginHubEntry, "project-project-channels"],
        ]),
      },
      pattern: /cannot additionally share its own source entry/u,
    },
    {
      name: "already projected source",
      declarations: [reviewedPluginHubRedirect],
      overrides: { ownedSourceEntries: [pluginHubEntry] },
      pattern: /is redundant/u,
    },
  ];

  for (const invalidCase of invalidCases) {
    assert.throws(
      () =>
        resolveReviewedAdditionalEntries(
          invalidCase.declarations,
          invalidCase.overrides,
        ),
      invalidCase.pattern,
      invalidCase.name,
    );
  }
});

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
