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
      requirement.surface === surface && requirement.actions.includes(action),
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

test("Tenant Workspaces records the production summary and Blackboard navigation", () => {
  const capability = readCapability(
    "parity-capability-definitions.02-tenant-operations.v2.json",
    "tenant-tenant-workspaces",
  );
  const expectedWebActions = [
    "view",
    "list",
    "inspect-summary",
    "create",
    "open-blackboard",
  ];

  assert.deepEqual(capability.actions, expectedWebActions);
  assert.deepEqual(capability.web_actions, expectedWebActions);
  assert.deepEqual(contractKeys(capability, "web"), [
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives",
    "GET /api/v1/workspaces/{workspace_id}/plan?outbox_limit=0&event_limit=0&include_details=false&recover_stale_attempts=false",
    "GET /api/v1/workspaces/{workspace_id}/tasks",
  ]);
  assert.deepEqual(permissionActions(capability, "web").sort(), [
    "create",
    "inspect-summary",
    "list",
    "open-blackboard",
    "view",
  ]);
  assert.equal(capability.cloud_status, "unavailable");
  assert.equal(
    capability.cloud_reason_code,
    "renderer_capability_authority_unobserved",
  );
  assert.deepEqual(capability.cloud_actions, []);
  assert.ok(capability.local_actions.includes("open-blackboard"));
  assert.ok(
    permissionActions(capability, "desktop_local").includes("open-blackboard"),
  );
  assert.match(capability.judgment_rationale, /objectives.*plan.*tasks/u);
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

test("Tenant Tasks records fail-closed Cloud and explicit Local degradation boundaries", () => {
  const capability = readCapability(
    "parity-capability-definitions.02-tenant-operations.v2.json",
    "tenant-tenant-tasks",
  );

  assert.equal(Object.hasOwn(capability, "web_status"), false);
  assert.equal(Object.hasOwn(capability, "web_reason_code"), false);
  assert.equal(capability.cloud_status, "unavailable");
  assert.equal(
    capability.cloud_reason_code,
    "renderer_capability_authority_unobserved",
  );
  assert.equal(capability.local_status, "unavailable");
  assert.equal(
    capability.local_reason_code,
    "renderer_capability_authority_unobserved",
  );
  assert.deepEqual(capability.cloud_actions, []);
  assert.deepEqual(capability.local_actions, [
    "view",
    "list",
    "search",
    "filter",
    "paginate",
    "refresh",
    "open-workspace",
  ]);
  assert.match(
    capability.judgment_rationale,
    /renderer_capability_authority_unobserved/u,
  );
  assert.match(
    capability.judgment_rationale,
    /both modes.*renderer_capability_authority_unobserved/u,
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
  assert.equal(capability.web_status, "partial");
  assert.equal(
    capability.web_reason_code,
    "web_pattern_delete_affordance_permission_partial",
  );
  assert.equal(capability.cloud_status, "unavailable");
  assert.equal(
    capability.cloud_reason_code,
    "tenant_patterns_authority_contract_invalid",
  );
  assert.equal(capability.local_status, "unavailable");
  assert.equal(
    capability.local_reason_code,
    "local_workflow_patterns_authority_unavailable",
  );
});

test("management route capabilities fail closed when authority revisions are absent", () => {
  const cases = [
    [
      "parity-capability-definitions.03-agent-core.v2.json",
      "tenant-tenant-agent-definitions",
      "capability_authority_revision_unavailable",
    ],
    [
      "parity-capability-definitions.04-agent-skills.v2.json",
      "tenant-tenant-skills",
      "capability_authority_revision_unavailable",
    ],
    [
      "parity-capability-definitions.05-agent-evolution.v2.json",
      "tenant-tenant-evolution",
      "local_skill_evolution_authority_unavailable",
    ],
    [
      "parity-capability-definitions.06-plugins.v2.json",
      "tenant-tenant-plugins",
      "capability_authority_revision_unavailable",
    ],
  ];

  for (const [fragment, capabilityId, localReason] of cases) {
    const capability = readCapability(fragment, capabilityId);
    assert.equal(capability.cloud_status, "unavailable", capabilityId);
    assert.equal(
      capability.cloud_reason_code,
      "capability_authority_revision_unavailable",
      capabilityId,
    );
    assert.equal(capability.local_status, "unavailable", capabilityId);
    assert.equal(capability.local_reason_code, localReason, capabilityId);
    for (const entry of [
      "agi-stack/apps/desktop/src/App.tsx",
      "agi-stack/apps/desktop/src/features/runtime/capabilitySnapshot.ts",
      "agi-stack/apps/desktop/src/features/runtime/workbenchCapabilityClient.ts",
    ]) {
      assert.ok(
        capability.cloud_entries.includes(entry),
        `${capabilityId}: ${entry}`,
      );
    }
  }
});

test("Skill Evolution records tenant-native and adjacent Web review permissions", () => {
  const capability = readCapability(
    "parity-capability-definitions.05-agent-evolution.v2.json",
    "tenant-tenant-evolution",
  );

  for (const action of ["configure", "run"]) {
    assert.deepEqual(
      permissionRequirementsForAction(capability, "web", action).map(
        (requirement) => requirement.authorization,
      ),
      [["tenant_admin"]],
      action,
    );
  }
  for (const action of ["apply-job", "reject-job"]) {
    assert.deepEqual(
      permissionRequirementsForAction(capability, "web", action).map(
        (requirement) => requirement.authorization,
      ),
      [["tenant_admin"], ["project_contributor"]],
      `web ${action}`,
    );
  }
  for (const action of ["run", "apply-job", "reject-job"]) {
    assert.deepEqual(
      permissionRequirementsForAction(capability, "desktop_cloud", action).map(
        (requirement) => requirement.authorization,
      ),
      [["tenant_admin"]],
      `desktop_cloud ${action}`,
    );
  }
  assert.match(capability.judgment_rationale, /tenant Evolution/u);
  assert.match(
    capability.judgment_rationale,
    /tenant mutations require administration/u,
  );
  assert.match(
    capability.judgment_rationale,
    /capability_authority_revision_unavailable/u,
  );
});

test("Skills records the evolution read bound by SkillDetail", () => {
  const capability = readCapability(
    "parity-capability-definitions.04-agent-skills.v2.json",
    "tenant-tenant-skills",
  );
  const evolutionContract = "GET /api/v1/skills/{skill_id}/evolution";

  assert.ok(contractKeys(capability, "web").includes(evolutionContract));
  assert.equal(capability.actions.includes("view-evolution"), true);
  assert.equal(capability.web_actions.includes("view-evolution"), true);
  assert.equal(capability.cloud_actions.includes("view-evolution"), true);
  assert.equal(capability.local_actions.includes("view-evolution"), false);
  assert.ok(
    contractKeys(capability, "desktop_cloud").includes(evolutionContract),
  );
  assert.deepEqual(
    permissionRequirementsForAction(capability, "web", "view-evolution").map(
      (requirement) => requirement.authorization,
    ),
    [["tenant_member"], ["project_member"]],
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
  assert.deepEqual(
    contractKeys(capability, "desktop_cloud"),
    expectedContracts,
  );
  assert.deepEqual(
    contractKeys(capability, "desktop_local"),
    expectedContracts,
  );
  assertPermissionCoverage(capability, "desktop_cloud", expectedActions);
  assertPermissionCoverage(capability, "desktop_local", expectedActions);
  for (const surface of ["cloud", "local"]) {
    assert.equal(capability[`${surface}_status`], "unavailable");
    assert.equal(
      capability[`${surface}_reason_code`],
      "capability_authority_revision_unavailable",
    );
  }
  for (const entry of [
    "agi-stack/apps/desktop/src/App.tsx",
    "agi-stack/apps/desktop/src/features/runtime/capabilitySnapshot.ts",
    "agi-stack/apps/desktop/src/features/runtime/workbenchCapabilityClient.ts",
    "agi-stack/apps/desktop/src/features/settings-routes/mcpServersRouteModule.ts",
  ]) {
    assert.ok(capability.cloud_entries.includes(entry), entry);
  }
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
  assert.deepEqual(
    contractKeys(capability, "desktop_cloud"),
    contractKeys(capability, "web"),
  );
  assert.deepEqual(capability.cloud_actions, expectedActions);
  assertPermissionCoverage(capability, "desktop_cloud", expectedActions);
  assert.equal(capability.cloud_status, "unavailable");
  assert.equal(
    capability.cloud_reason_code,
    "tenant_acp_authority_contract_invalid",
  );
  assert.ok(
    capability.cloud_entries.includes(
      "agi-stack/apps/desktop/src/features/tenant-admin/tenantAcpRouteModule.tsx",
    ),
  );
});

test("Template Marketplace records the native Cloud route but fails closed without revision", () => {
  const capability = readCapability(
    "parity-capability-definitions.07-extension-protocols.v2.json",
    "tenant-tenant-templates",
  );

  assert.deepEqual(contractKeys(capability, "desktop_cloud"), [
    "GET /api/v1/subagents/templates/list",
    "GET /api/v1/subagents/templates/categories",
    "GET /api/v1/subagents/templates/{template_id}",
    "POST /api/v1/subagents/templates/{template_id}/install",
    "POST /api/v1/subagents/templates/seed",
  ]);
  assert.deepEqual(capability.cloud_actions, capability.web_actions);
  assertPermissionCoverage(
    capability,
    "desktop_cloud",
    capability.cloud_actions,
  );
  assert.equal(capability.cloud_status, "unavailable");
  assert.equal(
    capability.cloud_reason_code,
    "capability_authority_revision_unavailable",
  );
  assert.ok(
    capability.cloud_entries.includes(
      "agi-stack/apps/desktop/src/features/settings-routes/templatesRouteModule.ts",
    ),
  );
  assert.ok(
    capability.local_entries.includes(
      "agi-stack/apps/desktop/src/features/settings-routes/TemplatesRoutePage.tsx",
    ),
  );
});

test("Agent Dashboard records the admin-only runtime hook catalog", () => {
  const capability = readCapability(
    "parity-capability-definitions.03-agent-core.v2.json",
    "tenant-tenant-agent-configuration",
  );

  assert.equal(
    permissionActionsForAuthorization(
      capability,
      "web",
      "tenant_member",
    ).includes("view-hook-catalog"),
    false,
  );
  assert.deepEqual(
    permissionActionsForAuthorization(capability, "web", "tenant_admin").sort(),
    ["update-config", "view-hook-catalog"],
  );
  assert.match(capability.judgment_rationale, /hook catalog.*tenant admin/iu);
});

test("Agent Bindings records tenant-only scope and member-readable testing", () => {
  const capability = readCapability(
    "parity-capability-definitions.03-agent-core.v2.json",
    "tenant-tenant-agent-bindings",
  );

  assert.deepEqual(capability.scope, ["tenant"]);
  assert.equal(
    capability.permissions.includes("project_access_when_scoped"),
    false,
  );
  for (const requirement of capability.permission_requirements.filter(
    ({ surface }) => surface === "web",
  )) {
    assert.equal(requirement.authorization.includes("project_member"), false);
  }
  assert.deepEqual(
    permissionActionsForAuthorization(
      capability,
      "web",
      "tenant_member",
    ).sort(),
    ["list", "test", "view"],
  );
  assert.deepEqual(
    permissionActionsForAuthorization(capability, "web", "tenant_admin").sort(),
    ["create", "delete", "set-enabled"],
  );
  assert.match(capability.judgment_rationale, /tenant-(?:level|scoped)/iu);
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

test("Webhooks records the gated event type catalog used by creation", () => {
  const capability = readCapability(
    "parity-capability-definitions.08-provider-webhooks.v2.json",
    "tenant-tenant-webhooks",
  );

  assert.ok(
    contractKeys(capability, "web").includes("GET /api/v1/events/types"),
  );
  assert.ok(capability.actions.includes("list-event-types"));
  assert.ok(capability.web_actions.includes("list-event-types"));
  assert.deepEqual(
    permissionRequirementsForAction(capability, "web", "list-event-types"),
    [
      {
        surface: "web",
        actions: ["list-event-types"],
        authentication: "authenticated",
        authorization: ["tenant_member"],
        enforcement: "enforced",
        feature_gate: "events",
      },
    ],
  );
  for (const action of ["create", "update", "delete"]) {
    const requirements = permissionRequirementsForAction(
      capability,
      "web",
      action,
    );
    assert.equal(requirements.length, 1, action);
    assert.deepEqual(requirements[0].authorization, ["tenant_admin"]);
    assert.equal(requirements[0].feature_gate, null);
  }
  assert.ok(
    capability.permissions.includes("events_feature_for_event_type_catalog"),
  );
  assert.match(capability.judgment_rationale, /event type catalog/u);
  assert.match(capability.judgment_rationale, /feature gate/u);
  assert.equal(capability.cloud_status, "unavailable");
  assert.equal(
    capability.cloud_reason_code,
    "tenant_webhooks_authority_contract_invalid",
  );
  assert.deepEqual(capability.cloud_actions, capability.web_actions);
  assert.deepEqual(
    contractKeys(capability, "desktop_cloud"),
    contractKeys(capability, "web"),
  );
  assertPermissionCoverage(
    capability,
    "desktop_cloud",
    capability.cloud_actions,
  );
  assert.ok(
    capability.cloud_entries.includes(
      "agi-stack/apps/desktop/src/features/tenant-admin/tenantWebhooksRouteModule.tsx",
    ),
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
                  "list-models",
                  "search-models",
                ]
              : surface === "desktop_cloud"
                ? ["view", "list", "list-provider-types", "list-models"]
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
  for (const surface of ["cloud", "local"]) {
    assert.equal(capability[`${surface}_status`], "unavailable");
    assert.equal(
      capability[`${surface}_reason_code`],
      "capability_authority_revision_unavailable",
    );
  }
  assert.ok(
    capability.cloud_entries.includes(
      "agi-stack/apps/desktop/src/features/settings-routes/providersRouteModule.ts",
    ),
  );
});

test("Cloud Provider usage requires tenant membership unless the user is a global admin", () => {
  const capability = readCapability(
    "parity-capability-definitions.08-provider-webhooks.v2.json",
    "tenant-tenant-providers",
  );

  for (const surface of ["web", "desktop_cloud"]) {
    assert.deepEqual(
      permissionRequirementsForAction(capability, surface, "view-usage"),
      [
        {
          surface,
          actions: ["view-usage"],
          authentication: "authenticated",
          authorization: ["tenant_member"],
          enforcement: "enforced",
          feature_gate: null,
        },
        {
          surface,
          actions: ["view-usage"],
          authentication: "authenticated",
          authorization: ["global_admin"],
          enforcement: "enforced",
          feature_gate: null,
        },
      ],
    );
  }
  assert.ok(
    capability.permissions.includes("tenant_member_or_global_admin_for_usage"),
  );
  assert.match(
    capability.judgment_rationale,
    /usage.*tenant membership.*global admin/iu,
  );
});

test("renderer-declared Cloud route slices retain entries but expose no actions", () => {
  const cases = [
    [
      "parity-capability-definitions.02-tenant-operations.v2.json",
      "tenant-tenant-workspaces",
      true,
    ],
    [
      "parity-capability-definitions.02-tenant-operations.v2.json",
      "tenant-tenant-tasks",
      true,
    ],
    [
      "parity-capability-definitions.09-runtime-pool.v2.json",
      "tenant-tenant-runtimes",
      true,
    ],
    [
      "parity-capability-definitions.09-runtime-pool.v2.json",
      "tenant-tenant-pool",
      false,
    ],
    [
      "parity-capability-definitions.10-runtime-instances.v2.json",
      "tenant-tenant-instances",
      true,
    ],
    [
      "parity-capability-definitions.11-runtime-deployment.v2.json",
      "tenant-tenant-clusters",
      false,
    ],
  ];

  for (const [fragment, capabilityId, localDeclared] of cases) {
    const capability = readCapability(fragment, capabilityId);
    assert.equal(capability.cloud_status, "unavailable", capabilityId);
    assert.equal(
      capability.cloud_reason_code,
      "renderer_capability_authority_unobserved",
      capabilityId,
    );
    assert.deepEqual(capability.cloud_actions, [], capabilityId);
    for (const entry of [
      "agi-stack/apps/desktop/src/App.tsx",
      "agi-stack/apps/desktop/src/features/runtime/capabilitySnapshot.ts",
      "agi-stack/apps/desktop/src/features/runtime/workbenchCapabilityClient.ts",
    ]) {
      assert.ok(
        capability.cloud_entries.includes(entry),
        `${capabilityId}: ${entry}`,
      );
    }
    assert.match(
      capability.judgment_rationale,
      /renderer_capability_authority_unobserved/u,
      capabilityId,
    );
    if (localDeclared) {
      assert.equal(capability.local_status, "unavailable", capabilityId);
      assert.equal(
        capability.local_reason_code,
        "renderer_capability_authority_unobserved",
        capabilityId,
      );
      assert.notDeepEqual(capability.local_actions, [], capabilityId);
      for (const entry of [
        "agi-stack/apps/desktop/src/features/runtime/capabilitySnapshot.ts",
        "agi-stack/apps/desktop/src/features/runtime/workbenchCapabilityClient.ts",
      ]) {
        assert.ok(
          capability.local_entries.includes(entry),
          `${capabilityId}: ${entry}`,
        );
      }
    }
  }
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
  assert.ok(
    webContracts.includes("GET /api/v1/instances/{instance_id}/llm-config"),
  );
  assert.ok(
    webContracts.includes("PUT /api/v1/instances/{instance_id}/llm-config"),
  );
  assert.ok(capability.actions.includes("configure"));
  assert.ok(permissionActions(capability, "web").includes("configure"));
});

test("Runtime Instances records direct dependencies and current member and scope defects", () => {
  const capability = readCapability(
    "parity-capability-definitions.10-runtime-instances.v2.json",
    "tenant-tenant-instances",
  );
  const webContracts = contractKeys(capability, "web");

  for (const contract of [
    "GET /api/v1/clusters/",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    "GET /api/v1/instance-templates/{template_id}",
    "GET /api/v1/genes/",
    "GET /api/v1/llm-providers/",
    "GET /api/v1/llm-providers/models/{provider_type}",
  ]) {
    assert.ok(webContracts.includes(contract), contract);
  }
  assert.ok(
    webContracts.includes(
      "PUT /api/v1/instances/{instance_id}/members/{member_id}",
    ),
  );
  assert.equal(
    webContracts.includes(
      "PUT /api/v1/instances/{instance_id}/members/{user_id}",
    ),
    false,
  );
  for (const action of [
    "list-members",
    "search-users",
    "add-member",
    "remove-member",
  ]) {
    assert.ok(capability.actions.includes(action), action);
  }
  assert.equal(capability.actions.includes("manage-members"), false);
  assert.equal(capability.actions.includes("update-member-role"), false);
  assert.equal(
    capability.web_reason_code,
    "runtime_instance_contract_and_authorization_incomplete",
  );
  assert.match(capability.judgment_rationale, /member.*identifier/iu);
  assert.match(
    capability.judgment_rationale,
    /selected tenant.*default tenant/iu,
  );
});

test("Clusters excludes the unbound runner-pool update contract", () => {
  const capability = readCapability(
    "parity-capability-definitions.11-runtime-deployment.v2.json",
    "tenant-tenant-clusters",
  );
  const updateContract =
    "PUT /api/v1/clusters/{cluster_id}/acp-runner-pools/{pool_key}";

  for (const surface of ["web", "desktop_cloud"]) {
    assert.equal(
      contractKeys(capability, surface).includes(updateContract),
      false,
    );
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
  assert.equal(
    permissionActions(capability, "desktop_cloud").includes("export"),
    false,
  );
});
