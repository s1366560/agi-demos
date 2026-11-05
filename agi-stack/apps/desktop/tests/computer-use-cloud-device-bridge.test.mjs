import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
const require = createRequire(import.meta.url);
const {
  createComputerUseCloudDeviceBridge,
} = require("/tmp/agistack-desktop-test-dist/apps/desktop/electron/main/computerUseCloudDeviceBridge.js");
const {
  DesktopCloudSocketBroker,
} = require("/tmp/agistack-desktop-test-dist/apps/desktop/electron/main/cloudSocketBroker.js");
const scope = {
  tenant_id: "fixture-tenant",
  project_id: "fixture-project",
  workspace_id: null,
  conversation_id: "fixture-conversation",
};
const tick = () => new Promise((resolve) => setImmediate(resolve));
const pixel =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ2cAAAAASUVORK5CYII=";

test("native control markers cross the bridge only with their exact non-error result", async () => {
  const output = (status) =>
    JSON.stringify({
      type: "computer_use_control",
      status,
      retry_allowed: false,
    });
  const cases = [
    {
      control_outcome: "user_paused",
      control_generation: "generation",
      output_json: output("user_paused"),
    },
    { control_outcome: "user_stopped", output_json: output("user_stopped") },
    {
      control_outcome: "user_paused",
      output_json: output("user_paused"),
      invalid: true,
    },
    {
      control_outcome: "user_stopped",
      control_generation: "generation",
      output_json: output("user_stopped"),
      invalid: true,
    },
    { output_json: output("user_stopped") },
    {
      control_outcome: "unknown",
      output_json: output("unknown"),
      invalid: true,
    },
    {
      control_outcome: "user_stopped",
      output_json: output("user_paused"),
      invalid: true,
    },
    {
      control_outcome: "user_stopped",
      output_json: output("user_stopped"),
      is_error: true,
      invalid: true,
    },
    {
      control_outcome: "user_stopped",
      output_json: '{"error":"permission_denied"}',
      invalid: true,
    },
    {
      control_outcome: "user_stopped",
      output_json: JSON.stringify({
        type: "computer_use_control",
        status: "user_stopped",
        retry_allowed: true,
      }),
      invalid: true,
    },
    {
      control_outcome: "user_stopped",
      output_json: output("user_stopped"),
      media: [{ artifact_id: "image", mime_type: "image/png", size_bytes: 1 }],
      invalid: true,
    },
  ];
  for (const { invalid, ...result } of cases) {
    const messages = [];
    const bridge = createComputerUseCloudDeviceBridge(
      async (_command, { input }) => {
        if (input.action === "describe")
          return { device_id: "device", tool_definitions: [], scope };
        if (input.action === "call")
          return {
            request_id: input.request_id,
            is_error: false,
            media: [],
            ...result,
          };
        return {};
      },
    );
    await bridge.opened("connection", scope, async (message) =>
      messages.push(message),
    );
    try {
      bridge.receive(
        "connection",
        scope,
        JSON.stringify({ type: "computer_use_request", request_id: "request" }),
        async () => {},
      );
      await tick();
      await tick();
      const returned = messages.find(
        (message) => message.type === "computer_use_result",
      );
      assert.ok(returned);
      assert.equal(returned.is_error, invalid === true);
      assert.equal(
        returned.control_outcome,
        invalid ? undefined : result.control_outcome,
      );
      assert.equal(
        returned.control_generation,
        invalid ? undefined : result.control_generation,
      );
      if (!invalid) assert.equal(returned.output_json, result.output_json);
    } finally {
      bridge.closed("connection", scope);
    }
  }
});

async function pausedConnection(t, readEvents) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const calls = [],
    messages = [];
  const bridge = createComputerUseCloudDeviceBridge(
    async (_command, { input }) => {
      calls.push(input);
      if (input.action === "describe")
        return { device_id: "device", tool_definitions: [], scope };
      if (input.action === "call")
        return {
          request_id: input.request_id,
          is_error: false,
          media: [],
          output_json: JSON.stringify({
            type: "computer_use_control",
            status: "user_paused",
            retry_allowed: false,
          }),
          control_outcome: "user_paused",
          control_generation: "generation",
        };
      if (input.action === "control_events") return readEvents();
      return {};
    },
  );
  await bridge.opened("connection", scope, async (message) =>
    messages.push(message),
  );
  bridge.receive(
    "connection",
    scope,
    JSON.stringify({ type: "computer_use_request", request_id: "request" }),
    async () => {},
  );
  await tick();
  t.after(() => bridge.closed("connection", scope));
  return { bridge, calls, messages };
}

