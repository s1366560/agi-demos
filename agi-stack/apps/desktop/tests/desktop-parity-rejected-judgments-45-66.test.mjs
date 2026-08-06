import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const contractRoot = new URL(
  "../contracts/desktop-web-parity/",
  import.meta.url,
);

function readCapability(fragmentName, capabilityId) {
  const fragment = JSON.parse(
    readFileSync(new URL(fragmentName, contractRoot), "utf8"),
  );
  const capability = fragment.capabilities.find(
    (candidate) => candidate.id === capabilityId,
  );
  assert.ok(capability, `missing capability ${capabilityId}`);
  return capability;
}

function contractKeys(capability, surface) {
  return capability.api_contracts
    .filter((contract) => contract.surface === surface)
    .map((contract) => `${contract.method} ${contract.path}`);
}

function requirementsForAction(capability, surface, action) {
  return capability.permission_requirements.filter(
    (requirement) =>
      requirement.surface === surface &&
      requirement.actions.includes(action),
  );
}

function assertActionRole(capability, surface, action, role) {
  assert.ok(
    requirementsForAction(capability, surface, action).some((requirement) =>
      requirement.authorization.includes(role),
    ),
    `${capability.id} ${surface}.${action} missing ${role}`,
  );
}

test("Project Channels follows ProjectChannelsRedirect into the PluginHub production flow", () => {
  const capability = readCapability(
    "parity-capability-definitions.19-project-knowledge-configuration.v2.json",
    "project-project-channels",
  );
  const expectedWebActions = [
    "view",
    "list",
    "install",
    "enable",
    "disable",
    "uninstall",
    "reload",
    "view-channel-catalog",
    "view-channel-schema",
    "view-config-schema",
    "view-config",
    "update-config",
    "list-channel-configs",
    "create-channel-config",
    "update-channel-config",
    "delete-channel-config",
    "test-channel-config",
  ];

  assert.deepEqual(capability.actions, expectedWebActions);
  assert.deepEqual(capability.web_actions, expectedWebActions);
  assert.deepEqual(capability.reviewed_additional_web_entries, [
    {
      source_entry: "web/src/pages/tenant/PluginHub.tsx",
      source_owner_capability_id: "tenant-tenant-plugins",
      route_registration_id:
        "production-route-path-tenant-tenantid-project-projectid-channels",
      relationship: "canonical_redirect_target",
    },
  ]);
  assert.deepEqual(contractKeys(capability, "web"), [
    "GET /api/v1/channels/tenants/{tenant_id}/plugins",
    "GET /api/v1/channels/tenants/{tenant_id}/plugins/channel-catalog",
    "GET /api/v1/channels/tenants/{tenant_id}/plugins/channel-catalog/{channel_type}/schema",
    "POST /api/v1/channels/tenants/{tenant_id}/plugins/install",
    "POST /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/enable",
    "POST /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/disable",
    "POST /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/uninstall",
    "POST /api/v1/channels/tenants/{tenant_id}/plugins/reload",
    "GET /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/config-schema",
    "GET /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/config",
    "PUT /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/config",
    "GET /api/v1/channels/projects/{project_id}/configs",
    "POST /api/v1/channels/projects/{project_id}/configs",
    "PUT /api/v1/channels/configs/{config_id}",
    "DELETE /api/v1/channels/configs/{config_id}",
    "POST /api/v1/channels/configs/{config_id}/test",
  ]);

  for (const unusedContract of [
    "GET /api/v1/channels/configs/{config_id}",
    "GET /api/v1/channels/configs/{config_id}/status",
    "GET /api/v1/channels/projects/{project_id}/observability/summary",
  ]) {
    assert.equal(
      contractKeys(capability, "web").includes(unusedContract),
      false,
      `Web must not claim unused ${unusedContract}`,
    );
  }

  for (const action of [
    "view",
    "list",
    "view-channel-catalog",
    "view-channel-schema",
    "view-config-schema",
    "view-config",
  ]) {
    assertActionRole(capability, "web", action, "tenant_member");
  }
  for (const action of [
    "install",
    "enable",
    "disable",
    "uninstall",
    "reload",
    "update-config",
  ]) {
    assertActionRole(capability, "web", action, "tenant_admin");
    assertActionRole(capability, "web", action, "tenant_owner");
  }
  for (const action of ["list-channel-configs", "test-channel-config"]) {
    assertActionRole(capability, "web", action, "project_member");
  }
  for (const action of [
    "create-channel-config",
    "update-channel-config",
    "delete-channel-config",
  ]) {
    assertActionRole(capability, "web", action, "project_admin");
    assertActionRole(capability, "web", action, "project_owner");
  }

  assert.match(capability.judgment_rationale, /ProjectChannelsRedirect/u);
  assert.match(capability.judgment_rationale, /PluginHub/u);
});

