import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  confirmPendingAgentRunMessageReceipt,
  buildHitlSocketMessage,
  canQueuePendingAgentRunMessage,
  createPendingAgentMessageQueue,
  conversationSubscriptionMessages,
  createAgentSocketContextState,
  agentSteerMessageOutcome,
  agentSteerSocketMessage,
  deliverSubAgentControlCommand,
  deliverAgentSteerMessage,
  deliverAgentStopSession,
  deliverAgentRunMessage,
  enqueuePendingAgentRunMessage,
  eventCursor,
  flushPendingAgentRunMessages,
  pendingAgentRunQueueScopeKey,
  reconnectDelay,
  resetAgentSocketContextState,
  transitionAgentSocketConversationSelection,
  socketEventKey,
  socketEventWindowSince,
  socketEventsSince,
  subAgentControlReceipt,
  subAgentControlSocketMessage,
} = require("/tmp/agistack-desktop-test-dist/src/hooks/useAgentSocket.js");

test("SubAgent control commands are revision-bound and fail closed", () => {
  const steer = subAgentControlSocketMessage({
    action: "steer",
    conversationId: " conversation-1 ",
    runId: " child-run-1 ",
    expectedRunRevision: 7,
    idempotencyKey: " control-1 ",
    instruction: " Check the failing contract first ",
  });
  assert.deepEqual(steer, {
    type: "steer",
    conversation_id: "conversation-1",
    run_id: "child-run-1",
    expected_run_revision: 7,
    idempotency_key: "control-1",
    instruction: "Check the failing contract first",
  });
  assert.deepEqual(
    subAgentControlSocketMessage({
      action: "kill_run",
      conversationId: "conversation-1",
      runId: "child-run-1",
      expectedRunRevision: 7,
      idempotencyKey: "control-2",
      cascade: true,
    }),
    {
      type: "kill_run",
      conversation_id: "conversation-1",
      run_id: "child-run-1",
      expected_run_revision: 7,
      idempotency_key: "control-2",
      cascade: true,
    },
  );
  assert.equal(
    subAgentControlSocketMessage({
      action: "steer",
      conversationId: "conversation-1",
      runId: "child-run-1",
      expectedRunRevision: 0,
      idempotencyKey: "control-invalid",
      instruction: "test",
    }),
    null,
  );
  assert.equal(
    subAgentControlSocketMessage({
      action: "steer",
      conversationId: "conversation-1",
      runId: "child-run-1",
      expectedRunRevision: 7,
      idempotencyKey: "control-invalid",
      instruction: " ",
    }),
    null,
  );

  const sent = [];
  assert.equal(
    deliverSubAgentControlCommand(
      {
        action: "kill_run",
        conversationId: "conversation-1",
        runId: "child-run-1",
        expectedRunRevision: 7,
        idempotencyKey: "control-3",
      },
      (payload) => {
        sent.push(payload);
        return true;
      },
    ),
    true,
  );
  assert.equal(sent[0].cascade, false);
});

test("SubAgent control receipts settle only the matching idempotency key", () => {
  const receipt = {
    type: "control_command_ack",
    action: "steer",
    accepted: false,
    duplicate: false,
    reason_code: "run_revision_conflict",
    conversation_id: "conversation-1",
    project_id: "project-1",
    run_id: "child-run-1",
    run_revision: 8,
    idempotency_key: "control-1",
  };
  assert.deepEqual(subAgentControlReceipt(receipt, "control-1"), {
    action: "steer",
    accepted: false,
    duplicate: false,
    reasonCode: "run_revision_conflict",
    conversationId: "conversation-1",
    projectId: "project-1",
    runId: "child-run-1",
    runRevision: 8,
    idempotencyKey: "control-1",
    cascade: false,
  });
  assert.equal(subAgentControlReceipt(receipt, "control-other"), null);
  assert.equal(
    subAgentControlReceipt({ ...receipt, type: "user_message" }, "control-1"),
    null,
  );
});