test("only matching paused generations relay retained native Resume or Stop once", async (t) => {
  for (const state of ["resumed", "stopped"]) {
    await t.test(state, async (t) => {
      const event = {
        request_id: "request",
        session_id: "session",
        control_generation: "generation",
        state,
      };
      const { calls, messages } = await pausedConnection(t, () => ({
        events: [event, event],
      }));
      assert.equal(
        calls.some((call) => call.action === "control_events"),
        false,
      );
      t.mock.timers.tick(1000);
      await tick();
      const frames = messages.filter(
        (message) => message.type === "computer_use_control_state",
      );
      assert.deepEqual(frames, [
        { type: "computer_use_control_state", ...event },
      ]);
      assert.deepEqual(
        calls.find((call) => call.action === "control_events").scope,
        scope,
      );
      const count = calls.filter(
        (call) => call.action === "control_events",
      ).length;
      t.mock.timers.tick(1000);
      await tick();
      assert.equal(
        calls.filter((call) => call.action === "control_events").length,
        count,
      );
    });
  }
});

test("stale requests, old pause generations and malformed events cannot resume the waiter", async (t) => {
  const valid = {
    request_id: "request",
    session_id: "session",
    control_generation: "generation",
    state: "resumed",
  };
  let events = [
    { ...valid, request_id: "different" },
    { ...valid, control_generation: "older-generation" },
    { ...valid, state: "unknown" },
  ];
  const { messages } = await pausedConnection(t, () => ({ events }));
  t.mock.timers.tick(1000);
  await tick();
  assert.equal(
    messages.some((message) => message.type === "computer_use_control_state"),
    false,
  );
  events = [{ ...valid, state: "stopped" }];
  t.mock.timers.tick(1000);
  await tick();
  assert.equal(messages.at(-1).state, "stopped");
});

test("closing a cloud connection suppresses an in-flight native control notification", async (t) => {
  let resolveEvents;
  const { bridge, calls, messages } = await pausedConnection(
    t,
    () =>
      new Promise((resolve) => {
        resolveEvents = resolve;
      }),
  );
  t.mock.timers.tick(1000);
  await tick();
  bridge.closed("connection", scope);
  resolveEvents({
    events: [
      {
        request_id: "request",
        session_id: "session",
        control_generation: "generation",
        state: "resumed",
      },
    ],
  });
  await tick();
  t.mock.timers.tick(2000);
  await tick();
  assert.equal(
    messages.some((message) => message.type === "computer_use_control_state"),
    false,
  );
  assert.equal(
    calls.filter((call) => call.action === "control_events").length,
    1,
  );
});

test("authenticated main bridge relays structured observations and real media bytes without native paths", async () => {
  const calls = [];
  const messages = [];
  const bridge = createComputerUseCloudDeviceBridge(
    async (command, { input }) => {
      calls.push({ command, input });
      if (input.action === "describe")
        return {
          device_id: "fixture-device",
          tool_definitions: [
            { name: "computer_get_app_state", inputSchema: { type: "object" } },
          ],
          scope,
          revision: 1,
        };
      if (input.action === "call")
        return {
          request_id: input.request_id,
          output_json: '{"screenshot":{"artifact_id":"cua-image-fixture"}}',
          is_error: false,
          media: [
            {
              artifact_id: "cua-image-fixture",
              mime_type: "image/png",
              size_bytes: Buffer.from(pixel, "base64").byteLength,
            },
          ],
        };
      if (input.action === "media")
        return {
          artifact_id: input.artifact_id,
          mime_type: "image/png",
          offset: 0,
          next_offset: Buffer.from(pixel, "base64").byteLength,
          data_base64: pixel,
          eof: true,
        };
      return { ready: true };
    },
  );
  await bridge.opened("fixture-connection", scope, async (message) =>
    messages.push(message),
  );
  assert.equal(messages[0].type, "computer_use_device");
  assert.equal(
    bridge.receive(
      "fixture-connection",
      scope,
      JSON.stringify({
        type: "computer_use_request",
        request_id: "fixture-request",
      }),
      async () => {},
    ),
    true,
  );
  await tick();
  await tick();
  assert.deepEqual(
    messages.map((message) => message.type),
    ["computer_use_device", "computer_use_result", "computer_use_media"],
  );
  assert.equal(messages[2].data_base64, pixel);
  assert.equal(messages[2].offset, 0);
  assert.equal(messages[2].eof, true);
  assert.equal(calls[1].command, "computer_use_cloud_v2");
  assert.deepEqual(calls[1].input.scope, scope);
  assert.equal("tool_name" in calls[1].input, false);
  assert.equal(JSON.stringify(messages).includes("artifact_path"), false);
  bridge.closed("fixture-connection", scope);
  await tick();
  assert.equal(calls.at(-1).input.action, "close");
});

