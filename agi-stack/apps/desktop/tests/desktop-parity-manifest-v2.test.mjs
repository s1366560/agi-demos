import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { validateJsonSchema } from "../contracts/desktop-web-parity/schema-validator.mjs";

const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);
const generatorSource = [
  "../contracts/desktop-web-parity/generate-parity-manifest-v2.mjs",
  "../contracts/desktop-web-parity/parity-judgment-ledger.mjs",
]
  .map((relativePath) =>
    readFileSync(new URL(relativePath, import.meta.url), "utf8"),
  )
  .join("\n");

function readJson(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, contractRoot), "utf8"));
}

test("parity manifest v2 separates desired capability contracts from evidence runs", () => {
  const schema = readJson("parity-manifest.v2.schema.json");
  const manifest = readJson("parity-manifest.v2.json");

  assert.deepEqual(validateJsonSchema(schema, manifest), []);
  assert.equal(manifest.schema_version, "2.0.0");
  assert.equal(Object.hasOwn(manifest, "runs"), false);
  assert.equal(Object.hasOwn(manifest, "results"), false);
  assert.match(
    manifest.evidence_run_schema,
    /^\.\/evidence-run\.v1\.schema\.json$/,
  );
  assert.equal(manifest.capabilities.length >= 51, true);
});

test("every capability declares all product surfaces and auditable authority metadata", () => {
  const manifest = readJson("parity-manifest.v2.json");
  const capabilityIds = new Set();

  for (const capability of manifest.capabilities) {
    assert.equal(
      capabilityIds.has(capability.id),
      false,
      `duplicate ${capability.id}`,
    );
    capabilityIds.add(capability.id);

    assert.deepEqual(
      Object.keys(capability.surfaces).sort(),
      ["desktop_cloud", "desktop_local", "native_only", "web"],
      capability.id,
    );
    assert.equal(
      capability.production_entries.web.length > 0,
      true,
      capability.id,
    );
    assert.equal(
      capability.source_revision,
      manifest.references.audit_revision,
      capability.id,
    );
    assert.equal(
      Array.isArray(capability.web_route_registration_ids),
      true,
      capability.id,
    );
    assert.equal(
      Array.isArray(capability.web_production_dependencies),
      true,
      capability.id,
    );
    assert.equal(capability.data_states.length > 0, true, capability.id);
    assert.equal(capability.interaction_states.length > 0, true, capability.id);
    assert.equal(
      capability.permission_requirements.length > 0,
      true,
      capability.id,
    );
    for (const requirement of capability.permission_requirements) {
      assert.equal(typeof requirement.surface, "string", capability.id);
      assert.equal(Array.isArray(requirement.actions), true, capability.id);
      assert.equal(typeof requirement.authentication, "string", capability.id);
      assert.equal(
        Array.isArray(requirement.authorization),
        true,
        capability.id,
      );
      assert.equal(typeof requirement.enforcement, "string", capability.id);
    }
    assert.equal(
      capability.expected_observable_result.length > 0,
      true,
      capability.id,
    );
    assert.equal(
      capability.evidence_requirements.length > 0,
      true,
      capability.id,
    );
    assert.equal(capability.judgment.agent_id.length > 0, true, capability.id);
    assert.equal(
      capability.judgment.tool_name,
      "structured_parity_judgment",
      capability.id,
    );
    assert.equal(typeof capability.judgment.input, "object", capability.id);
    assert.equal(typeof capability.judgment.output, "object", capability.id);
    assert.equal(capability.judgment.output.verdict, "accepted", capability.id);
    assert.equal(capability.judgment.rationale.length > 0, true, capability.id);
    assert.equal(capability.judgment.latency_ms > 0, true, capability.id);
  }
});