test("socket event windows surface an evicted cursor boundary for canonical refetch", () => {
  const previous = { type: "old" };
  const first = { type: "first" };
  const second = { type: "second" };
  assert.deepEqual(socketEventWindowSince([second, first], previous), {
    events: [first, second],
    cursorGap: true,
  });
  assert.deepEqual(
    socketEventWindowSince([second, first, previous], previous),
    {
      events: [first, second],
      cursorGap: false,
    },
  );
});

test("a stop request is scoped, immediate, and never enters the reconnect outbox", () => {
  const queue = createPendingAgentMessageQueue();
  enqueuePendingAgentRunMessage(queue, {
    conversationId: "conversation-queued",
    projectId: "project-1",
    message: "Keep this durable turn",
    messageId: "message-queued",
  });
  const sent = [];

  assert.equal(
    deliverAgentStopSession("  conversation-streaming  ", (payload) => {
      sent.push(payload);
      return true;
    }),
    true,
  );
  assert.deepEqual(sent, [
    {
      type: "stop_session",
      conversation_id: "conversation-streaming",
    },
  ]);
  assert.equal(queue.size, 1);
  assert.equal(
    deliverAgentStopSession(" ", () => true),
    false,
  );
});

test("a steer message sends directly and never enters the reconnect outbox", () => {
  const sent = [];
  const accepted = deliverAgentSteerMessage(
    {
      conversationId: "  conversation-steer  ",
      projectId: "project-1",
      message: "  Focus on the failing test first  ",
      messageId: "desktop-steer-prompt-1",
    },
    (payload) => {
      sent.push(payload);
      return true;
    },
  );
  assert.equal(accepted, true);
  assert.deepEqual(sent, [
    {
      type: "steer_message",
      conversation_id: "conversation-steer",
      project_id: "project-1",
      message: "Focus on the failing test first",
      message_id: "desktop-steer-prompt-1",
    },
  ]);

  assert.equal(
    deliverAgentSteerMessage(
      {
        conversationId: "conversation-steer",
        projectId: "project-1",
        message: "offline",
        messageId: "desktop-steer-prompt-2",
      },
      () => false,
    ),
    false,
  );
  assert.equal(
    agentSteerSocketMessage({
      conversationId: " ",
      projectId: "project-1",
      message: "no conversation",
      messageId: "desktop-steer-prompt-3",
    }),
    null,
  );
  assert.equal(
    agentSteerSocketMessage({
      conversationId: "conversation-steer",
      projectId: "project-1",
      message: "missing id",
      messageId: "  ",
    }),
    null,
  );
});

test("steer outcome reads acks, durable echoes, and steer error codes", () => {
  const messageId = "desktop-steer-prompt-1";
  assert.equal(
    agentSteerMessageOutcome(
      {
        type: "ack",
        action: "steer_message",
        outcome: "accepted",
        message_id: messageId,
      },
      messageId,
    ),
    "accepted",
  );
  assert.equal(
    agentSteerMessageOutcome(
      {
        type: "ack",
        action: "steer_message",
        outcome: "rejected",
        message_id: messageId,
      },
      messageId,
    ),
    "rejected",
  );
  assert.equal(
    agentSteerMessageOutcome(
      { type: "user_message", message_id: messageId },
      messageId,
    ),
    "accepted",
  );
  assert.equal(
    agentSteerMessageOutcome(
      { type: "error", code: "STEER_UNSUPPORTED", message_id: messageId },
      messageId,
    ),
    "rejected",
  );
  assert.equal(
    agentSteerMessageOutcome(
      { type: "error", code: "UNKNOWN_MESSAGE_TYPE", message_id: messageId },
      messageId,
    ),
    "rejected",
  );
  // A different message id or an unrelated event never resolves the steer.
  assert.equal(
    agentSteerMessageOutcome(
      {
        type: "ack",
        action: "steer_message",
        outcome: "accepted",
        message_id: "other-message",
      },
      messageId,
    ),
    null,
  );
  assert.equal(
    agentSteerMessageOutcome(
      { type: "text_delta", message_id: messageId },
      messageId,
    ),
    null,
  );
  assert.equal(
    agentSteerMessageOutcome(
      { type: "error", code: "STOP_SESSION_FAILED", message_id: messageId },
      messageId,
    ),
    null,
  );
});

