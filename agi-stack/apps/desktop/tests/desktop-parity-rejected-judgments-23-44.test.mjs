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

test("Project Workspaces limits Web authority to its two routed pages", () => {
  const workspaces = readCapability(
    "parity-capability-definitions.16-project-workspace.v2.json",
    "project-project-workspaces",
  );

  assert.deepEqual(workspaces.web_actions, [
    "view",
    "list",
    "create",
    "open-blackboard",
  ]);
  assert.deepEqual(contractKeys(workspaces, "web"), [
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
  ]);
  assert.deepEqual(
    workspaces.permission_requirements
      .filter((requirement) => requirement.surface === "web")
      .flatMap((requirement) => requirement.actions),
    ["view", "list", "open-blackboard", "create"],
  );
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
    "list-replies",
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
});

test("Project Team records the tenant invitation used by its production form", () => {
  const team = readCapability(
    "parity-capability-definitions.17-project-knowledge-core.v2.json",
    "project-project-team",
  );
  const webContracts = contractKeys(team, "web");

  assert.ok(
    webContracts.includes(
      "POST /api/v1/tenants/{tenant_id}/invitations",
    ),
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
    permissionActions(memories, "web", "project_member").includes(
      "copy-link",
    ),
  );
  assert.match(memories.judgment_rationale, /navigator\.clipboard/u);
});

test("Project Communities records its rebuild task lifecycle", () => {
  const communities = readCapability(
    "parity-capability-definitions.18-project-knowledge-graph.v2.json",
    "project-project-communities",
  );
  const taskActions = [
    "stream-rebuild-progress",
    "cancel-rebuild",
    "list-task-history",
    "retry-task",
    "stop-task",
  ];
  const webContracts = contractKeys(communities, "web");

  for (const action of taskActions) {
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
    "POST /api/v1/tasks/{task_id}/retry",
    "POST /api/v1/tasks/{task_id}/stop",
  ]) {
    assert.ok(webContracts.includes(contract), `missing ${contract}`);
  }
  assert.match(communities.judgment_rationale, /CommunitiesList\.tsx/u);
  assert.match(communities.judgment_rationale, /communities\/index\.tsx/u);
  assert.match(communities.judgment_rationale, /TaskList\.tsx/u);
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
