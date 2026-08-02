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

function permissionActions(capability, surface, authorization) {
  return capability.permission_requirements
    .filter(
      (requirement) =>
        requirement.surface === surface &&
        requirement.authorization.includes(authorization),
    )
    .flatMap((requirement) => requirement.actions);
}

test("Deploy records its current Web contract mismatch as degraded", () => {
  const deploy = readCapability(
    "parity-capability-definitions.11-runtime-deployment.v2.json",
    "tenant-tenant-deploy",
  );
  const webContracts = contractKeys(deploy, "web");

  assert.equal(
    webContracts.includes("GET /api/v1/deploys/instances/{instance_id}/latest"),
    false,
  );
  assert.equal(deploy.web_status, "partial");
  assert.equal(deploy.web_reason_code, "web_deploy_contract_mismatch");
  assert.deepEqual(deploy.web_actions, [
    "view",
    "create",
    "inspect-progress",
    "stream-progress",
  ]);
  assert.match(deploy.judgment_rationale, /deploys.*deployments/u);
  assert.match(deploy.judgment_rationale, /finished_at.*completed_at/u);
  assert.match(deploy.judgment_rationale, /running.*in_progress/u);
});

test("Instance Templates limits APIs to production page callers", () => {
  const templates = readCapability(
    "parity-capability-definitions.11-runtime-deployment.v2.json",
    "tenant-tenant-instance-templates",
  );
  const webContracts = contractKeys(templates, "web");

  for (const unusedContract of [
    "PUT /api/v1/instance-templates/{template_id}",
    "POST /api/v1/instance-templates/{template_id}/unpublish",
    "POST /api/v1/instance-templates/{template_id}/items",
    "DELETE /api/v1/instance-templates/{template_id}/items/{item_id}",
  ]) {
    assert.equal(
      webContracts.includes(unusedContract),
      false,
      `unexpected ${unusedContract}`,
    );
  }
  assert.ok(
    webContracts.includes("GET /api/v1/instance-templates/{template_id}/items"),
  );
  assert.ok(templates.actions.includes("list-items"));
  assert.ok(
    permissionActions(templates, "web", "tenant_member").includes("list-items"),
  );
  assert.ok(
    permissionActions(templates, "web", "tenant_member").includes(
      "deploy-from-template",
    ),
  );
  assert.equal(
    permissionActions(templates, "web", "tenant_admin").includes(
      "deploy-from-template",
    ),
    false,
  );
  assert.equal(templates.web_status, "partial");
  assert.equal(
    templates.web_reason_code,
    "web_instance_template_route_tenant_scope_mismatch",
  );
  assert.deepEqual(templates.web_actions, [
    "view",
    "list",
    "list-items",
    "create",
    "delete",
    "publish",
    "clone",
    "deploy-from-template",
  ]);
  assert.deepEqual(templates.cloud_actions, [
    "view",
    "list",
    "list-items",
    "create",
    "delete",
    "publish",
    "clone",
    "refresh",
    "paginate",
    "search-current-page",
    "filter-status",
  ]);
  const webRequirements = templates.permission_requirements.filter(
    (requirement) => requirement.surface === "web",
  );
  assert.equal(webRequirements.length, 2);
  for (const requirement of webRequirements) {
    assert.equal(requirement.enforcement, "missing");
  }
  assert.match(templates.judgment_rationale, /route tenant/u);
  assert.match(templates.judgment_rationale, /first membership/u);
  assert.match(templates.judgment_rationale, /instance creation/u);
});

test("Gene Market records the evolution history shown by Gene Detail", () => {
  const genes = readCapability(
    "parity-capability-definitions.12-runtime-genes.v2.json",
    "tenant-tenant-genes",
  );

  assert.ok(contractKeys(genes, "web").includes("GET /api/v1/genes/evolution"));
  assert.ok(genes.actions.includes("inspect-evolution"));
  assert.ok(
    permissionActions(genes, "web", "tenant_member").includes(
      "inspect-evolution",
    ),
  );
  assert.match(genes.judgment_rationale, /evolution history/u);
});