test("Project Channels Cloud contract matches the native connection dialog", () => {
  const capability = readCapability(
    "parity-capability-definitions.19-project-knowledge-configuration.v2.json",
    "project-project-channels",
  );
  const expectedCloudActions = [
    "view",
    "view-channel-catalog",
    "view-channel-schema",
    "list-channel-configs",
    "create-channel-config",
    "update-channel-config",
    "delete-channel-config",
    "test-channel-config",
  ];

  assert.deepEqual(capability.cloud_actions, expectedCloudActions);
  assert.deepEqual(contractKeys(capability, "desktop_cloud"), [
    "GET /api/v1/channels/tenants/{tenant_id}/plugins/channel-catalog",
    "GET /api/v1/channels/tenants/{tenant_id}/plugins/channel-catalog/{channel_type}/schema",
    "GET /api/v1/channels/projects/{project_id}/configs",
    "POST /api/v1/channels/projects/{project_id}/configs",
    "PUT /api/v1/channels/configs/{config_id}",
    "DELETE /api/v1/channels/configs/{config_id}",
    "POST /api/v1/channels/configs/{config_id}/test",
  ]);

  for (const entry of [
    "agi-stack/apps/desktop/src/api/client.ts",
    "agi-stack/apps/desktop/src/features/settings/ChannelConnectionsDialog.tsx",
    "agi-stack/apps/desktop/src/features/settings/useChannelConnectionManagement.ts",
    "agi-stack/apps/desktop/src/features/settings/SettingsManagementDialogs.tsx",
    "agi-stack/apps/desktop/src/features/settings/SettingsWindow.tsx",
  ]) {
    assert.ok(capability.cloud_entries.includes(entry), `missing ${entry}`);
  }

  for (const action of expectedCloudActions) {
    const requirements = requirementsForAction(
      capability,
      "desktop_cloud",
      action,
    );
    assert.ok(requirements.length > 0, `missing Cloud permission for ${action}`);
    assert.ok(
      requirements.some((requirement) =>
        requirement.authorization.some((role) =>
          ["tenant_admin", "tenant_owner"].includes(role),
        ),
      ),
      `${action} must retain the native admin-or-owner UI gate`,
    );
  }

  for (const action of [
    "view",
    "view-channel-catalog",
    "view-channel-schema",
    "list-channel-configs",
    "test-channel-config",
  ]) {
    assertActionRole(capability, "desktop_cloud", action, "project_member");
  }
  for (const action of [
    "create-channel-config",
    "update-channel-config",
    "delete-channel-config",
  ]) {
    assert.ok(
      requirementsForAction(capability, "desktop_cloud", action).some(
        (requirement) =>
          requirement.authorization.includes("project_admin") ||
          requirement.authorization.includes("project_owner"),
      ),
      `${action} must retain project mutation authority`,
    );
  }
});