test("only an authenticated cloud socket may retain a turn for reconnect", () => {
  assert.equal(
    canQueuePendingAgentRunMessage("cloud", true, "ms_sk_session"),
    true,
  );
  assert.equal(
    canQueuePendingAgentRunMessage("cloud", false, "ms_sk_session"),
    false,
  );
  assert.equal(canQueuePendingAgentRunMessage("cloud", true, ""), false);
  assert.equal(
    canQueuePendingAgentRunMessage("local", true, "local-session"),
    false,
  );
});

test("cloud agent turns wait in a bounded deduplicated queue until the socket opens", () => {
  const queue = createPendingAgentMessageQueue();
  const message = {
    conversationId: "conversation-1",
    projectId: "project-1",
    message: "Prepare the plan",
    messageId: "message-1",
  };

  assert.equal(enqueuePendingAgentRunMessage(queue, message), true);
  assert.equal(enqueuePendingAgentRunMessage(queue, message), true);
  assert.equal(queue.size, 1);

  const sent = [];
  assert.equal(
    flushPendingAgentRunMessages(queue, (payload) => {
      sent.push(payload);
      return true;
    }),
    1,
  );
  assert.deepEqual(sent, [
    {
      type: "send_message",
      conversation_id: "conversation-1",
      project_id: "project-1",
      message: "Prepare the plan",
      message_id: "message-1",
    },
  ]);
  assert.equal(queue.size, 1);
  assert.equal(
    confirmPendingAgentRunMessageReceipt(queue, {
      type: "ack",
      action: "send_message",
      outcome: "accepted",
      conversation_id: "conversation-1",
      message_id: "message-1",
    }),
    true,
  );
  assert.equal(queue.size, 0);
});

test("agent turns carry the selected permission mode through reconnect replay", () => {
  const queue = createPendingAgentMessageQueue();
  const sent = [];

  assert.equal(
    deliverAgentRunMessage(
      queue,
      {
        conversationId: "conversation-permission",
        projectId: "project-1",
        message: "Use the selected authorization snapshot",
        messageId: "message-permission-1",
        permissionMode: "automatic",
      },
      (payload) => {
        sent.push(payload);
        return true;
      },
      true,
    ),
    true,
  );
  assert.deepEqual(sent, [
    {
      type: "send_message",
      conversation_id: "conversation-permission",
      project_id: "project-1",
      message: "Use the selected authorization snapshot",
      message_id: "message-permission-1",
      permission_mode: "automatic",
    },
  ]);

  sent.length = 0;
  assert.equal(
    flushPendingAgentRunMessages(queue, (payload) => {
      sent.push(payload);
      return true;
    }),
    1,
  );
  assert.equal(sent[0].permission_mode, "automatic");
});

test("failed socket flush preserves pending cloud turns for the next reconnect", () => {
  const queue = createPendingAgentMessageQueue();
  enqueuePendingAgentRunMessage(queue, {
    conversationId: "conversation-1",
    projectId: "project-1",
    message: "Prepare the plan",
    messageId: "message-1",
  });
  enqueuePendingAgentRunMessage(queue, {
    conversationId: "conversation-2",
    projectId: "project-1",
    message: "Review the result",
    messageId: "message-2",
  });

  assert.equal(
    flushPendingAgentRunMessages(queue, () => false),
    0,
  );
  assert.equal(queue.size, 2);
});

