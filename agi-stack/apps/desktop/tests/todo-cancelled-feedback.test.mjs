import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
require.extensions[".css"] = () => {};
const root = "/tmp/agistack-desktop-test-dist/src";
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const { I18nProvider } = require(`${root}/i18n.js`);
const { TaskChecklist } = require(`${root}/features/chat/TaskChecklist.js`);
const { timelineItemFromSocketEvent } = require(
  `${root}/features/chat/appTimelineEventModel.js`,
);
const { todoChecklistFromTimeline, todoChecklistStats } = require(
  `${root}/features/chat/todoChecklistModel.js`,
);
const { sessionPlanTaskStatusTranslationKey } = require(
  `${root}/features/session/sessionPlanApprovalModel.js`,
);
const { pairToolCallItems, toolCallPairStatus } = require(
  `${root}/features/chat/chatTimelineModel.js`,
);

function event(type, data, counter) {
  return timelineItemFromSocketEvent({
    type,
    data,
    time_us: counter * 1000,
    counter,
  });
}

test("native Stop and rejected update do not manufacture cancellation; persisted progress does", () => {
  const initial = event(
    "task_list_updated",
    {
      tasks: [
        { id: "native", content: "Desktop work", status: "in_progress" },
        { id: "failure", content: "Actual failed work", status: "failed" },
        {
          id: "finished",
          content: "Finished independent work",
          status: "completed",
        },
      ],
    },
    1,
  );
  const stopped = event(
    "observe",
    {
      tool_name: "computer_get_app_state",
      call_id: "native-call",
      control_outcome: "user_stopped",
      status: "cancelled",
    },
    2,
  );
  const attempt = event(
    "act",
    {
      tool_name: "todowrite",
      call_id: "todo-call",
      tool_input: {
        action: "update",
        todos: [{ status: "cancelled" }, { id: "native" }],
      },
    },
    3,
  );
  const rejected = event(
    "observe",
    {
      tool_name: "todowrite",
      call_id: "todo-call",
      status: "error",
      error: "invalid_tool_arguments: todo_id is required",
    },
    4,
  );
  const timeline = [initial, stopped, attempt, rejected];
  assert.deepEqual(
    todoChecklistFromTimeline(timeline).map((item) => item.status),
    ["in_progress", "failed", "completed"],
  );
  const cancelled = event(
    "task_updated",
    { task_id: "native", status: "cancelled" },
    5,
  );
  const items = todoChecklistFromTimeline([...timeline, cancelled]);
  assert.deepEqual(
    items.map((item) => item.status),
    ["cancelled", "failed", "completed"],
  );
  assert.deepEqual(todoChecklistStats(items), {
    total: 3,
    active: 0,
    failed: 1,
    completed: 1,
    percent: 33,
  });
  assert.equal(
    sessionPlanTaskStatusTranslationKey("cancelled"),
    "session.planTaskState.cancelled",
  );

  const previousWindow = globalThis.window;
  try {
    for (const [locale, cancelledLabel, failedLabel] of [
      ["en", "Cancelled", "Failed"],
      ["zh-CN", "已取消", "失败"],
    ]) {
      globalThis.window = { localStorage: { getItem: () => locale } };
      const html = renderToStaticMarkup(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(TaskChecklist, { items }),
        ),
      );
      assert.match(html, /class="task-checklist-item status-cancelled"/);
      assert.match(html, /class="task-checklist-item status-failed"/);
      assert.ok(html.includes(cancelledLabel));
      assert.ok(html.includes(failedLabel));
      assert.doesNotMatch(html, /chat\.todoChecklist\.status\./);
      assert.match(html, /aria-valuenow="33"/);
    }
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});

test("Pause, a fresh observation after Resume, and Stop preserve task state until persisted cancellation", () => {
  const timeline = [
    event(
      "task_list_updated",
      {
        tasks: [
          { id: "native", content: "Desktop work", status: "in_progress" },
          { id: "other", content: "Independent work", status: "completed" },
        ],
      },
      1,
    ),
  ];
  for (const [callId, outcome, output] of [
    ["paused-call", "user_paused", null],
    ["fresh-call", null, { observation_id: "fresh-after-resume" }],
    ["stopped-call", "user_stopped", null],
  ]) {
    timeline.push(
      event(
        "act",
        { tool_name: "computer_get_app_state", call_id: callId },
        timeline.length + 1,
      ),
    );
    timeline.push(
      event(
        "observe",
        {
          tool_name: "computer_get_app_state",
          call_id: callId,
          status: outcome ? "cancelled" : "success",
          control_outcome: outcome,
          error: null,
          observation: output ?? {
            type: "computer_use_control",
            status: outcome,
            retry_allowed: false,
          },
        },
        timeline.length + 1,
      ),
    );
    assert.deepEqual(
      todoChecklistFromTimeline(timeline).map((item) => item.status),
      ["in_progress", "completed"],
    );
  }
  assert.deepEqual(
    pairToolCallItems(
      timeline.filter((item) => item.type === "act" || item.type === "observe"),
    ).map(toolCallPairStatus),
    ["paused", "complete", "stopped"],
  );
  timeline.push(
    event(
      "task_updated",
      { task: { id: "native", status: "cancelled" } },
      timeline.length + 1,
    ),
  );
  const items = todoChecklistFromTimeline(timeline);
  assert.deepEqual(
    items.map((item) => item.status),
    ["cancelled", "completed"],
  );
  assert.deepEqual(todoChecklistStats(items), {
    total: 2,
    active: 0,
    failed: 0,
    completed: 1,
    percent: 50,
  });
});