test("Project Maintenance closes its production scope and endpoint mismatches", () => {
  const capability = readCapability(
    "parity-capability-definitions.19-project-knowledge-configuration.v2.json",
    "project-project-maintenance",
  );

  assert.equal(capability.cloud_status, "unavailable");
  assert.equal(
    capability.cloud_reason_code,
    "project_maintenance_authority_unavailable",
  );
  assert.deepEqual(capability.cloud_actions, []);
  assert.deepEqual(contractKeys(capability, "desktop_cloud"), [
    "GET /api/v1/maintenance/status?project_id={project_id}",
    "GET /api/v1/data/stats?project_id={project_id}",
    "GET /api/v1/maintenance/embeddings/status?project_id={project_id}",
    "POST /api/v1/maintenance/incremental-refresh",
    "POST /api/v1/maintenance/deduplicate",
    "POST /api/v1/maintenance/invalidate-edges",
    "POST /api/v1/maintenance/communities/rebuild",
    "POST /api/v1/maintenance/embeddings/rebuild?project_id={project_id}",
  ]);
  assert.equal(capability.local_status, "unavailable");
  assert.equal(capability.local_authority, "none");
  assert.equal(
    capability.local_reason_code,
    "local_project_maintenance_authority_unavailable",
  );
  assert.match(capability.judgment_rationale, /auth\/me/u);
  assert.match(capability.judgment_rationale, /user_id/u);
  assert.match(capability.judgment_rationale, /userPayload\.id/u);
  assert.match(capability.judgment_rationale, /refresh\/incremental/u);
  assert.match(capability.judgment_rationale, /graph\/communities\/rebuild/u);
});

test("Project Cron Jobs separates effective Web reads from unavailable mutations", () => {
  const capability = readCapability(
    "parity-capability-definitions.20-project-automation-settings.v2.json",
    "project-project-cron-jobs",
  );
  const allActions = [
    "view",
    "list",
    "create",
    "update",
    "delete",
    "toggle",
    "run-now",
    "view-history",
    "inspect-capabilities",
  ];
  const expectedWebActions = ["view", "list", "view-history"];
  const readActions = [
    "view",
    "list",
    "view-history",
    "inspect-capabilities",
  ];
  const mutationActions = [
    "create",
    "update",
    "delete",
    "toggle",
    "run-now",
  ];

  assert.deepEqual(capability.actions, allActions);
  assert.equal(capability.web_status, "partial");
  assert.equal(
    capability.web_reason_code,
    "web_cron_mutation_and_run_authority_unavailable",
  );
  assert.deepEqual(capability.web_actions, expectedWebActions);
  assert.equal(
    contractKeys(capability, "web").includes(
      "GET /api/v1/projects/{project_id}/cron-jobs/capabilities",
    ),
    false,
    "Web must not claim the unconsumed Cron capabilities endpoint",
  );
  assert.equal(
    requirementsForAction(
      capability,
      "web",
      "inspect-capabilities",
    ).length,
    0,
    "Web must not claim the unconsumed inspect-capabilities action",
  );
  for (const action of expectedWebActions) {
    const requirements = requirementsForAction(capability, "web", action);
    assert.equal(requirements.length, 1, `unexpected Web permission rows for ${action}`);
    assert.deepEqual(requirements[0].authorization, ["project_member"]);
    assert.equal(
      requirements[0].feature_gate,
      null,
      `Web ${action} must retain project membership enforcement`,
    );
  }
  for (const action of mutationActions) {
    assert.equal(
      requirementsForAction(capability, "web", action).length,
      0,
      `Web must not claim unavailable ${action} authority`,
    );
  }

  for (const surface of ["desktop_cloud", "desktop_local"]) {
    assert.ok(
      contractKeys(capability, surface).includes(
        "GET /api/v1/projects/{project_id}/cron-jobs/capabilities",
      ),
      `${surface} must retain its structured Cron capability authority`,
    );
  }

  for (const action of readActions) {
    const requirements = requirementsForAction(
      capability,
      "desktop_cloud",
      action,
    );
    assert.ok(requirements.length > 0, `missing Cloud permission for ${action}`);
    assert.ok(
      requirements.some(
        (requirement) =>
          requirement.authorization.includes("project_member") &&
          requirement.feature_gate === null,
      ),
    );
  }
  for (const action of mutationActions) {
    const requirements = requirementsForAction(
      capability,
      "desktop_cloud",
      action,
    );
    assert.ok(requirements.length > 0, `missing Cloud permission for ${action}`);
    assert.ok(
      requirements.some(
        (requirement) =>
          requirement.authorization.includes("project_member") &&
          requirement.feature_gate === "cron_capabilities_action_allowed",
      ),
    );
  }

  assert.deepEqual(capability.local_actions, [
    "view",
    "list",
    "view-history",
    "inspect-capabilities",
    "create",
    "update",
    "delete",
    "toggle",
    "run-now",
  ]);
  assert.equal(
    capability.local_reason_code,
    "local_automation_projection_partial",
  );
  for (const action of capability.local_actions) {
    const requirements = requirementsForAction(
      capability,
      "desktop_local",
      action,
    );
    assert.equal(requirements.length, 1, `unexpected Local permission rows for ${action}`);
    assert.deepEqual(requirements[0].authorization, []);
    assert.equal(
      requirements[0].feature_gate,
      "local_automation_capabilities",
    );
  }
  assert.match(capability.judgment_rationale, /schema_version 2/u);
  assert.match(capability.judgment_rationale, /canonical project route/u);
  assert.match(capability.judgment_rationale, /Electron evidence/u);
});