test("a scope transition defers the first turn even while the previous socket is open", () => {
  const queue = createPendingAgentMessageQueue();
  const sent = [];

  assert.equal(
    deliverAgentRunMessage(
      queue,
      {
        conversationId: "conversation-unbound",
        projectId: "project-1",
        message: "Start the unbound conversation",
        messageId: "message-unbound-1",
        deferUntilNextConnection: true,
      },
      (payload) => {
        sent.push(payload);
        return true;
      },
      true,
    ),
    true,
  );
  assert.deepEqual(sent, []);
  assert.equal(queue.size, 1);

  assert.equal(
    flushPendingAgentRunMessages(queue, (payload) => {
      sent.push(payload);
      return true;
    }),
    1,
  );
  assert.deepEqual(sent, [
    {
      type: "send_message",
      conversation_id: "conversation-unbound",
      project_id: "project-1",
      message: "Start the unbound conversation",
      message_id: "message-unbound-1",
    },
  ]);
  assert.equal(queue.size, 1);
  assert.equal(
    confirmPendingAgentRunMessageReceipt(queue, {
      type: "user_message",
      conversation_id: "conversation-unbound",
      data: { message_id: "message-unbound-1" },
    }),
    true,
  );
  assert.equal(queue.size, 0);
});

test("an open-socket send remains in the outbox until receipt and replays after disconnect", () => {
  const queue = createPendingAgentMessageQueue();
  const sent = [];
  const message = {
    conversationId: "conversation-reconnect",
    projectId: "project-1",
    message: "Keep this turn durable",
    messageId: "message-reconnect-1",
  };

  assert.equal(
    deliverAgentRunMessage(
      queue,
      message,
      (payload) => {
        sent.push(payload);
        return true;
      },
      true,
    ),
    true,
  );
  assert.equal(sent.length, 1);
  assert.equal(queue.size, 1);

  assert.equal(
    flushPendingAgentRunMessages(queue, (payload) => {
      sent.push(payload);
      return true;
    }),
    1,
  );
  assert.equal(sent.length, 2);
  assert.deepEqual(sent[1], sent[0]);
  assert.equal(queue.size, 1);
  assert.equal(
    confirmPendingAgentRunMessageReceipt(queue, {
      type: "ack",
      action: "send_message",
      outcome: "accepted",
      conversation_id: "conversation-reconnect",
      message_id: "message-reconnect-1",
    }),
    true,
  );
  assert.equal(queue.size, 0);
});

test("a permanent server error with the client message id removes the stale outbox turn", () => {
  const queue = createPendingAgentMessageQueue();
  enqueuePendingAgentRunMessage(queue, {
    conversationId: "conversation-rejected",
    projectId: "project-1",
    message: "Blocked while HITL is pending",
    messageId: "message-rejected-1",
  });

  assert.equal(
    confirmPendingAgentRunMessageReceipt(queue, {
      type: "error",
      conversation_id: "conversation-rejected",
      data: {
        code: "HITL_PENDING",
        message_id: "message-rejected-1",
      },
    }),
    true,
  );
  assert.equal(queue.size, 0);
});

test("a transient server error with the client message id stays queued for reconnect", () => {
  const queue = createPendingAgentMessageQueue();
  enqueuePendingAgentRunMessage(queue, {
    conversationId: "conversation-retry",
    projectId: "project-1",
    message: "Retry after a temporary server failure",
    messageId: "message-retry-1",
  });

  assert.equal(
    confirmPendingAgentRunMessageReceipt(queue, {
      type: "error",
      conversation_id: "conversation-retry",
      data: {
        message: "Temporary database failure",
        message_id: "message-retry-1",
      },
    }),
    false,
  );
  assert.equal(queue.size, 1);
});

test("an unrelated acknowledgment cannot clear a pending agent turn", () => {
  const queue = createPendingAgentMessageQueue();
  enqueuePendingAgentRunMessage(queue, {
    conversationId: "conversation-pending",
    projectId: "project-1",
    message: "Keep this message pending",
    messageId: "message-pending-1",
  });

  assert.equal(
    confirmPendingAgentRunMessageReceipt(queue, {
      type: "ack",
      action: "subscribe",
      outcome: "accepted",
      conversation_id: "conversation-pending",
      message_id: "message-pending-1",
    }),
    false,
  );
  assert.equal(queue.size, 1);
});