test("cancel reaches the native pipe while an execution request is pending and duplicate requests do not dispatch", async () => {
  let release;
  let executions = 0;
  const actions = [];
  const bridge = createComputerUseCloudDeviceBridge(
    async (_command, { input }) => {
      actions.push(input.action);
      if (input.action === "describe")
        return { device_id: "device", tool_definitions: [], scope };
      if (input.action === "call") {
        executions++;
        return new Promise((resolve) => {
          release = resolve;
        });
      }
      return {};
    },
  );
  await bridge.opened("connection", scope, async () => {});
  const request = JSON.stringify({
    type: "computer_use_request",
    request_id: "request",
  });
  bridge.receive("connection", scope, request, async () => {});
  bridge.receive("connection", scope, request, async () => {});
  bridge.receive(
    "connection",
    scope,
    JSON.stringify({ type: "computer_use_cancel", request_id: "request" }),
    async () => {},
  );
  await tick();
  assert.equal(executions, 1);
  assert.ok(actions.includes("cancel"));
  bridge.closed("connection", scope);
  release({
    request_id: "request",
    output_json: "{}",
    is_error: false,
    media: [],
  });
  await tick();
});

test("renderer cannot forge native device registration or tool results through the general cloud socket", async () => {
  const socket = {
    protocol: "memstack.auth",
    readyState: 1,
    bufferedAmount: 0,
    binaryType: "arraybuffer",
    onopen: null,
    onmessage: null,
    onerror: null,
    onclose: null,
    send() {},
    close() {},
  };
  const broker = new DesktopCloudSocketBroker({
    authorize: async () => ({
      kind: "agent",
      url: "wss://fixture.test/agent",
      protocols: ["memstack.auth"],
      scope,
      binary: { client_to_server: false, server_to_client: false },
      limits: {
        max_frame_bytes: 512 * 1024,
        max_aggregate_bytes: 2 * 1024 * 1024,
        connect_timeout_ms: 15000,
        idle_timeout_ms: 75000,
      },
    }),
    createSocket: () => socket,
    emit() {},
  });
  await broker.open(1, {
    socketId: "fixture-cloud-socket-001",
    request: { kind: "agent", url: "wss://fixture.test/agent", scope },
  });
  socket.onopen();
  for (const type of [
    "computer_use_device",
    "computer_use_result",
    "computer_use_media",
    "computer_use_control_state",
  ])
    await assert.rejects(
      broker.send(1, {
        socketId: "fixture-cloud-socket-001",
        frame: { binary: false, text: JSON.stringify({ type }) },
      }),
      /cua_cloud_renderer_frame_forbidden/u,
    );
  await broker.close(1, {
    socketId: "fixture-cloud-socket-001",
    code: 1000,
    reason: "",
  });
});

test("an empty registered roster acknowledgement cannot mark the native device ready", async () => {
  const actions = [];
  const bridge = createComputerUseCloudDeviceBridge(
    async (_command, { input }) => {
      actions.push(input.action);
      return input.action === "describe"
        ? { device_id: "device", tool_definitions: [], scope }
        : {};
    },
  );
  await bridge.opened("empty", scope, async () => {});
  assert.equal(
    bridge.receive(
      "empty",
      scope,
      JSON.stringify({
        type: "computer_use_device_ready",
        device_id: "device",
        ready: false,
      }),
      async () => {},
    ),
    true,
  );
  await tick();
  assert.deepEqual(actions, ["describe"]);
  bridge.closed("empty", scope);
});

test('server claim deadline reaches the private supervisor without changing native arguments', async () => {
  const invocations = [];
  const bridge = createComputerUseCloudDeviceBridge(async (command, args) => {
    invocations.push({ command, args });
    if (args.input.action === 'describe') return { device_id: 'device', tool_definitions: [], scope };
    return { request_id: args.input.request_id, output_json: '{}', is_error: false, media: [] };
  });
  await bridge.opened('deadline', scope, async () => {});
  try {
    bridge.receive('deadline', scope, JSON.stringify({ type: 'computer_use_request', request_id: 'timed', expires_at: 2_000_000_000 }), async () => {});
    await tick(); await tick();
    const call = invocations.find(item => item.args.input.action === 'call');
    assert.equal(call.args.request_deadline_ms, 2_000_000_000_000);
    assert.deepEqual(Object.keys(call.args.input).sort(), ['action', 'connection_id', 'request_id', 'scope']);
    assert.throws(() => bridge.receive('deadline', scope, JSON.stringify({ type: 'computer_use_request', request_id: 'invalid', expires_at: '300000' }), async () => {}), /deadline_invalid/);
    assert.equal(invocations.filter(item => item.args.input.action === 'call').length, 1);
  } finally { bridge.closed('deadline', scope); }
});