test("Project Settings records only the routed page sandbox operations and authorities", () => {
  const capability = readCapability(
    "parity-capability-definitions.20-project-automation-settings.v2.json",
    "project-project-settings",
  );
  const expectedActions = [
    "view",
    "update",
    "delete",
    "inspect-sandbox",
    "inspect-sandbox-stats",
    "restart-sandbox",
    "terminate-sandbox",
  ];

  assert.deepEqual(capability.actions, expectedActions);
  assert.deepEqual(capability.web_actions, expectedActions);
  assert.deepEqual(contractKeys(capability, "web"), [
    "GET /api/v1/projects/{project_id}",
    "PUT /api/v1/projects/{project_id}",
    "DELETE /api/v1/projects/{project_id}",
    "GET /api/v1/projects/{project_id}/sandbox",
    "GET /api/v1/projects/{project_id}/sandbox/stats",
    "POST /api/v1/projects/{project_id}/sandbox/restart",
    "DELETE /api/v1/projects/{project_id}/sandbox",
  ]);
  assert.deepEqual(contractKeys(capability, "desktop_cloud"), [
    "GET /api/v1/projects/{project_id}",
    "PATCH /api/v1/projects/{project_id}",
    "DELETE /api/v1/projects/{project_id}",
    "GET /api/v1/projects/{project_id}/sandbox",
    "GET /api/v1/projects/{project_id}/sandbox/stats",
    "POST /api/v1/projects/{project_id}/sandbox/restart",
    "DELETE /api/v1/projects/{project_id}/sandbox",
  ]);
  assert.equal(capability.cloud_status, "unavailable");
  assert.equal(
    capability.cloud_reason_code,
    "project_settings_authority_unavailable",
  );
  assert.deepEqual(capability.cloud_actions, []);
  assert.equal(capability.local_status, "unavailable");
  assert.equal(capability.local_authority, "none");
  assert.equal(
    capability.local_reason_code,
    "local_project_settings_authority_unavailable",
  );
  assert.match(capability.judgment_rationale, /auth\/me/u);
  assert.match(capability.judgment_rationale, /user_id/u);
  assert.match(capability.judgment_rationale, /userPayload\.id/u);
  assert.match(capability.judgment_rationale, /PATCH/u);
  assert.match(capability.judgment_rationale, /PUT/u);

  for (const action of [
    "view",
    "inspect-sandbox",
    "inspect-sandbox-stats",
  ]) {
    assertActionRole(capability, "web", action, "project_member");
  }
  for (const action of [
    "update",
    "restart-sandbox",
    "terminate-sandbox",
  ]) {
    assertActionRole(capability, "web", action, "project_admin");
    assertActionRole(capability, "web", action, "project_owner");
  }
  assertActionRole(capability, "web", "delete", "project_owner");

  for (const removedAction of [
    "configure-sandbox",
    "open-terminal",
    "open-desktop",
  ]) {
    assert.equal(capability.actions.includes(removedAction), false);
  }
  for (const removedPath of [
    "/api/v1/projects/{project_id}/sandbox/health",
    "/api/v1/projects/{project_id}/sandbox/sync",
    "/api/v1/projects/{project_id}/sandbox/terminal",
    "/api/v1/projects/{project_id}/sandbox/desktop",
    "/api/v1/projects/{project_id}/sandbox/execute",
    "/api/v1/projects/{project_id}/sandbox/proxy-auth-cookie",
  ]) {
    assert.equal(
      capability.api_contracts.some((contract) =>
        contract.path.startsWith(removedPath),
      ),
      false,
      `Settings must not claim ${removedPath}`,
    );
  }
});

