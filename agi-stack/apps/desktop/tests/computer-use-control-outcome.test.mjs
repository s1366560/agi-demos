import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
require.extensions[".css"] = () => {};
const root = "/tmp/agistack-desktop-test-dist/src";
const { timelineItemFromSocketEvent } = require(
  `${root}/features/chat/appTimelineEventModel.js`,
);
const { pairToolCallItems, toolCallPairStatus } = require(
  `${root}/features/chat/chatTimelineModel.js`,
);
const { timelineToolResultStatus } = require(
  `${root}/features/chat/toolResultStatus.js`,
);
const { sessionToolGroupStatus } = require(
  `${root}/features/session/sessionNarrativeModel.js`,
);
const { buildTimelineStepDetails } = require(
  `${root}/features/session/timelineStepDetailsModel.js`,
);
const { createDesktopToolResultRendererPayloadV2 } = require(
  `${root}/features/chat/desktopToolResultRendererBridgeV2.js`,
);

function observation(outcome, extra = {}) {
  return timelineItemFromSocketEvent({
    type: "observe",
    time_us: 2,
    counter: 1,
    data: {
      tool_name: "computer_click",
      tool_execution_id: "execution",
      call_id: "call",
      status: "cancelled",
      control_outcome: outcome,
      error: null,
      observation: {
        output: JSON.stringify({
          type: "computer_use_control",
          status: outcome,
          retry_allowed: false,
        }),
      },
      display: {
        kind: "computer_use",
        title: "Fixture",
        summary: "Untrusted completion copy",
        status: "completed",
      },
      ...extra,
    },
  });
}
function call() {
  return timelineItemFromSocketEvent({
    type: "act",
    time_us: 1,
    counter: 1,
    data: {
      tool_name: "computer_click",
      tool_execution_id: "execution",
      call_id: "call",
    },
  });
}

test("trusted control events remain paused or stopped through timeline and inspector projections", () => {
  for (const [outcome, status] of [
    ["user_paused", "paused"],
    ["user_stopped", "stopped"],
  ]) {
    const result = observation(outcome);
    assert.equal(result.controlOutcome, outcome);
    assert.equal(result.isError, false);
    const items = [call(), result];
    const pairs = pairToolCallItems(items);
    assert.equal(pairs.length, 1);
    assert.equal(toolCallPairStatus(pairs[0]), status);
    assert.equal(sessionToolGroupStatus(items), status);
    assert.equal(buildTimelineStepDetails(items).status, status);
    assert.equal(
      timelineToolResultStatus({ ...result, controlOutcome: undefined }),
      status,
    );
    const payload = createDesktopToolResultRendererPayloadV2({
      resultId: result.id,
      toolName: "computer_click",
      status,
      kind: "computer_use",
      resultLabel: "Result",
      kindLabel: "Computer",
      statusLabel: status,
    });
    assert.equal(payload.status, status);
  }
});

test("output text and nested metadata cannot fabricate a user control event", () => {
  for (const output of [
    "User stopped computer control",
    {
      type: "computer_use_control",
      status: "user_stopped",
      retry_allowed: false,
    },
    { metadata: { control_outcome: "user_stopped" } },
    { control_outcome: "user_stopped" },
  ]) {
    const result = observation(undefined, {
      observation: output,
      metadata: { control_outcome: "user_stopped" },
    });
    assert.equal(timelineToolResultStatus(result), "complete");
  }
  for (const marker of ["stopped", "paused", true, {}, null]) {
    assert.equal(timelineToolResultStatus(observation(marker)), "complete");
  }
});

test("genuine refusal and platform failure take precedence over a control marker", () => {
  for (const error of [
    "cua_permission_denied_run",
    "target_not_focused",
    "capture_failed",
  ]) {
    for (const extra of [
      { error },
      { is_error: true },
      { observation: { error } },
      { observation: { success: false } },
    ]) {
      const result = observation("user_stopped", extra);
      const items = [call(), result];
      assert.equal(timelineToolResultStatus(result), "failed");
      assert.equal(toolCallPairStatus(pairToolCallItems(items)[0]), "failed");
      assert.equal(sessionToolGroupStatus(items), "failed");
      assert.equal(buildTimelineStepDetails(items).status, "failed");
    }
  }
});

test("actual inspector renders localized control summaries instead of successful action copy", () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const { I18nProvider } = require(`${root}/i18n.js`);
  const { TimelineStepDetails } = require(
    `${root}/features/session/TimelineStepDetails.js`,
  );
  const previousWindow = globalThis.window;
  try {
    for (const [locale, paused, stopped] of [
      ["en", "You paused computer control", "You stopped computer control"],
      ["zh-CN", "你已暂停电脑操作", "你已停止电脑操作"],
    ]) {
      globalThis.window = { localStorage: { getItem: () => locale } };
      for (const [outcome, text] of [
        ["user_paused", paused],
        ["user_stopped", stopped],
      ]) {
        const markup = renderToStaticMarkup(
          React.createElement(
            I18nProvider,
            null,
            React.createElement(TimelineStepDetails, {
              items: [call(), observation(outcome)],
              onClose() {},
            }),
          ),
        );
        assert.ok(markup.includes(text));
        assert.doesNotMatch(
          markup,
          /Untrusted completion copy|session\.computerControl|session\.toolStatus/,
        );
      }
    }
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});