test("manifest maps every canonical Web route and routed source entry without external handoff", () => {
  const manifest = readJson("parity-manifest.v2.json");
  const inventory = readJson("web-route-inventory.v2.json");
  const mappedRouteIds = new Set();
  const mappedRouteRegistrationIds = new Set();
  const mappedWebSources = new Set();

  for (const capability of manifest.capabilities) {
    for (const routeId of capability.web_route_ids) {
      assert.equal(
        mappedRouteIds.has(routeId),
        false,
        `route ${routeId} mapped more than once`,
      );
      mappedRouteIds.add(routeId);
    }
    for (const routeId of capability.web_route_registration_ids) {
      assert.equal(
        mappedRouteRegistrationIds.has(routeId),
        false,
        `production route ${routeId} mapped more than once`,
      );
      mappedRouteRegistrationIds.add(routeId);
    }
    for (const sourceEntry of capability.production_entries.web) {
      mappedWebSources.add(sourceEntry);
    }

    for (const surface of [
      capability.surfaces.desktop_cloud,
      capability.surfaces.desktop_local,
    ]) {
      assert.notEqual(surface.disposition, "external_browser", capability.id);
      assert.notEqual(surface.disposition, "webview", capability.id);
    }
  }

  assert.deepEqual(
    [...mappedRouteIds].sort(),
    inventory.canonical_navigation_targets
      .map((route) => route.route_key)
      .sort(),
  );
  assert.deepEqual(
    [...mappedRouteRegistrationIds].sort(),
    inventory.production_routes.map((route) => route.route_key).sort(),
  );
  for (const lazyPage of inventory.lazy_page_entries) {
    assert.equal(
      mappedWebSources.has(lazyPage.source_entry),
      true,
      `unmapped lazy page ${lazyPage.id}: ${lazyPage.source_entry}`,
    );
  }
  for (const eagerRouteEntry of inventory.eager_route_entries) {
    assert.equal(
      mappedWebSources.has(eagerRouteEntry.source_entry),
      true,
      `unmapped eager route source ${eagerRouteEntry.symbol}: ${eagerRouteEntry.source_entry}`,
    );
  }
});

test("capability judgments bind the audited hashes of routed pages and route registrations", () => {
  const manifest = readJson("parity-manifest.v2.json");
  const inventory = readJson("web-route-inventory.v2.json");
  const auditedSources = new Map(
    inventory.audited_sources.map((source) => [source.source_entry, source]),
  );
  const routes = new Map(
    inventory.production_routes.map((route) => [route.route_key, route]),
  );

  for (const capability of manifest.capabilities) {
    assert.equal(
      Array.isArray(capability.audited_web_sources),
      true,
      capability.id,
    );
    assert.deepEqual(
      capability.judgment.input.audited_web_sources,
      capability.audited_web_sources,
      capability.id,
    );
    assert.deepEqual(
      capability.judgment.input.web_production_dependencies ?? [],
      capability.web_production_dependencies,
      capability.id,
    );
    const capabilitySources = new Map(
      capability.audited_web_sources.map((source) => [
        source.source_entry,
        source,
      ]),
    );
    for (const source of capability.audited_web_sources) {
      assert.match(source.sha256, /^sha256:[0-9a-f]{64}$/u, capability.id);
      assert.deepEqual(
        source,
        auditedSources.get(source.source_entry),
        capability.id,
      );
    }
    for (const sourceEntry of capability.production_entries.web) {
      if (sourceEntry.startsWith("not_applicable:")) {
        continue;
      }
      assert.equal(
        capabilitySources.has(sourceEntry),
        true,
        `${capability.id}: unaudited Web source ${sourceEntry}`,
      );
    }
    for (const routeId of capability.web_route_registration_ids) {
      const registrationSource = routes.get(routeId)?.registration_source;
      assert.equal(
        typeof registrationSource,
        "string",
        `${capability.id}: ${routeId}`,
      );
      assert.equal(
        capabilitySources.has(registrationSource),
        true,
        `${capability.id}: unaudited registration source ${registrationSource}`,
      );
    }
  }
});

