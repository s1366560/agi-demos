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

test("Project Cron Jobs separates Web production actions from Desktop capability gates", () => {
  const capability = readCapability(
    "parity-capability-definitions.20-project-automation-settings.v2.json",
    "project-project-cron-jobs",
  );
  const expectedWebActions = [
    "view",
    "list",
    "create",
    "update",
    "delete",
    "toggle",
    "run-now",
    "view-history",
  ];
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

  assert.deepEqual(capability.actions, [
    ...expectedWebActions,
    "inspect-capabilities",
  ]);
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
      `Web ${action} must reflect backend project membership without a client capability gate`,
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
    "PUT /api/v1/projects/{project_id}",
    "DELETE /api/v1/projects/{project_id}",
    "GET /api/v1/projects/{project_id}/sandbox",
    "GET /api/v1/projects/{project_id}/sandbox/stats",
    "POST /api/v1/projects/{project_id}/sandbox/restart",
    "DELETE /api/v1/projects/{project_id}/sandbox",
  ]);

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

test("User Profile reads the authenticated identity from auth-me", () => {
  const capability = readCapability(
    "parity-capability-definitions.23-identity-profile.v2.json",
    "user-profile",
  );

  assert.deepEqual(contractKeys(capability, "web"), [
    "GET /api/v1/auth/me",
    "PUT /api/v1/users/me",
    "POST /api/v1/auth/force-change-password",
  ]);
  assert.equal(
    contractKeys(capability, "web").includes("GET /api/v1/users/me"),
    false,
  );
  assert.match(capability.judgment_rationale, /UserProfile/u);
  assert.match(capability.judgment_rationale, /useAuthStore/u);
  assert.match(capability.judgment_rationale, /authAPI\.(?:login|verifyToken)/u);
  assert.match(capability.judgment_rationale, /\/auth\/me/u);
  assert.match(capability.judgment_rationale, /\/users\/me/u);
});