test("Dead Letter Queue does not claim its unused single-message API", () => {
  const dlq = readCapability(
    "parity-capability-definitions.13-tenant-governance-operations.v2.json",
    "tenant-tenant-dead-letter-queue",
  );
  const webContracts = contractKeys(dlq, "web");

  assert.equal(
    webContracts.includes("GET /api/v1/admin/dlq/messages/{message_id}"),
    false,
  );
  for (const usedContract of [
    "GET /api/v1/admin/dlq/messages",
    "POST /api/v1/admin/dlq/messages/{message_id}/retry",
    "POST /api/v1/admin/dlq/messages/retry",
    "DELETE /api/v1/admin/dlq/messages/{message_id}",
    "POST /api/v1/admin/dlq/messages/discard",
    "GET /api/v1/admin/dlq/stats",
    "POST /api/v1/admin/dlq/cleanup/expired",
    "POST /api/v1/admin/dlq/cleanup/resolved",
  ]) {
    assert.ok(webContracts.includes(usedContract), `missing ${usedContract}`);
  }
});

test("Decision Records inspects the selected list row without a detail GET", () => {
  const decisions = readCapability(
    "parity-capability-definitions.14-tenant-governance-policy.v2.json",
    "tenant-tenant-decision-records",
  );
  const webContracts = contractKeys(decisions, "web");

  assert.equal(
    webContracts.includes(
      "GET /api/v1/tenants/{tenant_id}/trust/decision-records/{record_id}",
    ),
    false,
  );
  assert.ok(
    webContracts.includes(
      "GET /api/v1/tenants/{tenant_id}/trust/decision-records",
    ),
  );
  assert.ok(
    webContracts.includes(
      "POST /api/v1/tenants/{tenant_id}/trust/approval-requests/{record_id}/resolve",
    ),
  );
  assert.ok(
    permissionActions(decisions, "web", "tenant_member").includes("inspect"),
  );
  assert.equal(decisions.web_status, "partial");
  assert.equal(
    decisions.web_reason_code,
    "web_decision_records_default_workspace_scope_invalid",
  );
  assert.deepEqual(decisions.web_actions ?? decisions.actions, [
    "view",
    "list",
    "filter",
    "inspect",
    "resolve-approval",
  ]);
  assert.ok(
    decisions.permission_requirements
      .filter((requirement) => requirement.surface === "web")
      .every((requirement) => requirement.enforcement === "enforced"),
  );
  assert.match(decisions.judgment_rationale, /workspace_id 'default'/u);
  assert.match(decisions.judgment_rationale, /real workspace ID/u);
  assert.match(decisions.judgment_rationale, /404/u);
});

test("Trust Policies records its invalid default workspace projection", () => {
  const policies = readCapability(
    "parity-capability-definitions.14-tenant-governance-policy.v2.json",
    "tenant-tenant-trust-policies",
  );

  assert.equal(policies.web_status, "partial");
  assert.equal(
    policies.web_reason_code,
    "web_trust_policy_default_workspace_scope_invalid",
  );
  assert.deepEqual(policies.web_actions ?? policies.actions, [
    "view",
    "list",
    "create",
    "revoke",
  ]);
  assert.ok(
    policies.permission_requirements
      .filter((requirement) => requirement.surface === "web")
      .every((requirement) => requirement.enforcement === "enforced"),
  );
  assert.match(policies.judgment_rationale, /workspace_id 'default'/u);
  assert.match(policies.judgment_rationale, /real WorkspaceModel ID/u);
  assert.match(policies.judgment_rationale, /404/u);
});

test("Billing derives invoice rows from the billing response", () => {
  const billing = readCapability(
    "parity-capability-definitions.14-tenant-governance-policy.v2.json",
    "tenant-tenant-billing",
  );
  const webContracts = contractKeys(billing, "web");

  assert.deepEqual(webContracts, [
    "GET /api/v1/tenants/{tenant_id}/billing",
    "POST /api/v1/tenants/{tenant_id}/upgrade",
  ]);
  assert.ok(billing.actions.includes("list-invoices"));
  assert.ok(billing.actions.includes("download-invoice"));
  assert.match(billing.judgment_rationale, /embeds.*invoice/u);
});