test("reviewed Web production dependencies bind reachable paths and audited SHA-256 sources", () => {
  const manifest = readJson("parity-manifest.v2.json");
  const inventory = readJson("web-route-inventory.v2.json");
  const inventoryEdges = new Set(
    inventory.production_dependency_edges.map((edge) => JSON.stringify(edge)),
  );
  const communities = manifest.capabilities.find(
    (capability) => capability.id === "project-project-communities",
  );

  assert.ok(communities);
  assert.deepEqual(
    communities.web_production_dependencies.map(
      ({ routed_source_entry, source_entry }) => ({
        routed_source_entry,
        source_entry,
      }),
    ),
    [
      {
        routed_source_entry:
          "web/src/pages/project/CommunitiesList.tsx",
        source_entry: "web/src/pages/project/communities/index.tsx",
      },
      {
        routed_source_entry:
          "web/src/pages/project/CommunitiesList.tsx",
        source_entry: "web/src/components/tasks/TaskList.tsx",
      },
    ],
  );

  const auditedByEntry = new Map(
    communities.audited_web_sources.map((source) => [
      source.source_entry,
      source,
    ]),
  );
  for (const dependency of communities.web_production_dependencies) {
    assert.equal(dependency.dependency_path.length > 0, true);
    assert.equal(
      dependency.dependency_path[0].from_source_entry,
      dependency.routed_source_entry,
    );
    assert.equal(
      dependency.dependency_path.at(-1).to_source_entry,
      dependency.source_entry,
    );
    for (const edge of dependency.dependency_path) {
      assert.equal(inventoryEdges.has(JSON.stringify(edge)), true);
    }
    assert.equal(
      communities.production_entries.web.includes(dependency.source_entry),
      true,
    );
    const auditedSource = auditedByEntry.get(dependency.source_entry);
    assert.ok(auditedSource);
    assert.equal(
      auditedSource.roles.includes("production_dependency"),
      true,
    );
    assert.match(auditedSource.sha256, /^sha256:[0-9a-f]{64}$/u);
  }

  const nativeOnlyCapability = manifest.capabilities.find(
    (capability) => capability.id === "application-encrypted-vault",
  );
  assert.ok(nativeOnlyCapability);
  assert.deepEqual(nativeOnlyCapability.web_production_dependencies, []);
});

test("manifest source entries and pinned revisions resolve in the audited repository", () => {
  const manifest = readJson("parity-manifest.v2.json");
  const repositoryRoot = new URL("../../../../../", contractRoot);

  assert.match(manifest.references.audit_revision, /^[0-9a-f]{40}$/);
  assert.equal(
    manifest.references.web_revision,
    manifest.references.audit_revision,
  );
  assert.equal(
    manifest.references.desktop_revision,
    manifest.references.audit_revision,
  );

  for (const capability of manifest.capabilities) {
    for (const [surfaceName, entries] of Object.entries(
      capability.production_entries,
    )) {
      for (const entry of entries) {
        const sourceEntry = surfaceName === "web" ? entry : entry.path;
        if (
          surfaceName === "web" &&
          (sourceEntry.startsWith("planned:") ||
            sourceEntry.startsWith("not_applicable:"))
        ) {
          continue;
        }
        assert.equal(
          existsSync(new URL(sourceEntry, repositoryRoot)),
          true,
          `${capability.id}: ${sourceEntry}`,
        );
      }
    }
  }
});