test("pending cloud turns survive workspace activation within the same project", () => {
  const baseConfig = {
    apiBaseUrl: "https://cloud.memstack.example",
    apiKey: "cloud-session",
    localApiToken: "",
    tenantId: "tenant-1",
    projectId: "project-1",
    workspaceId: "workspace-before-create",
    mode: "cloud",
    workspaceRoot: "",
  };

  assert.equal(
    pendingAgentRunQueueScopeKey(baseConfig, 7),
    pendingAgentRunQueueScopeKey(
      { ...baseConfig, workspaceId: "workspace-created-for-session" },
      7,
    ),
  );
});

test("pending cloud turns reset when authenticated project authority changes", () => {
  const baseConfig = {
    apiBaseUrl: "https://cloud.memstack.example",
    apiKey: "cloud-session",
    localApiToken: "",
    tenantId: "tenant-1",
    projectId: "project-1",
    workspaceId: "workspace-1",
    mode: "cloud",
    workspaceRoot: "",
  };
  const currentKey = pendingAgentRunQueueScopeKey(baseConfig, 7);

  assert.notEqual(
    currentKey,
    pendingAgentRunQueueScopeKey({ ...baseConfig, projectId: "project-2" }, 7),
  );
  assert.notEqual(
    currentKey,
    pendingAgentRunQueueScopeKey(
      { ...baseConfig, apiKey: "rotated-session" },
      7,
    ),
  );
  assert.notEqual(currentKey, pendingAgentRunQueueScopeKey(baseConfig, 8));
});

test("queued cloud turns preserve Agent, skill, mention, attachment, and composer context routing", () => {
  const queue = createPendingAgentMessageQueue();
  enqueuePendingAgentRunMessage(queue, {
    conversationId: "conversation-1",
    projectId: "project-1",
    message: "/review Review this change",
    messageId: "message-context-1",
    agentId: "definition-reviewer",
    forcedSkillName: "source-research",
    mentions: ["agent-research"],
    fileMetadata: [
      {
        filename: "evidence.txt",
        sandbox_path: "/workspace/input/evidence.txt",
        mime_type: "text/plain",
        size_bytes: 42,
      },
    ],
    appModelContext: {
      desktop_composer_context: {
        resources: [{ kind: "plugin", resource_id: "github" }],
      },
    },
  });

  const sent = [];
  assert.equal(
    flushPendingAgentRunMessages(queue, (payload) => {
      sent.push(payload);
      return true;
    }),
    1,
  );
  assert.deepEqual(sent, [
    {
      type: "send_message",
      conversation_id: "conversation-1",
      project_id: "project-1",
      message: "/review Review this change",
      message_id: "message-context-1",
      agent_id: "definition-reviewer",
      forced_skill_name: "source-research",
      mentions: ["agent-research"],
      file_metadata: [
        {
          filename: "evidence.txt",
          sandbox_path: "/workspace/input/evidence.txt",
          mime_type: "text/plain",
          size_bytes: 42,
        },
      ],
      app_model_context: {
        desktop_composer_context: {
          resources: [{ kind: "plugin", resource_id: "github" }],
        },
      },
    },
  ]);
});

test("buildHitlSocketMessage preserves the backend WebSocket contract", () => {
  assert.deepEqual(
    buildHitlSocketMessage({
      requestId: "clarification-1",
      hitlType: "clarification",
      responseData: { answer: "Use the indexed repository." },
    }),
    {
      type: "clarification_respond",
      request_id: "clarification-1",
      answer: "Use the indexed repository.",
    },
  );
  assert.deepEqual(
    buildHitlSocketMessage({
      requestId: "permission-1",
      hitlType: "permission",
      responseData: { granted: false },
    }),
    {
      type: "permission_respond",
      request_id: "permission-1",
      granted: false,
    },
  );
});

