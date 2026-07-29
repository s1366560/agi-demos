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

function permissionActionsForAuthorization(capability, surface, authorization) {
  return capability.permission_requirements
    .filter(
      (requirement) =>
        requirement.surface === surface &&
        requirement.authorization.includes(authorization),
    )
    .flatMap((requirement) => requirement.actions);
}

function permissionRequirementsForAction(capability, surface, action) {
  return capability.permission_requirements.filter(
    (requirement) =>
      requirement.surface === surface &&
      requirement.actions.includes(action),
  );
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

test("Tenant Workspaces limits Web authority to its routed list and create pages", () => {
  const capability = readCapability(
    "parity-capability-definitions.02-tenant-operations.v2.json",
    "tenant-tenant-workspaces",
  );
  const expectedWebActions = ["view", "list", "create"];

  assert.deepEqual(capability.actions, expectedWebActions);
  assert.deepEqual(capability.web_actions, expectedWebActions);
  assert.deepEqual(contractKeys(capability, "web"), [
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
  ]);
  assert.deepEqual(permissionActions(capability, "web").sort(), [
    "create",
    "list",
    "view",
  ]);
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
    "agi-stack/apps/desktop/src/features/workspace/WorkspaceMembersPanel.tsx",
    "agi-stack/apps/desktop/src/features/workspace/workspaceMembersModel.ts",
    "agi-stack/apps/desktop/src/features/workspace/WorkspaceAgentBindingsPanel.tsx",
    "agi-stack/apps/desktop/src/features/workspace/workspaceAgentBindingsModel.ts",
  ]) {
    assert.ok(capability.cloud_entries.includes(entry), `missing ${entry}`);
  }

  const requiredMutationContracts = [
    "PATCH /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members/{user_id}",
    "DELETE /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members/{user_id}",
    "DELETE /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents/{workspace_agent_id}",
  ];
  const cloudContracts = contractKeys(capability, "desktop_cloud");
  for (const contract of requiredMutationContracts) {
    assert.ok(
      cloudContracts.includes(contract),
      `desktop_cloud missing ${contract}`,
    );
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
  assert.deepEqual(
    permissionActionsForAuthorization(
      capability,
      "desktop_cloud",
      "workspace_editor",
    ).sort(),
    ["bind-agent", "unbind-agent", "update"],
  );
  assert.deepEqual(
    permissionActionsForAuthorization(
      capability,
      "desktop_cloud",
      "workspace_owner",
    ),
    ["manage-members"],
  );
  assert.equal(
    capability.permission_requirements.some((requirement) =>
      requirement.authorization.includes("workspace_manager"),
    ),
    false,
  );
  assert.equal(
    capability.permissions.includes("workspace_manager_for_mutations"),
    false,
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

test("Skills records the evolution read bound by SkillDetail", () => {
  const capability = readCapability(
    "parity-capability-definitions.04-agent-skills.v2.json",
    "tenant-tenant-skills",
  );
  const evolutionContract =
    "GET /api/v1/skills/{skill_id}/evolution";

  assert.ok(contractKeys(capability, "web").includes(evolutionContract));
  assert.equal(capability.actions.includes("view-evolution"), true);
  assert.equal(capability.web_actions.includes("view-evolution"), true);
  assert.equal(capability.cloud_actions.includes("view-evolution"), false);
  assert.equal(capability.local_actions.includes("view-evolution"), false);
  assert.deepEqual(
    permissionRequirementsForAction(
      capability,
      "web",
      "view-evolution",
    ),
    [
      {
        surface: "web",
        actions: [
          "view",
          "list",
          "get",
          "view-evolution",
          "export",
          "list-versions",
          "get-version",
        ],
        authentication: "authenticated",
        authorization: ["tenant_member", "project_member"],
        enforcement: "enforced",
        feature_gate: null,
      },
    ],
  );
  assert.match(capability.judgment_rationale, /SkillDetail/u);
  assert.match(capability.judgment_rationale, /getEvolution/u);
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

test("Web MCP Servers records the directly rendered MCP Apps tab without proxy overclaim", () => {
  const capability = readCapability(
    "parity-capability-definitions.07-extension-protocols.v2.json",
    "tenant-tenant-mcp-servers",
  );
  const appActions = [
    "list-apps",
    "search-apps",
    "delete-app",
    "refresh-app",
    "open-app-in-canvas",
  ];
  const webContracts = contractKeys(capability, "web");

  for (const contract of [
    "GET /api/v1/mcp/apps",
    "DELETE /api/v1/mcp/apps/{app_id}",
    "POST /api/v1/mcp/apps/{app_id}/refresh",
  ]) {
    assert.ok(webContracts.includes(contract), `web missing ${contract}`);
  }
  for (const contract of [
    "GET /api/v1/mcp/apps/{app_id}/resource",
    "POST /api/v1/mcp/apps/{app_id}/tool-call",
    "POST /api/v1/mcp/apps/proxy/tool-call",
    "POST /api/v1/mcp/apps/resources/read",
    "POST /api/v1/mcp/apps/resources/list",
  ]) {
    assert.equal(webContracts.includes(contract), false, contract);
  }
  for (const action of appActions) {
    assert.equal(capability.actions.includes(action), true, action);
    assert.equal(capability.web_actions.includes(action), true, action);
    assert.equal(capability.cloud_actions.includes(action), false, action);
    assert.equal(capability.local_actions.includes(action), false, action);
  }
  assert.deepEqual(
    permissionActionsForAuthorization(
      capability,
      "web",
      "project_member",
    ).filter((action) => appActions.includes(action)),
    ["list-apps", "search-apps", "open-app-in-canvas"],
  );
  assert.deepEqual(
    permissionActionsForAuthorization(
      capability,
      "web",
      "project_contributor",
    ).filter((action) => appActions.includes(action)),
    ["delete-app", "refresh-app"],
  );
  assert.equal(capability.web_status, "partial");
  assert.equal(
    capability.web_reason_code,
    "web_mcp_app_canvas_context_incomplete",
  );
  assert.match(capability.judgment_rationale, /McpAppsTabV2/u);
  assert.match(capability.judgment_rationale, /Canvas/u);
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

test("Provider types are bound by ProviderConfigModal across all three product surfaces", () => {
  const capability = readCapability(
    "parity-capability-definitions.08-provider-webhooks.v2.json",
    "tenant-tenant-providers",
  );
  const webContracts = contractKeys(capability, "web");
  const providerTypesContract = "GET /api/v1/llm-providers/types";

  for (const contract of [
    "GET /api/v1/llm-providers/{provider_id}",
    "GET /api/v1/llm-providers/tenants/{tenant_id}/provider",
    "GET /api/v1/llm-providers/models/catalog/search",
  ]) {
    assert.equal(webContracts.includes(contract), false, contract);
  }
  for (const surface of ["web", "desktop_cloud", "desktop_local"]) {
    assert.equal(
      contractKeys(capability, surface).includes(providerTypesContract),
      true,
      `${surface} provider types contract`,
    );
    assert.equal(
      capability[
        surface === "web"
          ? "web_actions"
          : surface === "desktop_cloud"
            ? "cloud_actions"
            : "local_actions"
      ].includes("list-provider-types"),
      true,
      `${surface} provider types action`,
    );
    assert.deepEqual(
      permissionRequirementsForAction(
        capability,
        surface,
        "list-provider-types",
      ),
      [
        {
          surface,
          actions:
            surface === "web"
              ? [
                  "view",
                  "list",
                  "list-provider-types",
                  "view-usage",
                  "list-models",
                  "search-models",
                ]
              : surface === "desktop_cloud"
                ? [
                    "view",
                    "list",
                    "list-provider-types",
                    "view-usage",
                    "list-models",
                  ]
                : [
                    "view",
                    "list",
                    "list-provider-types",
                    "health-check",
                    "test-connection",
                    "view-usage",
                    "list-models",
                    "discover-models",
                  ],
          authentication: "authenticated",
          authorization: [],
          enforcement: "enforced",
          feature_gate: null,
        },
      ],
    );
  }
  assert.equal(capability.actions.includes("list-provider-types"), true);
  assert.equal(capability.actions.includes("get"), false);
  assert.equal(capability.web_actions.includes("get"), false);
  assert.equal(capability.web_actions.includes("search-models"), true);
  assert.ok(webContracts.includes("GET /api/v1/llm-providers/models/catalog"));
  assert.match(capability.judgment_rationale, /ProviderConfigModal/u);
  assert.match(capability.judgment_rationale, /listTypes/u);
});

test("Runtime Instances excludes the unbound general config contract", () => {
  const capability = readCapability(
    "parity-capability-definitions.10-runtime-instances.v2.json",
    "tenant-tenant-instances",
  );

  for (const surface of ["web", "desktop_cloud"]) {
    const contracts = contractKeys(capability, surface);
    assert.equal(
      contracts.includes("GET /api/v1/instances/{instance_id}/config"),
      false,
    );
    assert.equal(
      contracts.includes("PUT /api/v1/instances/{instance_id}/config"),
      false,
    );
  }
  const webContracts = contractKeys(capability, "web");
  assert.ok(webContracts.includes("GET /api/v1/instances/{instance_id}/llm-config"));
  assert.ok(webContracts.includes("PUT /api/v1/instances/{instance_id}/llm-config"));
  assert.ok(capability.actions.includes("configure"));
  assert.ok(permissionActions(capability, "web").includes("configure"));
});

test("Clusters excludes the unbound runner-pool update contract", () => {
  const capability = readCapability(
    "parity-capability-definitions.11-runtime-deployment.v2.json",
    "tenant-tenant-clusters",
  );
  const updateContract =
    "PUT /api/v1/clusters/{cluster_id}/acp-runner-pools/{pool_key}";

  for (const surface of ["web", "desktop_cloud"]) {
    assert.equal(contractKeys(capability, surface).includes(updateContract), false);
  }
  assert.ok(
    contractKeys(capability, "web").includes(
      "POST /api/v1/clusters/{cluster_id}/acp-runner-pools",
    ),
  );
  assert.ok(
    contractKeys(capability, "web").includes(
      "POST /api/v1/clusters/{cluster_id}/acp-runner-pools/{pool_key}/registration-token",
    ),
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
    "copy-result-id",
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
