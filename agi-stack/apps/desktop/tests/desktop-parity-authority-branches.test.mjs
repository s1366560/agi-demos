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

test("Plugin Marketplace exposes only V2 reads and exact-version uninstall", () => {
  const capability = readCapability(
    "parity-capability-definitions.06-plugins.v2.json",
    "tenant-tenant-plugins",
  );
  const tenantAdminOrOwner = [["tenant_admin"], ["tenant_owner"]];

  assertActions(
    capability,
    "web",
    ["view", "list", "view-detail"],
    [["tenant_member"]],
  );
  assertActions(
    capability,
    "web",
    ["uninstall-exact-version"],
    tenantAdminOrOwner,
  );

  assertMatrix(capability, "desktop_cloud", {
    view: [["tenant_member"]],
    list: [["tenant_member"]],
  });
  assertActions(
    capability,
    "desktop_cloud",
    ["uninstall-exact-version"],
    tenantAdminOrOwner,
  );
  assertActions(capability, "desktop_local", ["view", "list"], [["tenant_member"]]);
  assertActions(
    capability,
    "desktop_local",
    ["uninstall-exact-version"],
    tenantAdminOrOwner,
  );

  assert.deepEqual(contractKeys(capability, "web"), [
    "GET /api/v1/plugin-marketplace/packages",
    "GET /api/v1/plugin-marketplace/packages/{plugin_id}",
    "POST /api/v1/plugin-marketplace/packages/{plugin_id}/uninstall",
  ]);
  for (const surface of ["desktop_cloud", "desktop_local"]) {
    assert.deepEqual(contractKeys(capability, surface), [
      "GET /api/v1/plugin-marketplace/packages",
      "POST /api/v1/plugin-marketplace/packages/{plugin_id}/uninstall",
    ]);
  }
  for (const retiredAction of [
    "install",
    "enable",
    "disable",
    "reload",
    "view-config",
    "update-config",
  ]) {
    assert.equal(capability.actions.includes(retiredAction), false, retiredAction);
  }
  assert.equal(
    capability.api_contracts.some((contract) =>
      contract.path.includes("/channels/tenants/{tenant_id}/plugins"),
    ),
    false,
  );
});
