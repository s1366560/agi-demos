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

function permissionActions(capability, surface) {
  return capability.permission_requirements
    .filter((requirement) => requirement.surface === surface)
    .flatMap((requirement) => requirement.actions);
}

function assertPermissionCoverage(capability, surface, actions) {
  const covered = permissionActions(capability, surface);
  for (const action of actions) {
    assert.ok(
      covered.includes(action),
      `${capability.id} ${surface} permission missing ${action}`,
    );
  }
}

test("Agent Workspace covers every native action with a surface permission", () => {
  const capability = readCapability(
    "parity-capability-definitions.01-conversation.v2.json",
    "agent-workspace-tenant-agent-workspace",
  );

  assertPermissionCoverage(
    capability,
    "desktop_cloud",
    capability.cloud_actions,
  );
  assertPermissionCoverage(
    capability,
    "desktop_local",
    capability.local_actions,
  );
});

test("Projects records the detail read used by the edit route", () => {
  const capability = readCapability(
    "parity-capability-definitions.02-tenant-operations.v2.json",
    "tenant-tenant-projects",
  );

  assert.ok(
    contractKeys(capability, "web").includes(
      "GET /api/v1/projects/{project_id}",
    ),
  );
});

test("Tenant Workspaces binds native settings entries, contracts, and permissions", () => {
  const capability = readCapability(
    "parity-capability-definitions.02-tenant-operations.v2.json",
    "tenant-tenant-workspaces",
  );

  for (const entry of [
    "agi-stack/apps/desktop/src/App.tsx",
    "agi-stack/apps/desktop/src/api/client.ts",
    "agi-stack/apps/desktop/src/features/workspace/WorkspaceSettingsDialog.tsx",
  ]) {
    assert.ok(capability.cloud_entries.includes(entry), `missing ${entry}`);
  }

  const requiredMutationContracts = [
    "PATCH /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members/{user_id}",
    "DELETE /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members/{user_id}",
    "DELETE /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents/{workspace_agent_id}",
  ];
  for (const surface of ["web", "desktop_cloud"]) {
    const contracts = contractKeys(capability, surface);
    for (const contract of requiredMutationContracts) {
      assert.ok(contracts.includes(contract), `${surface} missing ${contract}`);
    }
  }

  for (const contract of [
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents",
  ]) {
    assert.ok(
      contractKeys(capability, "desktop_cloud").includes(contract),
      `desktop_cloud missing ${contract}`,
    );
  }

  assertPermissionCoverage(
    capability,
    "desktop_cloud",
    capability.cloud_actions,
  );
  assertPermissionCoverage(
    capability,
    "desktop_local",
    capability.local_actions,
  );
});

test("Tenant Tasks records the fixed Web projection and native partial coverage", () => {
  const capability = readCapability(
    "parity-capability-definitions.02-tenant-operations.v2.json",
    "tenant-tenant-tasks",
  );

  assert.equal(Object.hasOwn(capability, "web_status"), false);
  assert.equal(Object.hasOwn(capability, "web_reason_code"), false);
  assert.equal(capability.cloud_status, "partial");
  assert.equal(capability.local_status, "partial");
  assert.equal(capability.local_reason_code, "local_task_dashboard_partial");
  assert.match(capability.judgment_rationale, /latest queue-depth point/u);
  assert.match(capability.judgment_rationale, /not yet a complete native equivalent/u);
  assertPermissionCoverage(
    capability,
    "desktop_cloud",
    capability.cloud_actions,
  );
  assertPermissionCoverage(
    capability,
    "desktop_local",
    capability.local_actions,
  );
});

test("Workflow Patterns excludes unbound detail and reset authorities", () => {
  const capability = readCapability(
    "parity-capability-definitions.05-agent-evolution.v2.json",
    "tenant-tenant-patterns",
  );

  assert.deepEqual(capability.actions, ["view", "list", "delete"]);
  assert.deepEqual(capability.web_actions, ["view", "list", "delete"]);
  assert.deepEqual(contractKeys(capability, "web"), [
    "GET /api/v1/agent/workflows/patterns",
    "DELETE /api/v1/agent/workflows/patterns/{pattern_id}",
  ]);
  assert.deepEqual(permissionActions(capability, "web").sort(), [
    "delete",
    "list",
    "view",
  ]);
});