test("eventCursor accepts Python, server Rust, and desktop Rust cursor fields", () => {
  assert.deepEqual(
    eventCursor({
      conversation_id: "conversation-1",
      event_time_us: 41,
      event_counter: 2,
    }),
    { conversationId: "conversation-1", timeUs: 41, counter: 2 },
  );
  assert.deepEqual(
    eventCursor({ conversation_id: "conversation-2", time_us: 82, counter: 5 }),
    {
      conversationId: "conversation-2",
      timeUs: 82,
      counter: 5,
    },
  );
  assert.deepEqual(
    eventCursor({
      conversation_id: "conversation-3",
      eventTimeUs: 120,
      eventCounter: 9,
    }),
    { conversationId: "conversation-3", timeUs: 120, counter: 9 },
  );
});

test("socketEventKey and reconnectDelay support replay dedupe and bounded backoff", () => {
  assert.equal(socketEventKey({ event_id: "10-0" }), "event:10-0");
  assert.equal(
    socketEventKey({
      conversation_id: "c1",
      event_time_us: 41,
      event_counter: 2,
    }),
    "cursor:c1:41:2",
  );
  assert.equal(reconnectDelay(0), 500);
  assert.equal(reconnectDelay(8), 15_000);
});

test("socketEventsSince returns every coalesced event once in arrival order", () => {
  const oldest = { event_id: "event-1" };
  const middle = { event_id: "event-2" };
  const newest = { event_id: "event-3" };
  const events = [newest, middle, oldest];

  assert.deepEqual(socketEventsSince(events, null), [oldest, middle, newest]);
  assert.deepEqual(socketEventsSince(events, oldest), [middle, newest]);
  assert.deepEqual(socketEventsSince(events, newest), []);
  assert.deepEqual(socketEventsSince(events, { event_id: "evicted" }), [
    oldest,
    middle,
    newest,
  ]);
  assert.deepEqual(socketEventsSince([], newest), []);
});

test("workspace context changes clear every replay and subscription cursor", () => {
  const state = createAgentSocketContextState();
  state.conversationCursors.set("conversation-1", {
    conversationId: "conversation-1",
    timeUs: 41,
    counter: 2,
  });
  state.subscribedConversations.add("conversation-1");
  state.workspaceEventId = "workspace-event-9";
  state.seenEventKeys.add("event:workspace-event-9");

  resetAgentSocketContextState(state);

  assert.equal(state.conversationCursors.size, 0);
  assert.equal(state.subscribedConversations.size, 0);
  assert.equal(state.workspaceEventId, null);
  assert.equal(state.seenEventKeys.size, 0);
});

test("active conversation transition replaces stale subscriptions without clearing replay cursors", () => {
  const state = createAgentSocketContextState();
  state.subscribedConversations.add("conversation-old");
  state.conversationCursors.set("conversation-new", {
    conversationId: "conversation-new",
    timeUs: 82,
    counter: 5,
  });

  const selected = transitionAgentSocketConversationSelection(
    state,
    " conversation-new ",
  );

  assert.deepEqual(selected, {
    unsubscribeConversationIds: ["conversation-old"],
    subscribeConversationId: "conversation-new",
  });
  assert.deepEqual([...state.subscribedConversations], ["conversation-new"]);
  assert.deepEqual(state.conversationCursors.get("conversation-new"), {
    conversationId: "conversation-new",
    timeUs: 82,
    counter: 5,
  });
  assert.deepEqual(conversationSubscriptionMessages(state), [
    {
      type: "subscribe",
      conversation_id: "conversation-new",
      from_time_us: 82,
      from_counter: 6,
    },
  ]);

  const cleared = transitionAgentSocketConversationSelection(state, null);
  assert.deepEqual(cleared, {
    unsubscribeConversationIds: ["conversation-new"],
    subscribeConversationId: null,
  });
  assert.equal(state.subscribedConversations.size, 0);
});
