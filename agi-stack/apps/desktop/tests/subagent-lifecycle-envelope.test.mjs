import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const base = "/tmp/agistack-desktop-test-dist/apps/desktop/src";
const { normalizeSubagentLifecycleEnvelope } = require(
  `${base}/hooks/subagentLifecycleEnvelope.js`,
);
const { eventCursor, socketEventKey } = require(
  `${base}/hooks/useAgentSocket.js`,
);
const {
  timelineItemFromSocketEvent,
  agentTaskUpdateFromSocketEvent,
  timelineCursorFromFirst,
  timelineCursorFromLast,
} = require(`${base}/features/chat/appTimelineEventModel.js`);
const { groupSubAgentTimelineItems } = require(
  `${base}/features/chat/subagentTimelineGroupModel.js`,
);
const scope = { mode: "cloud", tenantId: "tenant", projectId: "project" };
// Serialized by the production Python SubAgentKilledEvent.to_event_dict().
const killedDomainEvent = JSON.parse(
  readFileSync(
    new URL("./fixtures/subagent-killed-domain-event.json", import.meta.url),
    "utf8",
  ),
);
const envelope = (type, data = {}, nested = false) => ({
  type: "subagent_lifecycle",
  tenant_id: "tenant",
  project_id: "project",
  timestamp: "2026-09-14T07:00:00.000Z",
  data: {
    type,
    tenant_id: "tenant",
    project_id: "project",
    ...(nested
      ? {
          data: {
            conversation_id: "conversation",
            run_id: "child-1",
            subagent_name: "Reader",
            ...data,
          },
        }
      : {
          conversation_id: "conversation",
          run_id: "child-1",
          subagent_name: "Reader",
          ...data,
        }),
  },
});

test("real nested spawning and flat completion envelopes form one child lifecycle", () => {
  const start = normalizeSubagentLifecycleEnvelope(
    envelope("subagent_spawning", {}, true),
    scope,
  );
  const end = normalizeSubagentLifecycleEnvelope(
    envelope("subagent_ended", {
      status: "completed",
      summary: "child result",
    }),
    scope,
  );
  assert.equal(start.conversation_id, "conversation");
  assert.equal(end.data.execution_id, "child-1");
  assert.equal(
    eventCursor(start),
    null,
    "project lifecycle cannot advance conversation replay cursor",
  );
  assert.equal(
    agentTaskUpdateFromSocketEvent(end),
    null,
    "child completion does not finish parent",
  );
  const grouped = groupSubAgentTimelineItems(
    [start, end].map(timelineItemFromSocketEvent),
  );

  assert.equal(grouped.groups.length, 1);
  assert.equal(grouped.groups[0].status, "success");
  assert.equal(grouped.groups[0].runId, "child-1");
  assert.equal(grouped.groups[0].summary, "child result");
});

test("ended notifications with timed_out and pending statuses still project", () => {
  const timedOut = normalizeSubagentLifecycleEnvelope(
    envelope("subagent_ended", { status: "timed_out" }),
    scope,
  );
  assert.equal(timedOut.type, "subagent_run_failed");
  assert.equal(timedOut.data.status, "timed_out");
  assert.equal(timedOut.data.lifecycle_type, "subagent_ended");
  const pending = normalizeSubagentLifecycleEnvelope(
    envelope("subagent_ended", { status: "pending" }),
    scope,
  );
  assert.equal(pending.type, "subagent_queued");
  assert.equal(pending.data.status, "pending");
  // Unknown statuses still fail closed.
  assert.equal(
    normalizeSubagentLifecycleEnvelope(
      envelope("subagent_ended", { status: "teleported" }),
      scope,
    ),
    null,
  );
});

test("same timestamp siblings retain distinct identities and replay keys", () => {
  const a = normalizeSubagentLifecycleEnvelope(
    envelope("subagent_spawned"),
    scope,
  );
  const b = normalizeSubagentLifecycleEnvelope(
    envelope("subagent_spawned", { run_id: "child-2" }),
    scope,
  );
  assert.notEqual(socketEventKey(a), socketEventKey(b));
  assert.notEqual(
    timelineItemFromSocketEvent(a).id,
    timelineItemFromSocketEvent(b).id,
  );
  assert.equal(
    socketEventKey(a),
    socketEventKey(
      normalizeSubagentLifecycleEnvelope(envelope("subagent_spawned"), scope),
    ),
  );
  assert.equal(
    groupSubAgentTimelineItems([a, b].map(timelineItemFromSocketEvent)).groups
      .length,
    2,
  );
});