test("User Profile records the observed native route while Snapshot v4 fails closed", () => {
  const capability = readCapability(
    "parity-capability-definitions.23-identity-profile.v2.json",
    "user-profile",
  );

  assert.deepEqual(contractKeys(capability, "web"), [
    "GET /api/v1/auth/me",
    "PUT /api/v1/users/me",
    "POST /api/v1/auth/force-change-password",
  ]);
  assert.deepEqual(contractKeys(capability, "desktop_cloud"), [
    "GET /api/v1/auth/me",
    "PUT /api/v1/users/me",
    "POST /api/v1/auth/force-change-password",
  ]);
  assert.deepEqual(contractKeys(capability, "desktop_local"), [
    "GET /api/v1/auth/me",
  ]);
  assert.equal(
    contractKeys(capability, "web").includes("GET /api/v1/users/me"),
    false,
  );
  assert.equal(capability.cloud_status, "unavailable");
  assert.equal(
    capability.cloud_reason_code,
    "capability_authority_revision_unavailable",
  );
  assert.deepEqual(capability.cloud_actions, [
    "view",
    "update",
    "change-language",
    "change-password",
  ]);
  assert.equal(capability.local_status, "unavailable");
  assert.equal(
    capability.local_reason_code,
    "capability_authority_revision_unavailable",
  );
  assert.deepEqual(capability.local_actions, ["view"]);
  for (const entry of [
    "agi-stack/apps/desktop/src/App.tsx",
    "agi-stack/apps/desktop/src/features/runtime/capabilitySnapshot.ts",
    "agi-stack/apps/desktop/src/features/runtime/workbenchCapabilityClient.ts",
    "agi-stack/apps/desktop/src/features/settings-routes/profileRouteClient.ts",
    "agi-stack/apps/desktop/src/features/settings-routes/profileRouteController.ts",
    "agi-stack/apps/desktop/src/features/settings-routes/profileRouteModule.ts",
    "agi-stack/apps/desktop/src/features/settings-routes/ProfileRoutePage.tsx",
    "agi-stack/apps/desktop/src/features/settings-routes/p2ThirdBatchCapabilityClient.ts",
    "agi-stack/apps/desktop/src/features/settings-routes/p2ThirdBatchRouteRuntime.ts",
  ]) {
    assert.ok(capability.cloud_entries.includes(entry), `missing Cloud ${entry}`);
    assert.ok(capability.local_entries.includes(entry), `missing Local ${entry}`);
  }
  assert.match(capability.judgment_rationale, /UserProfile/u);
  assert.match(capability.judgment_rationale, /useAuthStore/u);
  assert.match(capability.judgment_rationale, /authAPI\.(?:login|verifyToken)/u);
  assert.match(capability.judgment_rationale, /\/auth\/me/u);
  assert.match(capability.judgment_rationale, /\/users\/me/u);
  assert.match(capability.judgment_rationale, /profileRouteClient/u);
  assert.match(capability.judgment_rationale, /authority_revision/u);
});

test("declared Tenant Creation and Project Support loaders stay unavailable", () => {
  const cases = [
    {
      fragment:
        "parity-capability-definitions.23-identity-profile.v2.json",
      id: "tenant-creation",
      entries: [
        "agi-stack/apps/desktop/src/features/tenant-creation/tenantCreationCapability.ts",
        "agi-stack/apps/desktop/src/features/tenant-creation/tenantCreationClient.ts",
        "agi-stack/apps/desktop/src/features/tenant-creation/tenantCreationRouteModule.tsx",
      ],
    },
    {
      fragment:
        "parity-capability-definitions.24-native-product-auxiliary.v2.json",
      id: "project-support",
      entries: [
        "agi-stack/apps/desktop/src/features/project-support/projectSupportCapability.ts",
        "agi-stack/apps/desktop/src/features/project-support/projectSupportClient.ts",
        "agi-stack/apps/desktop/src/features/project-support/projectSupportController.ts",
        "agi-stack/apps/desktop/src/features/project-support/projectSupportRouteModule.tsx",
      ],
    },
  ];

  for (const { fragment, id, entries } of cases) {
    const capability = readCapability(fragment, id);
    assert.equal(capability.cloud_status, "unavailable", id);
    assert.equal(
      capability.cloud_reason_code,
      "renderer_capability_authority_unobserved",
      id,
    );
    assert.deepEqual(capability.cloud_actions, [], id);
    for (const entry of [
      "agi-stack/apps/desktop/src/App.tsx",
      "agi-stack/apps/desktop/src/features/navigation/desktopProductionRouteRegistry.ts",
      "agi-stack/apps/desktop/src/features/runtime/capabilitySnapshot.ts",
      "agi-stack/apps/desktop/src/features/runtime/workbenchCapabilityClient.ts",
      ...entries,
    ]) {
      assert.ok(capability.cloud_entries.includes(entry), `${id}: missing ${entry}`);
    }
    assert.match(capability.judgment_rationale, /declared renderer provenance/u);
  }
});