test("Desktop MCP actions match the list and create settings UI", () => {
  const capability = readCapability(
    "parity-capability-definitions.07-extension-protocols.v2.json",
    "tenant-tenant-mcp-servers",
  );
  const expectedActions = ["view", "list", "create"];
  const expectedContracts = ["GET /api/v1/mcp", "POST /api/v1/mcp"];

  assert.deepEqual(capability.cloud_actions, expectedActions);
  assert.deepEqual(capability.local_actions, expectedActions);
  assert.deepEqual(contractKeys(capability, "desktop_cloud"), expectedContracts);
  assert.deepEqual(contractKeys(capability, "desktop_local"), expectedContracts);
  assertPermissionCoverage(capability, "desktop_cloud", expectedActions);
  assertPermissionCoverage(capability, "desktop_local", expectedActions);
});

test("ACP records only controls bound by AcpDashboard", () => {
  const capability = readCapability(
    "parity-capability-definitions.07-extension-protocols.v2.json",
    "tenant-tenant-acp",
  );
  const expectedActions = [
    "view",
    "view-status",
    "list-runner-pools",
    "list-agents",
    "create-agent",
    "update-agent",
    "delete-agent",
    "test-agent",
    "list-sessions",
  ];

  assert.deepEqual(capability.actions, expectedActions);
  assert.deepEqual(capability.web_actions, expectedActions);
  assert.deepEqual(contractKeys(capability, "web"), [
    "GET /api/v1/acp/tenants/{tenant_id}/status",
    "GET /api/v1/acp/tenants/{tenant_id}/runner-pools",
    "POST /api/v1/acp/tenants/{tenant_id}/external-agents",
    "PUT /api/v1/acp/tenants/{tenant_id}/external-agents/{agent_key}",
    "DELETE /api/v1/acp/tenants/{tenant_id}/external-agents/{agent_key}",
    "POST /api/v1/acp/tenants/{tenant_id}/external-agents/{agent_key}/test",
  ]);
  assertPermissionCoverage(capability, "web", expectedActions);
});

test("Cloud Providers excludes Local-only routing mutation and discovery", () => {
  const capability = readCapability(
    "parity-capability-definitions.08-provider-webhooks.v2.json",
    "tenant-tenant-providers",
  );
  const cloudContracts = contractKeys(capability, "desktop_cloud");
  const cloudPermissions = permissionActions(capability, "desktop_cloud");

  for (const action of ["update-routing", "discover-models"]) {
    assert.equal(capability.cloud_actions.includes(action), false);
    assert.equal(cloudPermissions.includes(action), false);
    assert.equal(capability.local_actions.includes(action), true);
  }
  for (const contract of [
    "GET /api/v1/llm-providers/routing-policy",
    "PUT /api/v1/llm-providers/routing-policy",
    "POST /api/v1/llm-providers/{provider_id}/models/discover",
  ]) {
    assert.equal(cloudContracts.includes(contract), false);
  }
  assert.ok(
    cloudContracts.includes("GET /api/v1/llm-providers/models/{provider_type}"),
  );
});

test("Project Search binds every Cloud action to project membership", () => {
  const capability = readCapability(
    "parity-capability-definitions.18-project-knowledge-graph.v2.json",
    "project-project-search",
  );
  const expectedActions = [
    "view",
    "search",
    "filter",
    "semantic-search",
    "faceted-search",
    "temporal-search",
    "graph-traversal",
    "community-search",
  ];
  const cloudRequirements = capability.permission_requirements.filter(
    (requirement) => requirement.surface === "desktop_cloud",
  );

  assert.deepEqual(capability.cloud_actions, expectedActions);
  assert.deepEqual(cloudRequirements, [
    {
      surface: "desktop_cloud",
      actions: expectedActions,
      authentication: "authenticated",
      authorization: ["project_member"],
      enforcement: "enforced",
      feature_gate: null,
    },
  ]);
  assert.equal(permissionActions(capability, "desktop_cloud").includes("export"), false);
});