test("cancelled and failed are terminal but unknown status never becomes success", () => {
  for (const [status, expected] of [
    ["cancelled", "killed"],
    ["failed", "error"],
  ]) {
    const event = normalizeSubagentLifecycleEnvelope(
      envelope("subagent_ended", { status, error: "actual reason" }),
      scope,
    );
    const group = groupSubAgentTimelineItems([
      timelineItemFromSocketEvent(event),
    ]).groups[0];
    assert.equal(group.status, expected);
  }
  assert.equal(
    normalizeSubagentLifecycleEnvelope(
      envelope("subagent_ended", { status: "unknown" }),
      scope,
    ),
    null,
  );
});

test("production killed event accepts absent optional execution id but rejects conflicting identity", () => {
  const message = { ...envelope("subagent_killed"), data: killedDomainEvent };
  assert.equal(message.data.data.execution_id, null);
  const normalized = normalizeSubagentLifecycleEnvelope(message, scope);
  assert.ok(normalized);
  assert.equal(normalized.data.execution_id, "child-1");
  assert.equal(eventCursor(normalized), null);
  const projected = timelineItemFromSocketEvent(normalized);
  assert.equal(projected.cursorSource, "project_lifecycle");
  assert.equal(timelineCursorFromFirst([projected]), null);
  assert.equal(timelineCursorFromLast([projected]), null);
  const groups = groupSubAgentTimelineItems([
    timelineItemFromSocketEvent(normalized),
  ]).groups;
  assert.equal(groups.length, 1);
  assert.equal(groups[0].status, "killed");
  assert.equal(groups[0].runId, "child-1");
  for (const executionId of ["another-child", "", 0, false, {}]) {
    assert.equal(
      normalizeSubagentLifecycleEnvelope(
        {
          ...message,
          data: {
            ...killedDomainEvent,
            data: { ...killedDomainEvent.data, execution_id: executionId },
          },
        },
        scope,
      ),
      null,
    );
  }
});

test("foreign scopes, conflicting identities and missing execution IDs fail closed", () => {
  for (const change of [
    (event) => {
      event.tenant_id = "foreign";
    },
    (event) => {
      event.project_id = "foreign";
    },
    (event) => {
      event.data.project_id = "foreign";
    },
    (event) => {
      event.data.run_id = "";
      event.data.subagent_id = "configuration-id";
    },
    (event) => {
      event.data.execution_id = "different-execution";
    },
    (event) => {
      event.data.conversation_id = "";
    },
    (event) => {
      event.data.data = { ...event.data, run_id: "conflicting-child" };
    },
  ]) {
    const event = envelope("subagent_spawned");
    change(event);
    assert.equal(normalizeSubagentLifecycleEnvelope(event, scope), null);
  }
  assert.equal(
    normalizeSubagentLifecycleEnvelope(envelope("subagent_spawned"), {
      ...scope,
      mode: "local",
    }),
    null,
  );
  const ordinary = { type: "complete", conversation_id: "parent" };
  assert.equal(normalizeSubagentLifecycleEnvelope(ordinary, scope), ordinary);
});

test('actual Redis to WebSocket frames and retained trace produce one completed child card', () => {
  const frames = JSON.parse(readFileSync(new URL('./fixtures/cloud-subagent-lifecycle-complete.json', import.meta.url), 'utf8'));
  const trace = JSON.parse(readFileSync(new URL('./fixtures/cloud-subagent-trace-complete.json', import.meta.url), 'utf8'));
  const { projectCloudSubagentTrace, mergeCloudSubagentTraceItems } = require(`${base}/features/chat/cloudSubagentTraceModel.js`);
  const actualScope = { mode: 'cloud', tenantId: frames[0].tenant_id, projectId: frames[0].project_id };
  const normalized = frames.map((frame) => normalizeSubagentLifecycleEnvelope(frame, actualScope));
  assert.deepEqual(normalized.map((event) => event.type), ['subagent_spawning', 'subagent_started', 'subagent_run_completed']);
  assert.equal(new Set(normalized.map(socketEventKey)).size, 3);
  assert.ok(normalized.every((event) => eventCursor(event) === null));
  const projected = normalized.map(timelineItemFromSocketEvent);
  assert.equal(timelineCursorFromLast(projected), null);
  const groups = groupSubAgentTimelineItems(projected).groups;
  assert.equal(groups.length, 1);
  assert.equal(groups[0].runId, trace.runs[0].run_id);
  assert.equal(groups[0].status, 'success');
  assert.equal(groups[0].summary, trace.runs[0].summary);
  const restored = projectCloudSubagentTrace(trace, trace.conversation_id, Date.now());
  const merged = mergeCloudSubagentTraceItems(projected, restored);
  assert.equal(merged.length, 1);
  assert.equal(groupSubAgentTimelineItems(merged).groups[0].runId, trace.runs[0].run_id);
  assert.equal(timelineCursorFromFirst(merged), null);
});
