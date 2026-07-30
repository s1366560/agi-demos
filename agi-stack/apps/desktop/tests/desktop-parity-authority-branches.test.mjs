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

function authorizationBranches(capability, surface, action) {
  return capability.permission_requirements
    .filter(
      (requirement) =>
        requirement.surface === surface &&
        requirement.actions.includes(action),
    )
    .map((requirement) => requirement.authorization);
}

function contractKeys(capability, surface) {
  return capability.api_contracts
    .filter((contract) => contract.surface === surface)
    .map((contract) => `${contract.method} ${contract.path}`);
}

function assertActions(capability, surface, actions, expected) {
  for (const action of actions) {
    assert.deepEqual(
      authorizationBranches(capability, surface, action),
      expected,
      `${capability.id} ${surface}.${action}`,
    );
  }
}

function assertMatrix(capability, surface, matrix) {
  for (const [action, expected] of Object.entries(matrix)) {
    assertActions(capability, surface, [action], expected);
  }
}

test("Agent Definitions keeps tenant and project authorization branches distinct", () => {
  const capability = readCapability(
    "parity-capability-definitions.03-agent-core.v2.json",
    "tenant-tenant-agent-definitions",
  );
  const reads = ["view", "list", "get"];
  const mutations = ["create", "update", "delete", "set-enabled"];

  for (const surface of ["web", "desktop_cloud"]) {
    assertActions(
      capability,
      surface,
      reads,
      [["tenant_member"], ["tenant_member", "project_member"]],
    );
    assertActions(
      capability,
      surface,
      mutations,
      [["tenant_admin"], ["tenant_admin", "project_member"]],
    );
  }
  assertActions(capability, "desktop_local", reads, [["tenant_member"]]);
  assertActions(capability, "desktop_local", mutations, [["tenant_admin"]]);
  assert.equal(
    capability.permission_requirements.every(
      (requirement) => requirement.feature_gate === null,
    ),
    true,
  );
});

test("Skills keeps tenant authority separate from project contributor authority", () => {
  const capability = readCapability(
    "parity-capability-definitions.04-agent-skills.v2.json",
    "tenant-tenant-skills",
  );
  const commonReads = [
    "view",
    "list",
    "get",
    "export",
    "list-versions",
    "get-version",
  ];
  const commonMutations = [
    "create",
    "update",
    "delete",
    "set-status",
    "update-content",
    "import-package",
    "rollback",
  ];

  assertActions(
    capability,
    "web",
    [...commonReads, "view-evolution"],
    [["tenant_member"], ["project_member"]],
  );
  assertActions(
    capability,
    "web",
    [...commonMutations, "import-zip"],
    [["tenant_admin"], ["project_contributor"]],
  );
  assertActions(
    capability,
    "desktop_cloud",
    [...commonReads, "view-evolution"],
    [["tenant_member"], ["project_member"]],
  );
  assertActions(
    capability,
    "desktop_cloud",
    [...commonMutations, "import-zip"],
    [["tenant_admin"], ["project_contributor"]],
  );
  assertActions(capability, "desktop_local", commonReads, [["tenant_member"]]);
  assertActions(capability, "desktop_local", commonMutations, [["tenant_admin"]]);
});

test("Plugins separates tenant control-plane and project channel authorities", () => {
  const capability = readCapability(
    "parity-capability-definitions.06-plugins.v2.json",
    "tenant-tenant-plugins",
  );
  const tenantAdminOrOwner = [["tenant_admin"], ["tenant_owner"]];
  const projectAdminOrOwner = [["project_admin"], ["project_owner"]];
  const tenantAndProjectMember = [
    ["tenant_admin", "project_member"],
    ["tenant_owner", "project_member"],
  ];
  const tenantAndProjectAdminOrOwner = [
    ["tenant_admin", "project_admin"],
    ["tenant_admin", "project_owner"],
    ["tenant_owner", "project_admin"],
    ["tenant_owner", "project_owner"],
  ];

  assertActions(
    capability,
    "web",
    [
      "view",
      "list",
      "view-channel-catalog",
      "view-channel-schema",
      "view-config-schema",
      "view-config",
    ],
    [["tenant_member"]],
  );
  assertActions(
    capability,
    "web",
    ["install", "enable", "disable", "uninstall", "reload", "update-config"],
    tenantAdminOrOwner,
  );
  assertActions(
    capability,
    "web",
    ["list-channel-configs", "test-channel-config"],
    [["project_member"]],
  );
  assertActions(
    capability,
    "web",
    ["create-channel-config", "update-channel-config", "delete-channel-config"],
    projectAdminOrOwner,
  );

  assertMatrix(capability, "desktop_cloud", {
    view: [["tenant_member"]],
    list: [["tenant_member"]],
  });
  assertActions(
    capability,
    "desktop_cloud",
    [
      "view-config-schema",
      "view-config",
      "install",
      "enable",
      "disable",
      "uninstall",
      "reload",
      "update-config",
    ],
    tenantAdminOrOwner,
  );
  assertActions(
    capability,
    "desktop_cloud",
    [
      "view-channel-catalog",
      "view-channel-schema",
      "list-channel-configs",
      "test-channel-config",
    ],
    tenantAndProjectMember,
  );
  assertActions(
    capability,
    "desktop_cloud",
    ["create-channel-config", "update-channel-config", "delete-channel-config"],
    tenantAndProjectAdminOrOwner,
  );
  assertActions(capability, "desktop_local", ["view", "list"], [["tenant_member"]]);
  assertActions(
    capability,
    "desktop_local",
    ["enable", "disable"],
    tenantAdminOrOwner,
  );

  const pluginNameContracts = [
    "POST /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/enable",
    "POST /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/disable",
    "POST /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/uninstall",
    "GET /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/config-schema",
    "GET /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/config",
    "PUT /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_name}/config",
  ];
  for (const surface of ["web", "desktop_cloud"]) {
    const contracts = contractKeys(capability, surface);
    for (const contract of pluginNameContracts) {
      assert.ok(contracts.includes(contract), `${surface} missing ${contract}`);
    }
    assert.equal(
      contracts.some((contract) => contract.includes("{plugin_id}")),
      false,
      `${surface} must use the production plugin_name parameter`,
    );
  }
  assert.deepEqual(
    contractKeys(capability, "desktop_local").filter((contract) =>
      contract.includes("/{plugin_id}/"),
    ),
    [
      "POST /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_id}/enable",
      "POST /api/v1/channels/tenants/{tenant_id}/plugins/{plugin_id}/disable",
    ],
  );
});