test("Organization Settings records the cluster status projection", () => {
  const orgSettings = readCapability(
    "parity-capability-definitions.15-organization-governance.v2.json",
    "tenant-tenant-org-settings",
  );

  assert.ok(contractKeys(orgSettings, "web").includes("GET /api/v1/clusters/"));
  for (const action of ["list-clusters", "inspect-cluster-status"]) {
    assert.ok(orgSettings.actions.includes(action), `missing ${action}`);
    assert.ok(
      permissionActions(orgSettings, "web", "tenant_member").includes(action),
      `missing tenant-member permission for ${action}`,
    );
  }
  assert.equal(orgSettings.web_status, "partial");
  assert.equal(
    orgSettings.web_reason_code,
    "organization_registry_gene_policy_authorization_and_cluster_route_tenant_scope_incomplete",
  );
  assert.deepEqual(orgSettings.web_actions ?? orgSettings.actions, orgSettings.actions);

  const clusterRequirement = orgSettings.permission_requirements.find(
    (requirement) =>
      requirement.surface === "web" &&
      requirement.actions.includes("list-clusters"),
  );
  assert.ok(clusterRequirement);
  assert.deepEqual(clusterRequirement.actions, [
    "list-clusters",
    "inspect-cluster-status",
  ]);
  assert.deepEqual(clusterRequirement.authorization, ["tenant_member"]);
  assert.equal(clusterRequirement.enforcement, "missing");

  const generalMemberRequirement = orgSettings.permission_requirements.find(
    (requirement) =>
      requirement.surface === "web" &&
      requirement.actions.includes("inspect-stats"),
  );
  assert.ok(generalMemberRequirement);
  assert.equal(generalMemberRequirement.enforcement, "enforced");
  assert.equal(
    generalMemberRequirement.actions.includes("list-clusters"),
    false,
  );
  assert.match(orgSettings.judgment_rationale, /first membership/u);
  assert.match(orgSettings.judgment_rationale, /non-default route tenant/u);
});

test("Project Workspaces records the production summary projection", () => {
  const workspaces = readCapability(
    "parity-capability-definitions.16-project-workspace.v2.json",
    "project-project-workspaces",
  );

  assert.ok(workspaces.web_actions.includes("inspect-summary"));
  assert.deepEqual(contractKeys(workspaces, "web"), [
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives",
    "GET /api/v1/workspaces/{workspace_id}/plan?outbox_limit=0&event_limit=0&include_details=false&recover_stale_attempts=false",
    "GET /api/v1/workspaces/{workspace_id}/tasks",
  ]);
  assert.ok(
    permissionActions(workspaces, "web", "workspace_member").includes(
      "inspect-summary",
    ),
  );
  assert.match(workspaces.judgment_rationale, /objectives.*plan.*tasks/u);
});