function permissionRecord(kind = 'cloud_execution_step') {
  return {
    kind,
    binding: {
      tool_name: 'computer_click', input_digest: 'a'.repeat(64),
      engine_session_id: 'engine-session', cell_id: 'cell', step_id: 'step',
    },
    demand: {
      error: 'cua_permission_required', scopes: ['once'],
      request: {
        request_id: 'inner-permission-request', session_id: 'native-session',
        engine_session_id: 'engine-session', tool_name: 'computer_click',
        app: 'fixture-app', identity_digest: 'native-identity',
        capability: kind === 'cloud_execution_step' ? 'execution_step' : 'control',
        input_digest: 'legacy-native-digest',
      },
    },
  };
}

async function bridgeResult(fields) {
  const messages = [];
  const bridge = createComputerUseCloudDeviceBridge(async (_command, { input }) => {
    if (input.action === 'describe') return { device_id: 'device', tool_definitions: [], scope };
    if (input.action === 'call') return {
      request_id: input.request_id, output_json: '{}', is_error: false, media: [], ...fields,
    };
    return {};
  });
  await bridge.opened('permission-connection', scope, async (message) => messages.push(message));
  try {
    bridge.receive('permission-connection', scope, JSON.stringify({
      type: 'computer_use_request', request_id: 'outer-request',
    }), async () => {});
    await tick(); await tick();
    return messages.find((message) => message.type === 'computer_use_result');
  } finally { bridge.closed('permission-connection', scope); }
}

test('trusted native permission and its exact authorization revision cross the private bridge', async () => {
  for (const kind of ['native_consent', 'cloud_execution_step']) {
    const permission = permissionRecord(kind);
    const result = await bridgeResult({ permission_required: permission, authorization_revision: 7 });
    assert.equal(result.is_error, false);
    assert.deepEqual(result.permission_required, permission);
    assert.equal(result.authorization_revision, 7);
    assert.notEqual(permission.binding.input_digest, permission.demand.request.input_digest);
    assert.notEqual(result.request_id, permission.demand.request.request_id);
  }
});

test('normal results and output text cannot manufacture permission provenance', async () => {
  for (const permission_required of [undefined, null]) {
    const result = await bridgeResult({
      permission_required, authorization_revision: 7,
      output_json: JSON.stringify({ permission_required: permissionRecord() }),
    });
    assert.equal(result.is_error, false);
    assert.equal(result.permission_required, undefined);
  }
});

test('malformed private permission records or revisions fail closed without leaking the record', async () => {
  const mutate = (change) => { const record = permissionRecord(); change(record); return record; };
  const invalid = [
    { permission_required: 'untrusted' },
    { permission_required: mutate((v) => { v.extra = true; }) },
    { permission_required: mutate((v) => { v.kind = 'arbitrary'; }) },
    { permission_required: mutate((v) => { v.binding.extra = true; }) },
    { permission_required: mutate((v) => { v.binding.input_digest = 'not-a-digest'; }) },
    { permission_required: mutate((v) => { v.binding.engine_session_id = ''; }) },
    { permission_required: mutate((v) => { v.binding.step_id = null; }) },
    { permission_required: mutate((v) => { v.demand.request.engine_session_id = 'different'; }) },
    { permission_required: mutate((v) => { v.demand.request.tool_name = 'different'; }) },
    { permission_required: mutate((v) => { v.demand.request.request_id = ''; }) },
    { permission_required: mutate((v) => { v.demand.error = 'different'; }) },
    { permission_required: mutate((v) => { v.demand.scopes = []; }) },
    { permission_required: mutate((v) => { v.demand.scopes = ['unknown']; }) },
    { permission_required: mutate((v) => { v.demand.scopes = ['session']; }) },
    { permission_required: mutate((v) => { v.demand.request.capability = 'control'; }) },
    { permission_required: mutate((v) => { v.binding.cell_id = null; v.binding.step_id = null; }) },
    ...[undefined, null, 0, -1, 1.5, '7', Number.MAX_SAFE_INTEGER + 1].map(
      (authorization_revision) => ({ authorization_revision }),
    ),
    { is_error: true },
    { control_outcome: 'user_stopped', output_json: JSON.stringify({
      type: 'computer_use_control', status: 'user_stopped', retry_allowed: false,
    }) },
  ];
  for (const fields of invalid) {
    const result = await bridgeResult({
      permission_required: permissionRecord(), authorization_revision: 7, ...fields,
    });
    assert.equal(result.is_error, true, JSON.stringify(fields));
    assert.equal(result.permission_required, undefined);
    assert.equal(result.authorization_revision, undefined);
    assert.equal(result.output_json.includes('native-identity'), false);
  }
});
