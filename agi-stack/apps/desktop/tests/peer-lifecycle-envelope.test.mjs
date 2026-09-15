import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
const require = createRequire(import.meta.url);
const base =
  process.env.PEER_TEST_DIST ??
  "/tmp/agistack-desktop-test-dist/apps/desktop/src";
const { normalizeSubagentLifecycleEnvelope } = require(
  `${base}/hooks/subagentLifecycleEnvelope.js`,
);
const { timelineItemFromSocketEvent } = require(
  `${base}/features/chat/appTimelineEventModel.js`,
);
const { mergeConversationTimelineItems } = require(
  `${base}/features/chat/chatTimelineModel.js`,
);
const { buildSessionAgentTree } = require(
  `${base}/features/session/sessionAgentTreeModel.js`,
);
const scope = { mode: "cloud", tenantId: "tenant", projectId: "project" };
const terminal = (run = "child-run") => ({
  type: "agent_lifecycle",
  tenant_id: "tenant",
  project_id: "project",
  conversation_id: "parent",
  data: {
    type: "agent_completed",
    event_time_us: 2000000,
    event_counter: 12,
    data: {
      agent_id: "agent",
      parent_agent_id: "parent-agent",
      session_id: "child",
      child_session_id: "child",
      parent_session_id: "parent",
      child_run_id: run,
      spawn_id: "spawn",
      status: "failed",
      success: false,
      result: "",
      artifacts: [],
      lifecycle_event_id: `peer-terminal:${run}`,
    },
  },
});
test("peer terminal reaches an existing parent card without advancing parent cursor", () => {
  const event = normalizeSubagentLifecycleEnvelope(terminal(), scope);
  assert.equal(event.type, "agent_completed");
  assert.equal(event.run_id, undefined);
  assert.equal(event.data.child_run_id, "child-run");
  assert.equal(event.event_counter, undefined);
  const item = timelineItemFromSocketEvent(event);
  assert.ok(item);
  const spawn = timelineItemFromSocketEvent({
    type: "agent_spawned",
    event_time_us: 1000000,
    event_counter: 1,
    data: {
      agent_id: "agent",
      parent_agent_id: "parent-agent",
      child_session_id: "child",
    },
  });
  const tree = buildSessionAgentTree([spawn, item]);
  assert.equal(tree.roots[0].status, "failed");
  assert.equal(
    item.id,
    normalizeSubagentLifecycleEnvelope(terminal(), scope).lifecycle_event_id,
  );
  const hydrated = {
    ...item,
    id: "agent_completed-2000000-12",
    eventCounter: 12,
    cursorSource: undefined,
  };
  assert.equal(mergeConversationTimelineItems([item], [hydrated]).length, 1);
  assert.notEqual(
    event.event_id,
    normalizeSubagentLifecycleEnvelope(terminal("later-turn"), scope).event_id,
  );
});
test("peer lifecycle rejects scope, identity and terminal contradictions", () => {
  for (const change of [
    (e) => (e.project_id = "other"),
    (e) => (e.data.data.child_run_id = ""),
    (e) => (e.data.data.session_id = "sibling"),
    (e) => (e.data.data.success = true),
    (e) => (e.data.type = "subagent_completed"),
    (e) => (e.data.data.status = "running"),
    (e) => (e.conversation_id = "other"),
    (e) => (e.data.event_counter = -1),
  ]) {
    const e = terminal();
    change(e);
    assert.equal(normalizeSubagentLifecycleEnvelope(e, scope), null);
  }
  assert.equal(
    normalizeSubagentLifecycleEnvelope(terminal(), { ...scope, mode: "local" }),
    null,
  );
});
test("actual SQL history and project notification recover as one peer terminal", async () => {
  const { readFileSync } = await import("node:fs");
  const { envelope, history } = JSON.parse(
    readFileSync(
      new URL(
        "./fixtures/peer-terminal-domain-projection.json",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  const context = {
    mode: "cloud",
    tenantId: envelope.tenant_id,
    projectId: envelope.project_id,
  };
  const live = timelineItemFromSocketEvent(
    normalizeSubagentLifecycleEnvelope(envelope, context),
  );
  assert.equal(live.id, history[0].id);
  const merged = mergeConversationTimelineItems([live], history);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].payload.child_run_id, envelope.data.data.child_run_id);
});
