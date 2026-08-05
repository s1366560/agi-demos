import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  resolveSubAgentControlAuthority,
  subAgentGroupControlAvailability,
} = require("/tmp/agistack-desktop-test-dist/src/features/chat/subagentControlAuthorityModel.js");

const conversation = {
  id: "conversation-1",
  participant_agents: ["reviewer-1"],
};
const run = {
  id: "parent-run-1",
  conversation_id: "conversation-1",
  status: "running",
  revision: 9,
};
const group = {
  runId: "child-run-1",
  subagentId: "reviewer-1",
  status: "running",
};

test("Cloud SubAgent controls require active revision-bound run authority", () => {
  assert.deepEqual(
    resolveSubAgentControlAuthority("cloud", conversation, run),
    {
      availability: "available",
      reasonCode: null,
      allowedActions: ["steer", "kill_run"],
      authorityRevision: 9,
      conversationId: "conversation-1",
      participantAgentIds: ["reviewer-1"],
    },
  );
  assert.deepEqual(
    resolveSubAgentControlAuthority("local", conversation, run),
    {
      availability: "unavailable",
      reasonCode: "subagent_control_local_unavailable",
      allowedActions: [],
      authorityRevision: null,
      conversationId: null,
      participantAgentIds: ["reviewer-1"],
    },
  );
});

test("SubAgent control fails closed for missing execution identity and roster mismatch", () => {
  const authority = resolveSubAgentControlAuthority("cloud", conversation, run);
  assert.equal(
    subAgentGroupControlAvailability(authority, { ...group, runId: "" })
      .reasonCode,
    "subagent_control_execution_id_unavailable",
  );
  assert.equal(
    subAgentGroupControlAvailability(authority, {
      ...group,
      subagentId: "not-in-roster",
    }).reasonCode,
    "subagent_control_roster_denied",
  );
  assert.equal(
    subAgentGroupControlAvailability(authority, { ...group, status: "success" })
      .reasonCode,
    "subagent_control_execution_terminal",
  );
});

test("Queued parent runs only allow kill and steered child runs retain both actions", () => {
  const queued = resolveSubAgentControlAuthority("cloud", conversation, {
    ...run,
    status: "queued",
  });
  assert.deepEqual(
    subAgentGroupControlAvailability(queued, group).allowedActions,
    ["kill_run"],
  );

  const running = resolveSubAgentControlAuthority("cloud", conversation, run);
  assert.deepEqual(
    subAgentGroupControlAvailability(running, { ...group, status: "steered" })
      .allowedActions,
    ["steer", "kill_run"],
  );
});