test("manifest generator consumes reviewed judgments and supports a drift-only check mode", () => {
  assert.match(generatorSource, /--check/u);
  assert.match(generatorSource, /--judgments/u);
  assert.match(generatorSource, /--output/u);
  assert.doesNotMatch(generatorSource, /verdict:\s*['"]accepted['"]/u);
  assert.doesNotMatch(generatorSource, /writeFileSync\(\s*judgmentsPath/u);
});

test("known production API contracts and native release actions stay source-accurate", () => {
  const manifest = readJson("parity-manifest.v2.json");
  const overview = manifest.capabilities.find(
    (capability) => capability.id === "tenant-tenant-overview",
  );
  const analytics = manifest.capabilities.find(
    (capability) => capability.id === "tenant-tenant-analytics",
  );
  const release = manifest.capabilities.find(
    (capability) => capability.id === "signed-update-and-release-boundary",
  );

  assert.ok(overview);
  assert.ok(analytics);
  assert.ok(release);
  assert.equal(
    overview.api_contracts.find((contract) => contract.surface === "web")?.path,
    "/api/v1/tenants/{tenant_id}/stats",
  );
  assert.equal(
    overview.surfaces.desktop_cloud.implementation_status,
    "missing",
  );
  assert.equal(overview.surfaces.desktop_cloud.authority, "none");
  assert.deepEqual(
    overview.api_contracts
      .filter((contract) => contract.surface === "desktop_cloud")
      .map(({ method, authority }) => ({ method, authority })),
    [{ method: "NONE", authority: "none" }],
  );
  assert.equal(
    analytics.api_contracts.find((contract) => contract.surface === "web")
      ?.path,
    "/api/v1/tenants/{tenant_id}/analytics",
  );
  for (const surfaceName of ["desktop_cloud", "desktop_local", "native_only"]) {
    assert.equal(
      release.surfaces[surfaceName].allowed_actions.includes("rollback"),
      false,
      surfaceName,
    );
  }
  assert.equal(release.surfaces.desktop_cloud.implementation_status, "partial");
  assert.equal(release.surfaces.desktop_local.implementation_status, "partial");
});

test("missing Desktop surfaces never claim a fabricated production authority", () => {
  const manifest = readJson("parity-manifest.v2.json");

  for (const capability of manifest.capabilities) {
    for (const surfaceName of ["desktop_cloud", "desktop_local"]) {
      const surface = capability.surfaces[surfaceName];
      if (surface.authority !== "none") continue;

      assert.deepEqual(
        surface.allowed_actions,
        [],
        `${capability.id}.${surfaceName}`,
      );
      const contracts = capability.api_contracts.filter(
        (contract) => contract.surface === surfaceName,
      );
      assert.equal(
        contracts.length > 0,
        true,
        `${capability.id}.${surfaceName}`,
      );
      for (const contract of contracts) {
        assert.equal(
          contract.method,
          "NONE",
          `${capability.id}.${surfaceName}`,
        );
        assert.equal(
          contract.authority,
          "none",
          `${capability.id}.${surfaceName}`,
        );
        assert.match(
          contract.path,
          /^not_applicable:/u,
          `${capability.id}.${surfaceName}`,
        );
      }
    }
  }
});

test("governance and runtime capabilities preserve audited Web actions and enforcement state", () => {
  const manifest = readJson("parity-manifest.v2.json");
  const byId = new Map(
    manifest.capabilities.map((capability) => [capability.id, capability]),
  );

  const expectedWebActions = {
    "tenant-tenant-instance-templates": [
      "view",
      "list",
      "list-items",
      "create",
      "delete",
      "publish",
      "clone",
      "deploy-from-template",
    ],
    "tenant-tenant-genes": [
      "view",
      "list",
      "create",
      "update",
      "delete",
      "publish",
      "unpublish",
      "install",
      "rate",
      "list-reviews",
      "create-review",
      "delete-own-review",
      "inspect-genome",
      "inspect-evolution",
    ],
    "tenant-tenant-users": [
      "view",
      "list",
      "invite",
      "inspect-pending-invitation-count",
      "change-role",
      "remove-member",
    ],
    "tenant-tenant-events": [
      "view",
      "list",
      "filter",
      "paginate",
      "retry-load",
    ],
    "tenant-tenant-trust-policies": ["view", "list", "create", "revoke"],
    "tenant-tenant-decision-records": [
      "view",
      "list",
      "filter",
      "inspect",
      "resolve-approval",
    ],
    "tenant-tenant-org-settings": [
      "view",
      "inspect-stats",
      "navigate-tenant-settings",
      "navigate-members",
      "navigate-clusters",
      "list-clusters",
      "inspect-cluster-status",
      "navigate-audit",
      "manage-registries",
      "inspect-smtp",
      "update-smtp",
      "delete-smtp",
      "test-smtp",
      "manage-gene-policies",
    ],
  };
  for (const [capabilityId, actions] of Object.entries(expectedWebActions)) {
    assert.deepEqual(
      byId.get(capabilityId)?.surfaces.web.allowed_actions,
      actions,
      capabilityId,
    );
  }
  assert.equal(
    byId.get("tenant-tenant-runtimes")?.surfaces.web.reason_code,
    "runtime_pool_authentication_admin_and_tenant_scope_not_enforced",
  );
  assert.equal(
    byId.get("tenant-tenant-pool")?.surfaces.web.reason_code,
    "runtime_pool_authentication_admin_and_tenant_scope_not_enforced",
  );
  assert.equal(
    byId.get("tenant-tenant-instances")?.surfaces.web.reason_code,
    "runtime_instance_contract_and_authorization_incomplete",
  );
  assert.equal(
    byId.get("tenant-tenant-org-settings")?.surfaces.web.reason_code,
    "organization_registry_gene_policy_authorization_and_cluster_route_tenant_scope_incomplete",
  );
  assert.deepEqual(byId.get("tenant-tenant-pool")?.permission_requirements, [
    {
      surface: "web",
      actions: [
        "view",
        "refresh",
        "toggle-auto-refresh",
        "list-instances",
        "search-current-page",
        "filter-by-tier",
        "paginate-instances",
        "pause-instance",
        "resume-instance",
        "terminate-instance",
        "retry-list-instances",
        "inspect-pool-status",
        "inspect-resource-usage",
      ],
      authentication: "authenticated",
      authorization: ["global_admin"],
      enforcement: "missing",
      feature_gate: null,
    },
  ]);
  assert.deepEqual(byId.get("tenant-tenant-pool")?.scope, [
    "tenant",
    "global",
  ]);
  assert.deepEqual(byId.get("tenant-tenant-runtimes")?.scope, [
    "tenant",
    "global",
  ]);
  const instanceMutationRequirement = byId
    .get("tenant-tenant-instances")
    ?.permission_requirements.find((requirement) =>
      requirement.actions.includes("create"),
    );
  assert.deepEqual(instanceMutationRequirement?.authorization, [
    "tenant_admin",
  ]);
  assert.equal(instanceMutationRequirement?.enforcement, "missing");

  const pendingInvitationRequirement = byId
    .get("tenant-tenant-users")
    ?.permission_requirements.find((requirement) =>
      requirement.actions.includes("inspect-pending-invitation-count"),
    );
  assert.deepEqual(pendingInvitationRequirement?.authorization, [
    "tenant_admin",
  ]);
  assert.equal(pendingInvitationRequirement?.enforcement, "enforced");

  const smtpReadRequirement = byId
    .get("tenant-tenant-org-settings")
    ?.permission_requirements.find((requirement) =>
      requirement.actions.includes("inspect-smtp"),
    );
  const smtpMutationRequirement = byId
    .get("tenant-tenant-org-settings")
    ?.permission_requirements.find((requirement) =>
      requirement.actions.includes("update-smtp"),
    );
  assert.deepEqual(smtpReadRequirement?.authorization, ["tenant_member"]);
  assert.deepEqual(smtpMutationRequirement?.authorization, ["tenant_admin"]);
  assert.equal(smtpReadRequirement?.enforcement, "enforced");
  assert.equal(smtpMutationRequirement?.enforcement, "enforced");

  for (const capability of manifest.capabilities) {
    for (const permission of capability.required_permissions) {
      assert.doesNotMatch(
        permission,
        /^(?:runtime|runtime-pool|instance|cluster|deploy|instance-template|gene|audit-log|event|dead-letter-queue|trust-policy|decision-record|billing|organization|tenant):(?:read|admin)$/u,
        capability.id,
      );
    }
  }
});

test("identity routes preserve their real multi-step authorities and per-surface actions", () => {
  const manifest = readJson("parity-manifest.v2.json");
  const byId = new Map(
    manifest.capabilities.map((capability) => [capability.id, capability]),
  );
  const auth = byId.get("authentication-and-account-entry");
  const oauth = byId.get("oauth-callback");
  const invitation = byId.get("invitation-acceptance");
  const profile = byId.get("user-profile");
  const tenantCreation = byId.get("tenant-creation");
  const orgSettings = byId.get("tenant-tenant-org-settings");

  assert.ok(auth);
  assert.ok(oauth);
  assert.ok(invitation);
  assert.ok(profile);
  assert.ok(tenantCreation);
  assert.ok(orgSettings);
  assert.deepEqual(auth.surfaces.web.allowed_actions, ["sign-in"]);
  assert.deepEqual(auth.surfaces.desktop_local.allowed_actions, [
    "start-local-session",
    "resume-local-session",
  ]);
  assert.deepEqual(
    auth.api_contracts
      .filter((contract) => contract.surface === "desktop_local")
      .map(({ method, path }) => `${method} ${path}`),
    [
      "POST /api/v1/auth/local-session",
      "POST /api/v1/auth/local-session/resume",
      "GET /api/v1/auth/me",
    ],
  );
  assert.equal(oauth.surfaces.web.availability, "unavailable");
  assert.deepEqual(
    invitation.api_contracts
      .filter((contract) => contract.surface === "web")
      .map(({ method, path }) => `${method} ${path}`),
    [
      "GET /api/v1/invitations/verify/{token}",
      "POST /api/v1/invitations/accept/{token}",
    ],
  );
  assert.deepEqual(
    profile.api_contracts
      .filter((contract) => contract.surface === "desktop_local")
      .map(({ method, path }) => `${method} ${path}`),
    ["GET /api/v1/auth/me"],
  );
  assert.equal(
    tenantCreation.production_entries.web.includes(
      "web/src/components/common/OrgSetupGuard.tsx",
    ),
    false,
  );
  assert.equal(
    orgSettings.production_entries.web.includes(
      "web/src/components/common/OrgSetupGuard.tsx",
    ),
    true,
  );
});

test("project capabilities preserve audited Local authority and per-surface action subsets", () => {
  const manifest = readJson("parity-manifest.v2.json");
  const byId = new Map(
    manifest.capabilities.map((capability) => [capability.id, capability]),
  );
  const workspaces = byId.get("project-project-workspaces");
  const blackboard = byId.get("project-blackboard-dynamic-project-blackboard");
  const search = byId.get("project-project-search");
  const cron = byId.get("project-project-cron-jobs");

  assert.ok(workspaces);
  assert.ok(blackboard);
  assert.ok(search);
  assert.ok(cron);
  assert.equal(
    workspaces.surfaces.desktop_local.implementation_status,
    "partial",
  );
  assert.equal(
    workspaces.surfaces.desktop_local.reason_code,
    "local_workspace_lifecycle_partial",
  );
  assert.deepEqual(workspaces.surfaces.desktop_local.allowed_actions, [
    "view",
    "list",
    "create",
    "open-blackboard",
  ]);
  assert.equal(
    blackboard.surfaces.desktop_local.implementation_status,
    "partial",
  );
  assert.equal(
    blackboard.surfaces.desktop_local.reason_code,
    "local_workspace_plan_read_only",
  );
  assert.deepEqual(blackboard.surfaces.desktop_local.allowed_actions, [
    "view",
    "select-workspace",
    "review-plan",
  ]);
  assert.deepEqual(search.surfaces.desktop_cloud.allowed_actions, [
    "view",
    "search",
    "filter",
    "semantic-search",
    "faceted-search",
    "temporal-search",
    "graph-traversal",
    "community-search",
    "copy-result-id",
  ]);
  assert.deepEqual(search.surfaces.desktop_local.allowed_actions, [
    "view",
    "search",
    "filter",
    "faceted-search",
    "temporal-search",
    "copy-result-id",
  ]);
  assert.deepEqual(cron.surfaces.web.allowed_actions, [
    "view",
    "list",
    "create",
    "update",
    "delete",
    "toggle",
    "run-now",
    "view-history",
  ]);
  assert.deepEqual(cron.surfaces.desktop_local.allowed_actions, [
    "view",
    "list",
    "view-history",
  ]);
});

test("agent ecosystem capabilities do not overstate missing controls or Local authorities", () => {
  const manifest = readJson("parity-manifest.v2.json");
  const byId = new Map(
    manifest.capabilities.map((capability) => [capability.id, capability]),
  );
  const workspace = byId.get("agent-workspace-tenant-agent-workspace");
  const configuration = byId.get("tenant-tenant-agent-configuration");
  const bindings = byId.get("tenant-tenant-agent-bindings");
  const evolution = byId.get("tenant-tenant-evolution");
  const acp = byId.get("tenant-tenant-acp");
  const templates = byId.get("tenant-tenant-templates");
  const providers = byId.get("tenant-tenant-providers");

  assert.ok(workspace);
  assert.ok(configuration);
  assert.ok(bindings);
  assert.ok(evolution);
  assert.ok(acp);
  assert.ok(templates);
  assert.ok(providers);
  assert.equal(workspace.surfaces.web.implementation_status, "partial");
  assert.equal(
    workspace.surfaces.web.reason_code,
    "web_subagent_control_handler_missing",
  );
  assert.deepEqual(workspace.surfaces.web.allowed_actions, [
    "view",
    "send-message",
    "stop-session",
    "manage-roster",
  ]);
  assert.deepEqual(workspace.surfaces.desktop_cloud.allowed_actions, [
    "view",
    "send-message",
    "stop-session",
  ]);
  assert.deepEqual(workspace.surfaces.desktop_local.allowed_actions, [
    "view",
    "send-message",
    "stop-session",
  ]);
  assert.deepEqual(configuration.surfaces.web.allowed_actions, [
    "view-config",
    "update-config",
    "view-hook-catalog",
    "list-runs",
    "filter-runs",
    "inspect-run",
    "inspect-trace",
    "refresh",
    "retry",
  ]);
  for (const capability of [configuration, bindings]) {
    for (const surfaceName of ["desktop_cloud", "desktop_local"]) {
      assert.equal(
        capability.surfaces[surfaceName].implementation_status,
        "missing",
      );
      assert.equal(capability.surfaces[surfaceName].authority, "none");
      assert.deepEqual(capability.surfaces[surfaceName].allowed_actions, []);
    }
  }
  assert.equal(evolution.surfaces.desktop_local.disposition, "native_equivalent");
  assert.equal(evolution.surfaces.desktop_local.implementation_status, "partial");
  assert.equal(evolution.surfaces.desktop_local.availability, "unavailable");
  assert.equal(
    evolution.surfaces.desktop_local.reason_code,
    "local_skill_evolution_not_applicable",
  );
  assert.equal(
    evolution.surfaces.desktop_local.intentional_deviation.includes(
      "legacy contract mismatch",
    ),
    true,
  );
  assert.equal(acp.surfaces.desktop_local.disposition, "not_applicable");
  assert.equal(
    acp.surfaces.desktop_local.reason_code,
    "local_external_acp_not_applicable",
  );
  assert.equal(templates.surfaces.desktop_local.availability, "unavailable");
  assert.equal(
    templates.surfaces.desktop_local.reason_code,
    "local_subagent_registry_unavailable",
  );
  for (const surfaceName of ["web", "desktop_cloud", "desktop_local"]) {
    assert.equal(
      providers.surfaces[surfaceName].allowed_actions.includes("oauth-connect"),
      false,
      surfaceName,
    );
  }
  assert.deepEqual(
    providers.permission_requirements.find(
      (requirement) =>
        requirement.surface === "web" &&
        requirement.actions.includes("view-tenant-assignment"),
    ),
    {
      surface: "web",
      actions: ["view-tenant-assignment"],
      authentication: "authenticated",
      authorization: ["tenant_member"],
      enforcement: "enforced",
      feature_gate: null,
    },
  );
  assert.deepEqual(
    providers.permission_requirements.find(
      (requirement) =>
        requirement.surface === "web" &&
        requirement.actions.includes("manage-tenant-assignment"),
    )?.authorization,
    ["global_admin"],
  );
});
