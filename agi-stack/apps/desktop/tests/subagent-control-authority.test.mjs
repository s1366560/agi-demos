import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  resolveSubAgentControlAuthority,
  subAgentGroupControlAvailability,
} = require("/tmp/agistack-desktop-test-dist/src/features/chat/subagentControlAuthorityModel.js");
const {
  timelineItemFromSocketEvent,
} = require("/tmp/agistack-desktop-test-dist/src/features/chat/appTimelineEventModel.js");

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

test("SubAgent controls require active revision-bound run authority", () => {
  assert.deepEqual(
    resolveSubAgentControlAuthority("cloud", conversation, run),
    {
      availability: "unavailable",
      reasonCode: "cloud_child_control_snapshot_required",
      allowedActions: [],
      authorityRevision: null,
      conversationId: null,
      participantAgentIds: [],
    },
  );
  assert.deepEqual(
    resolveSubAgentControlAuthority("local", conversation, run),
    {
      availability: "available",
      reasonCode: null,
      allowedActions: ["steer", "kill_run"],
      authorityRevision: 9,
      conversationId: "conversation-1",
      participantAgentIds: [],
      registeredExecutions: [],
    },
  );
});

test("Local SubAgent controls bind actual registered execution identity to the current parent", () => {
  const started = {
    id: "child-started",
    type: "subagent_started",
    conversation_id: conversation.id,
    payload: {
      run_id: group.runId,
      subagent_id: group.subagentId,
      parent_run_id: run.id,
      parent_run_revision: run.revision,
      control_registered: true,
    },
  };
  const authority = resolveSubAgentControlAuthority(
    "local",
    conversation,
    run,
    [started],
  );
  assert.equal(
    subAgentGroupControlAvailability(authority, group).available,
    true,
  );
  const scopedLiveItem = timelineItemFromSocketEvent(started);
  const liveAuthority = resolveSubAgentControlAuthority(
    "local",
    conversation,
    run,
    [scopedLiveItem],
  );
  assert.equal(
    subAgentGroupControlAvailability(liveAuthority, group).available,
    true,
    "live timeline normalization already scopes the event and omits conversation_id",
  );
  assert.equal(
    subAgentGroupControlAvailability(authority, {
      ...group,
      runId: "previous-child",
    }).available,
    false,
  );
  assert.equal(
    subAgentGroupControlAvailability(authority, {
      ...group,
      subagentId: "other-agent",
    }).available,
    false,
  );
  for (const payload of [
    { ...started.payload, control_registered: false },
    { ...started.payload, parent_run_id: "previous-parent" },
    { ...started.payload, parent_run_revision: run.revision - 1 },
  ]) {
    const rejected = resolveSubAgentControlAuthority(
      "local",
      conversation,
      run,
      [{ ...started, payload }],
    );
    assert.equal(
      subAgentGroupControlAvailability(rejected, group).available,
      false,
    );
  }
  const staleConversation = resolveSubAgentControlAuthority(
    "local",
    conversation,
    run,
    [{ ...started, conversation_id: "other-conversation" }],
  );
  assert.equal(
    subAgentGroupControlAvailability(staleConversation, group).available,
    false,
  );
});

test("SubAgent control fails closed for missing execution identity and roster mismatch", () => {
  const authority = localAuthority(run);
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
    "subagent_control_execution_id_unavailable",
  );
  assert.equal(
    subAgentGroupControlAvailability(authority, { ...group, status: "success" })
      .reasonCode,
    "subagent_control_execution_terminal",
  );
});

test("Queued parent runs only allow kill and steered child runs retain both actions", () => {
  const queued = localAuthority({
    ...run,
    status: "queued",
  });
  assert.deepEqual(
    subAgentGroupControlAvailability(queued, group).allowedActions,
    ["kill_run"],
  );

  const running = localAuthority(run);
  assert.deepEqual(
    subAgentGroupControlAvailability(running, { ...group, status: "steered" })
      .allowedActions,
    ["steer", "kill_run"],
  );
});

function localAuthority(parent) {
  return resolveSubAgentControlAuthority('local', conversation, parent, [{
    id: 'start', type: 'subagent_started', conversation_id: conversation.id,
    payload: { control_registered: true, run_id: group.runId, subagent_id: group.subagentId,
      parent_run_id: parent.id, parent_run_revision: parent.revision },
  }]);
}