test("Project Blackboard Cloud contract covers every production Canvas tab", () => {
  const blackboard = readCapability(
    "parity-capability-definitions.16-project-workspace.v2.json",
    "project-blackboard-dynamic-project-blackboard",
  );
  const memberActions = [
    "view",
    "select-workspace",
    "list-objectives",
    "list-tasks",
    "inspect-execution-diagnostics",
    "list-posts",
    "list-agents",
    "list-members",
    "list-genes",
    "list-files",
    "review-notes",
    "list-topology-nodes",
    "list-topology-edges",
    "view-settings",
  ];
  const editorActions = [
    "create-objective",
    "create-task",
    "create-post",
    "pin-post",
    "unpin-post",
    "create-reply",
    "update-gene",
    "create-topology-node",
    "delete-topology-node",
    "create-topology-edge",
    "delete-topology-edge",
    "update-workspace",
  ];
  const ownerActions = ["add-member", "remove-member"];

  assert.deepEqual(blackboard.cloud_actions, [
    ...memberActions,
    ...editorActions,
    ...ownerActions,
  ]);
  assert.deepEqual(contractKeys(blackboard, "desktop_cloud"), [
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/authority",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives",
    "GET /api/v1/workspaces/{workspace_id}/tasks",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/execution-diagnostics",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/genes",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files?parent_path=%2F",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}",
    "GET /api/v1/workspaces/{workspace_id}/topology/nodes",
    "GET /api/v1/workspaces/{workspace_id}/topology/edges",
    "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/mutations",
  ]);
  assert.deepEqual(
    permissionActions(blackboard, "desktop_cloud", "workspace_member"),
    memberActions,
  );
  assert.deepEqual(
    permissionActions(blackboard, "desktop_cloud", "workspace_editor"),
    editorActions,
  );
  assert.deepEqual(
    permissionActions(blackboard, "desktop_cloud", "workspace_owner"),
    ownerActions,
  );

  const webContracts = contractKeys(blackboard, "web");
  const webEditorActions = permissionActions(
    blackboard,
    "web",
    "workspace_editor",
  );
  for (const action of [
    "accept-review",
    "trigger-next-iteration",
    "request-pipeline-run",
    "regenerate-delivery-contract",
  ]) {
    assert.ok(blackboard.web_actions.includes(action), `missing ${action}`);
    assert.ok(
      webEditorActions.includes(action),
      `missing permission ${action}`,
    );
  }
  assert.equal(blackboard.web_actions.includes("recover-stale"), false);
  assert.equal(webEditorActions.includes("recover-stale"), false);
  assert.equal(
    webContracts.includes(
      "POST /api/v1/workspaces/{workspace_id}/plan/recover-stale-attempts",
    ),
    false,
  );
  for (const contract of [
    "POST /api/v1/workspaces/{workspace_id}/plan/nodes/{node_id}/accept-review",
    "POST /api/v1/workspaces/{workspace_id}/plan/iteration/trigger-next",
    "POST /api/v1/workspaces/{workspace_id}/plan/delivery/run-pipeline",
    "POST /api/v1/workspaces/{workspace_id}/plan/delivery/regenerate-contract",
  ]) {
    assert.ok(webContracts.includes(contract), `missing ${contract}`);
  }
  assert.equal(blackboard.cloud_actions.includes("list-replies"), false);
  assert.equal(
    permissionActions(blackboard, "desktop_cloud", "workspace_member").includes(
      "list-replies",
    ),
    false,
  );
  assert.equal(
    contractKeys(blackboard, "desktop_cloud").some((contract) =>
      contract.includes("/replies"),
    ),
    false,
  );
  assert.ok(
    permissionActions(blackboard, "desktop_cloud", "workspace_editor").includes(
      "create-reply",
    ),
  );
});

test("Project Team records the tenant invitation used by its production form", () => {
  const team = readCapability(
    "parity-capability-definitions.17-project-knowledge-core.v2.json",
    "project-project-team",
  );
  const webContracts = contractKeys(team, "web");

  assert.ok(
    webContracts.includes("POST /api/v1/tenants/{tenant_id}/invitations"),
  );
  assert.equal(
    webContracts.includes("POST /api/v1/projects/{project_id}/members"),
    false,
  );
  assert.deepEqual(permissionActions(team, "web", "tenant_admin"), ["invite"]);
  assert.deepEqual(permissionActions(team, "web", "project_admin"), [
    "update-role",
    "remove",
  ]);
});

test("Project Memories records copy-link as a client-side action", () => {
  const memories = readCapability(
    "parity-capability-definitions.17-project-knowledge-core.v2.json",
    "project-project-memories",
  );

  assert.ok(memories.web_actions.includes("copy-link"));
  assert.equal(memories.web_actions.includes("share"), false);
  assert.equal(
    memories.api_contracts.some((contract) =>
      contract.path.includes("/shares"),
    ),
    false,
  );
  assert.ok(
    permissionActions(memories, "web", "project_member").includes("copy-link"),
  );
  assert.equal(
    permissionActions(memories, "web", "project_member").includes("create"),
    false,
  );
  assert.deepEqual(permissionActions(memories, "web", "project_contributor"), [
    "create",
  ]);
  assert.ok(memories.permissions.includes("project_contributor"));
  assert.match(memories.judgment_rationale, /navigator\.clipboard/u);
});

test("Project Entities does not claim its unused entity detail API", () => {
  const entities = readCapability(
    "parity-capability-definitions.17-project-knowledge-core.v2.json",
    "project-project-entities",
  );
  const webContracts = contractKeys(entities, "web");

  assert.equal(
    webContracts.includes("GET /api/v1/graph/entities/{entity_id}"),
    false,
  );
  assert.ok(
    webContracts.includes(
      "GET /api/v1/graph/entities/{entity_id}/relationships",
    ),
  );
  assert.ok(
    permissionActions(entities, "web", "project_member").includes(
      "inspect-relationships",
    ),
  );
});

