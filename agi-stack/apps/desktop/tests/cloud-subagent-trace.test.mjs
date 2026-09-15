import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
const require = createRequire(import.meta.url);
const base = "/tmp/agistack-desktop-test-dist/apps/desktop";
const { projectCloudSubagentTrace, mergeCloudSubagentTraceItems } = require(
  `${base}/src/features/chat/cloudSubagentTraceModel.js`,
);
const { mergeLiveTimelineEvent, timelineCursorFromLast } = require(
  `${base}/src/features/chat/appTimelineEventModel.js`,
);
const { groupSubAgentTimelineItems } = require(
  `${base}/src/features/chat/subagentTimelineGroupModel.js`,
);
const { authorizeCloudSubagentTraceEndpoint } = require(
  `${base}/electron/main/cloudSubagentTraceEndpointPolicy.js`,
);
const row = (patch = {}) => ({
  run_id: "child",
  conversation_id: "conversation",
  subagent_name: "Reader",
  task: "Read current tools",
  status: "completed",
  created_at: "2026-09-14T00:00:00Z",
  ended_at: "2026-09-14T00:00:01Z",
  summary: "Actual completed result",
  metadata: {},
  tokens_used: 3,
  execution_time_ms: 1000,
  ...patch,
});
const project = (...rows) =>
  projectCloudSubagentTrace(
    { conversation_id: "conversation", runs: rows, total: rows.length },
    "conversation",
    Date.parse("2026-09-14T00:00:02Z"),
  );

test("retained trace restores actual status/result and never conversation cursors or control claims", () => {
  const items = project(
    row(),
    row({ run_id: "cancelled", status: "cancelled" }),
  );
  const groups = groupSubAgentTimelineItems(items).groups;
  assert.deepEqual(
    groups.map((g) => [g.runId, g.status]),
    [
      ["child", "success"],
      ["cancelled", "killed"],
    ],
  );
  assert.equal(groups[0].summary, "Actual completed result");
  assert.equal(groups[0].task, "Read current tools");
  assert.equal(timelineCursorFromLast(items), null);
  assert.equal(items[0].payload.control_registered, undefined);
  assert.deepEqual(project(), []);
});

test("scope, duplicate identity, truncated total, invalid statuses and values reject atomically", () => {
  for (const invalid of [
    row({ conversation_id: "foreign" }),
    row({ status: "unknown" }),
    row({ run_id: "" }),
    row({ created_at: "bad" }),
    row({ tokens_used: -1 }),
    row({ ended_at: 3 }),
  ]) {
    assert.throws(() => project(invalid));
  }
  assert.throws(() => project(row(), row()));
  assert.throws(() =>
    projectCloudSubagentTrace(
      { conversation_id: "foreign", runs: [], total: 0 },
      "conversation",
      1,
    ),
  );
  assert.throws(() =>
    projectCloudSubagentTrace(
      { conversation_id: "conversation", runs: [row()], total: 2 },
      "conversation",
      1,
    ),
  );
});

test("snapshot and actual lifecycle updates share one execution card without terminal regression", () => {
  let items = project(row({ status: "running", ended_at: null }));
  const live = (type, payload = {}) => ({
    type,
    lifecycle_event_id: `event:${type}`,
    timeline_cursor_source: "project_lifecycle",
    event_time_us: Date.parse("2026-09-14T00:00:03Z") * 1000,
    data: {
      conversation_id: "conversation",
      run_id: "child",
      execution_id: "child",
      subagent_name: "Reader",
      ...payload,
    },
  });
  items = mergeLiveTimelineEvent(
    items,
    live("subagent_run_completed", {
      status: "completed",
      summary: "new result",
    }),
  );
  items = mergeLiveTimelineEvent(
    items,
    live("subagent_started", { status: "running" }),
  );
  assert.equal(items.length, 1);
  assert.equal(groupSubAgentTimelineItems(items).groups[0].status, "success");
  assert.equal(
    groupSubAgentTimelineItems(items).groups[0].summary,
    "new result",
  );
  items = mergeCloudSubagentTraceItems(
    items,
    project(row({ status: "running", ended_at: null })),
  );
  assert.equal(items.length, 1);
  assert.equal(groupSubAgentTimelineItems(items).groups[0].status, "success");
  const firstLive = mergeLiveTimelineEvent(
    [],
    live("subagent_started", { status: "running" }),
  );
  const complete = mergeCloudSubagentTraceItems(firstLive, project(row()));
  assert.equal(complete.length, 1);
  assert.equal(
    groupSubAgentTimelineItems(complete).groups[0].status,
    "success",
  );
  const parent = { id: "parent", type: "act", eventTimeUs: 4, eventCounter: 7 };
  assert.ok(
    mergeCloudSubagentTraceItems([parent], project(row())).includes(parent),
  );
  assert.deepEqual(
    mergeCloudSubagentTraceItems([parent, ...project(row())], []),
    [parent],
    "expired registry snapshots are not retained as invented history",
  );
  const olderTerminal = mergeLiveTimelineEvent([], {
    ...live("subagent_run_completed", { summary: "old notification" }),
    event_time_us: 1,
  });
  assert.equal(
    groupSubAgentTimelineItems(
      mergeCloudSubagentTraceItems(olderTerminal, project(row())),
    ).groups[0].summary,
    "Actual completed result",
  );
});

test("trace gateway permits only exact read and requires conversation resource observation", () => {
  const target = new URL(
    "https://api.invalid/api/v1/agent/trace/runs/conversation",
  );
  assert.deepEqual(
    authorizeCloudSubagentTraceEndpoint({ method: "GET" }, target),
    {
      kind: "project",
      tenantId: null,
      projectId: null,
      workspaceId: null,
      conversationId: "conversation",
    },
  );
  for (const request of [
    { method: "POST" },
    { method: "GET", body: {} },
    { method: "GET", mutation: {} },
  ]) {
    assert.equal(authorizeCloudSubagentTraceEndpoint(request, target), null);
  }
  for (const path of [
    "conversation?limit=200",
    "conversation/extra",
    "%2Fforeign",
    "",
  ]) {
    assert.equal(
      authorizeCloudSubagentTraceEndpoint(
        { method: "GET" },
        new URL(`https://api.invalid/api/v1/agent/trace/runs/${path}`),
      ),
      null,
    );
  }
});
