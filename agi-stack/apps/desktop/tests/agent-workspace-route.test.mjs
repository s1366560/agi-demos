import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const {
  AGENT_WORKSPACE_ROUTE_ID,
  createAgentWorkspaceRouteModuleLoader,
} = require("/tmp/agistack-desktop-test-dist/src/features/agent-workspace/agentWorkspaceRouteModule.js");
const {
  agentWorkspaceCapability,
} = require("/tmp/agistack-desktop-test-dist/src/features/agent-workspace/agentWorkspaceCapability.js");
const {
  DEFAULT_CONFIG,
} = require("/tmp/agistack-desktop-test-dist/src/types.js");

const cloudConfig = Object.freeze({
  ...DEFAULT_CONFIG,
  mode: "cloud",
  tenantId: "tenant-1",
  projectId: "project-1",
  workspaceId: "workspace-1",
});
const localConfig = Object.freeze({
  ...cloudConfig,
  mode: "local",
});

test("Agent Workspace route module owns the canonical native-equivalent identity", async () => {
  assert.equal(
    AGENT_WORKSPACE_ROUTE_ID,
    "agent-workspace-tenant-agent-workspace",
  );
  const module = await createAgentWorkspaceRouteModuleLoader()();
  assert.deepEqual(
    {
      routeId: module.routeId,
      capability: module.capability,
      localPolicy: module.localPolicy,
      disposition: module.disposition,
      availability: module.availability,
      reasonCode: module.reasonCode,
    },
    {
      routeId: AGENT_WORKSPACE_ROUTE_ID,
      capability: AGENT_WORKSPACE_ROUTE_ID,
      localPolicy: "native_equivalent",
      disposition: "implemented",
      availability: "available",
      reasonCode: null,
    },
  );

  const markup = renderToStaticMarkup(
    React.createElement(module.Surface, {
      module,
      context: { tenantId: "tenant-1" },
      content: React.createElement(
        "article",
        { "data-session-canvas": true },
        "Session canvas",
      ),
    }),
  );
  assert.equal(module.contentPolicy, "route_content");
  assert.match(markup, /data-agent-workspace-route-surface="true"/u);
  assert.match(markup, /data-tenant-id="tenant-1"/u);
  assert.match(markup, /data-session-canvas="true"/u);
  assert.doesNotMatch(markup, /aria-hidden="true"/u);
});

test("Agent Workspace capability declares Cloud and Local workflow authority", () => {
  assert.deepEqual(agentWorkspaceCapability(cloudConfig), {
    availability: "available",
    reason_code: null,
    service_version: "0.1.0",
    contract_version: "3.0.0",
    allowed_actions: [
      "view",
      "switch-project",
      "switch-workspace",
      "create-session",
      "send-message",
      "queue-message",
      "steer-message",
      "respond-hitl",
      "attach-file",
      "review-plan",
      "review-usage",
      "review-changes",
      "open-activity",
      "open-my-work",
      "manage-roster",
      "manage-subagents",
    ],
    scope: {
      tenant_id: "tenant-1",
      project_id: "project-1",
      workspace_id: "workspace-1",
      instance_id: null,
    },
    authority_revision: null,
  });
  assert.deepEqual(agentWorkspaceCapability(localConfig), {
    availability: "degraded",
    reason_code: "local_cloud_agent_authority_unavailable",
    service_version: "0.1.0",
    contract_version: "3.0.0",
    allowed_actions: [
      "view",
      "switch-project",
      "switch-workspace",
      "create-session",
      "send-message",
      "respond-hitl",
      "attach-file",
      "review-plan",
      "manage-roster",
      "manage-subagents",
    ],
    scope: {
      tenant_id: "tenant-1",
      project_id: "project-1",
      workspace_id: "workspace-1",
      instance_id: null,
    },
    authority_revision: null,
  });
});

test("Agent Workspace capability fails closed when tenant scope is unavailable", () => {
  assert.deepEqual(
    agentWorkspaceCapability({
      ...localConfig,
      tenantId: " tenant-1 ",
    }),
    {
      availability: "unavailable",
      reason_code: "agent_workspace_scope_unavailable",
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: {
        tenant_id: null,
        project_id: "project-1",
        workspace_id: "workspace-1",
        instance_id: null,
      },
      authority_revision: null,
    },
  );
});