test("Project Communities degrades unreachable rebuild history controls", () => {
  const communities = readCapability(
    "parity-capability-definitions.18-project-knowledge-graph.v2.json",
    "project-project-communities",
  );
  const availableActions = [
    "view",
    "list",
    "inspect-members",
    "rebuild",
    "stream-rebuild-progress",
    "cancel-rebuild",
  ];
  const unreachableActions = [
    "list-task-history",
    "retry-task",
    "stop-task",
  ];
  const webContracts = contractKeys(communities, "web");

  assert.equal(communities.web_status, "partial");
  assert.equal(
    communities.web_reason_code,
    "web_community_rebuild_task_history_scope_mismatch",
  );
  assert.deepEqual(communities.actions, [
    ...availableActions,
    ...unreachableActions,
  ]);
  assert.deepEqual(communities.web_actions, availableActions);
  for (const action of availableActions) {
    assert.ok(communities.web_actions.includes(action), `missing ${action}`);
    assert.ok(
      permissionActions(communities, "web", "project_member").includes(action),
      `missing permission for ${action}`,
    );
  }
  for (const contract of [
    "GET /api/v1/tasks/{task_id}/stream",
    "POST /api/v1/tasks/{task_id}/cancel",
    "GET /api/v1/tasks/recent",
  ]) {
    assert.ok(webContracts.includes(contract), `missing ${contract}`);
  }
  for (const action of unreachableActions) {
    assert.equal(communities.web_actions.includes(action), false, action);
    assert.equal(
      permissionActions(communities, "web", "project_member").includes(action),
      false,
      action,
    );
  }
  for (const contract of [
    "POST /api/v1/tasks/{task_id}/retry",
    "POST /api/v1/tasks/{task_id}/stop",
  ]) {
    assert.equal(webContracts.includes(contract), false, contract);
  }
  assert.match(communities.judgment_rationale, /CommunitiesList\.tsx/u);
  assert.match(communities.judgment_rationale, /communities\/index\.tsx/u);
  assert.match(communities.judgment_rationale, /TaskList\.tsx/u);
  assert.match(communities.judgment_rationale, /entity_id/u);
  assert.match(communities.judgment_rationale, /project-(?:scoped|wide)/u);
  assert.match(communities.judgment_rationale, /\/tasks\/recent/u);
  assert.match(communities.judgment_rationale, /empty history/u);
  assert.match(communities.judgment_rationale, /source-content/u);
});

test("Project Knowledge Graph records its client-side PNG export", () => {
  const graph = readCapability(
    "parity-capability-definitions.18-project-knowledge-graph.v2.json",
    "project-project-graph",
  );

  assert.ok(graph.actions.includes("export-png"));
  assert.ok(graph.web_actions.includes("export-png"));
  assert.ok(
    permissionActions(graph, "web", "project_member").includes("export-png"),
  );
  assert.match(graph.judgment_rationale, /Cytoscape/u);
  assert.match(graph.judgment_rationale, /client-side PNG/u);
});

test("Project Search records copy-result-id on every implemented surface", () => {
  const search = readCapability(
    "parity-capability-definitions.18-project-knowledge-graph.v2.json",
    "project-project-search",
  );

  for (const field of [
    "actions",
    "web_actions",
    "cloud_actions",
    "local_actions",
  ]) {
    assert.ok(
      search[field].includes("copy-result-id"),
      `${field} missing copy`,
    );
  }
  assert.ok(
    permissionActions(search, "web", "project_member").includes(
      "copy-result-id",
    ),
  );
  assert.ok(
    permissionActions(search, "desktop_cloud", "project_member").includes(
      "copy-result-id",
    ),
  );
  assert.ok(
    search.permission_requirements
      .filter((requirement) => requirement.surface === "desktop_local")
      .flatMap((requirement) => requirement.actions)
      .includes("copy-result-id"),
  );
  assert.match(search.judgment_rationale, /navigator\.clipboard/u);
});