test("native vault status records Windows ACL source without claiming runtime proof", () => {
  const vault = readCapability(
    "parity-capability-definitions.25-native-boundaries.v2.json",
    "application-encrypted-vault",
  );
  const release = readCapability(
    "parity-capability-definitions.25-native-boundaries.v2.json",
    "signed-update-and-release-boundary",
  );

  assert.equal(vault.native_status, "partial");
  assert.equal(
    vault.native_reason_code,
    "windows_vault_acl_runtime_evidence_missing",
  );
  assert.ok(
    vault.native_entries.includes(
      "agi-stack/apps/desktop/sidecar/src/private_file_permissions.rs",
    ),
  );
  assert.match(vault.judgment_rationale, /protected current-user DACL/u);
  assert.match(vault.judgment_rationale, /Windows-only/u);
  assert.match(vault.judgment_rationale, /current-HEAD/u);
  assert.doesNotMatch(vault.judgment_rationale, /no-op/u);

  assert.equal(release.native_status, "partial");
  assert.equal(
    release.native_reason_code,
    "production_install_update_rollback_evidence_missing",
  );
  assert.match(release.judgment_rationale, /does not prove installation/u);
});

test("unimplemented backend-store and playbook routes remain planned", () => {
  for (const capabilityId of ["backend-stores", "project-playbooks"]) {
    const capability = readCapability(
      "parity-capability-definitions.24-native-product-auxiliary.v2.json",
      capabilityId,
    );
    assert.equal(capability.cloud_status, "planned", capabilityId);
    assert.equal(capability.local_status, "planned", capabilityId);
    assert.equal(
      capability.cloud_entries,
      undefined,
      `${capabilityId}: must not claim a native route entry`,
    );
  }
});

test("Not Found is an implemented renderer-owned route without service authority", () => {
  const capability = readCapability(
    "parity-capability-definitions.24-native-product-auxiliary.v2.json",
    "not-found",
  );
  const expectedEntries = [
    "agi-stack/apps/desktop/src/App.tsx",
    "agi-stack/apps/desktop/src/features/navigation/DesktopProductionRouter.tsx",
    "agi-stack/apps/desktop/src/features/navigation/desktopHashRouteHost.ts",
  ];

  assert.equal(capability.kind, "route_only");
  assert.deepEqual(capability.web_route_ids, []);
  assert.equal(capability.cloud_status, "implemented");
  assert.equal(capability.local_status, "implemented");
  assert.equal(capability.cloud_authority, "none");
  assert.equal(capability.local_authority, "none");
  assert.deepEqual(capability.cloud_entries, expectedEntries);
  assert.deepEqual(capability.local_entries, expectedEntries);
  assert.deepEqual(capability.cloud_actions, capability.actions);
  assert.deepEqual(capability.local_actions, capability.actions);
  for (const surface of ["desktop_cloud", "desktop_local"]) {
    assert.deepEqual(contractKeys(capability, surface), [
      "NONE not_applicable:routing/not-found",
    ]);
    assert.deepEqual(
      requirementsForAction(capability, surface, "restore-safe-route")[0]
        .authorization,
      [],
    );
  }
  assert.match(capability.judgment_rationale, /all non-empty hashes/u);
  assert.match(capability.judgment_rationale, /no service authority/u);
});
