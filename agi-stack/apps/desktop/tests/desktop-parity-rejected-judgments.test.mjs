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

test("Deployments records the audited Web create action and permission", () => {
  const deploy = readCapability(
    "parity-capability-definitions.11-runtime-deployment.v2.json",
    "tenant-tenant-deploy",
  );
  const tenantMember = deploy.permission_requirements.find(
    (requirement) =>
      requirement.surface === "web" &&
      requirement.authorization.includes("tenant_member"),
  );

  assert.ok(deploy.actions.includes("create"));
  assert.ok(tenantMember?.actions.includes("create"));
  assert.ok(contractKeys(deploy, "web").includes("POST /api/v1/deploys/"));
});

test("Project Workspaces records the audited native Cloud settings mutations", () => {
  const fragmentName =
    "parity-capability-definitions.16-project-workspace.v2.json";
  const workspaces = readCapability(fragmentName, "project-project-workspaces");
  const requiredCloudActions = [
    "update",
    "add-member",
    "update-member-role",
    "remove-member",
    "bind-agent",
    "unbind-agent",
  ];

  for (const action of requiredCloudActions) {
    assert.ok(workspaces.cloud_actions.includes(action), `missing ${action}`);
  }
  assert.equal(workspaces.cloud_actions.includes("delete"), false);
  assert.ok(
    workspaces.cloud_entries.includes("agi-stack/apps/desktop/src/App.tsx"),
  );
  assert.ok(
    workspaces.cloud_entries.includes(
      "agi-stack/apps/desktop/src/features/workspace/WorkspaceSettingsDialog.tsx",
    ),
  );

  const cloudContracts = contractKeys(workspaces, "desktop_cloud");
  for (const contract of [
    "PATCH /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}",
    "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members",
    "PATCH /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members/{user_id}",
    "DELETE /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members/{user_id}",
    "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents",
    "DELETE /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents/{workspace_agent_id}",
  ]) {
    assert.ok(cloudContracts.includes(contract), `missing ${contract}`);
  }
  const cloudPermissionActions = workspaces.permission_requirements
    .filter((requirement) => requirement.surface === "desktop_cloud")
    .flatMap((requirement) => requirement.actions);
  for (const action of workspaces.cloud_actions) {
    assert.ok(
      cloudPermissionActions.includes(action),
      `missing Cloud permission for ${action}`,
    );
  }
  const cloudEditor = workspaces.permission_requirements.find(
    (requirement) =>
      requirement.surface === "desktop_cloud" &&
      requirement.authorization.includes("workspace_editor"),
  );
  const cloudOwner = workspaces.permission_requirements.find(
    (requirement) =>
      requirement.surface === "desktop_cloud" &&
      requirement.authorization.includes("workspace_owner"),
  );
  assert.deepEqual(cloudEditor?.actions, [
    "update",
    "bind-agent",
    "unbind-agent",
  ]);
  assert.deepEqual(cloudOwner?.actions, [
    "add-member",
    "update-member-role",
    "remove-member",
  ]);

  assert.match(workspaces.judgment_rationale, /scope epoch/u);
  assert.match(workspaces.judgment_rationale, /context revision/u);
  assert.match(workspaces.judgment_rationale, /AbortSignal/u);
});

test("Project Blackboard records post and reply CRUD plus pin authority", () => {
  const blackboard = readCapability(
    "parity-capability-definitions.16-project-workspace.v2.json",
    "project-blackboard-dynamic-project-blackboard",
  );
  const memberActions = [
    "inspect-execution-diagnostics",
    "list-posts",
    "list-replies",
  ];
  const editorActions = [
    "create-post",
    "update-post",
    "delete-post",
    "pin-post",
    "unpin-post",
    "create-reply",
    "update-reply",
    "delete-reply",
  ];

  for (const action of [...memberActions, ...editorActions]) {
    assert.ok(blackboard.actions.includes(action), `missing ${action}`);
    assert.ok(blackboard.web_actions.includes(action), `missing Web ${action}`);
  }

  assert.deepEqual(
    contractKeys(blackboard, "web").filter((contract) =>
      contract.includes("/blackboard/posts"),
    ),
    [
      "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts",
      "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts",
      "PATCH /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}",
      "DELETE /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}",
      "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/pin",
      "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/unpin",
      "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies",
      "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies",
      "PATCH /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies/{reply_id}",
      "DELETE /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies/{reply_id}",
    ],
  );
  assert.ok(
    contractKeys(blackboard, "web").includes(
      "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/execution-diagnostics",
    ),
  );

  const webRequirements = blackboard.permission_requirements.filter(
    (requirement) => requirement.surface === "web",
  );
  const workspaceMember = webRequirements.find((requirement) =>
    requirement.authorization.includes("workspace_member"),
  );
  const workspaceEditor = webRequirements.find((requirement) =>
    requirement.authorization.includes("workspace_editor"),
  );
  for (const action of memberActions) {
    assert.ok(workspaceMember?.actions.includes(action));
  }
  for (const action of editorActions) {
    assert.ok(workspaceEditor?.actions.includes(action));
  }
});

test("Project Blackboard Cloud actions match the native discussion UI", () => {
  const blackboard = readCapability(
    "parity-capability-definitions.16-project-workspace.v2.json",
    "project-blackboard-dynamic-project-blackboard",
  );
  const cloudActions = [
    "inspect-execution-diagnostics",
    "list-posts",
    "create-post",
    "pin-post",
    "unpin-post",
    "create-reply",
  ];
  for (const action of cloudActions) {
    assert.ok(
      blackboard.cloud_actions.includes(action),
      `missing Cloud ${action}`,
    );
  }
  for (const action of [
    "update-post",
    "delete-post",
    "update-reply",
    "delete-reply",
  ]) {
    assert.equal(
      blackboard.cloud_actions.includes(action),
      false,
      `Cloud must not expose non-UI action ${action}`,
    );
  }
  for (const entry of [
    "agi-stack/apps/desktop/src/features/workspace/httpWorkspaceCollaborationClient.ts",
    "agi-stack/apps/desktop/src/features/workspace/workspaceCollaborationHttpMutations.ts",
  ]) {
    assert.ok(blackboard.cloud_entries.includes(entry), `missing ${entry}`);
  }
  const cloudContracts = contractKeys(blackboard, "desktop_cloud");
  for (const contract of [
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/authority",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/execution-diagnostics",
    "GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts",
    "POST /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/mutations",
  ]) {
    assert.ok(cloudContracts.includes(contract), `missing Cloud ${contract}`);
  }
  const cloudPermissionActions = blackboard.permission_requirements
    .filter((requirement) => requirement.surface === "desktop_cloud")
    .flatMap((requirement) => requirement.actions);
  for (const action of cloudActions) {
    assert.ok(
      cloudPermissionActions.includes(action),
      `missing Cloud permission for ${action}`,
    );
  }
});

test("Project Schema records client-side JSON copy and download export", () => {
  const schema = readCapability(
    "parity-capability-definitions.19-project-knowledge-configuration.v2.json",
    "project-project-schema",
  );
  const projectMember = schema.permission_requirements.find(
    (requirement) =>
      requirement.surface === "web" &&
      requirement.authorization.includes("project_member"),
  );

  assert.ok(schema.actions.includes("export"));
  assert.ok(schema.web_actions.includes("export"));
  assert.ok(projectMember?.actions.includes("export"));
  assert.match(schema.judgment_rationale, /copy/u);
  assert.match(schema.judgment_rationale, /download/u);
  assert.match(schema.judgment_rationale, /client-side/u);
});
