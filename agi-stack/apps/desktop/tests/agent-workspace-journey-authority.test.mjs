import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  AGENT_WORKSPACE_JOURNEY_IDS,
  createAgentWorkspaceJourneyAuthorityClient,
} = require("/tmp/agistack-desktop-test-dist/src/features/agent-workspace/agentWorkspaceJourneyAuthorityClient.js");

const journeyOverrides = JSON.parse(
  readFileSync(
    new URL(
      "../contracts/desktop-web-parity/parity-journey-overrides.v3.json",
      import.meta.url,
    ),
    "utf8",
  ),
);

const cloudConfig = Object.freeze({
  apiBaseUrl: "https://cloud.memstack.test",
  deviceAuthorizationBaseUrl: "https://cloud.memstack.test",
  apiKey: "trusted-session",
  localApiToken: "",
  tenantId: "tenant-1",
  projectId: "project-1",
  workspaceId: "workspace-1",
  mode: "cloud",
  workspaceRoot: "/workspace",
});

test("journey authority catalog covers every Agent Workspace v3 journey exactly once", () => {
  const declared = journeyOverrides.capabilities
    .find(
      (entry) =>
        entry.capability_id === "agent-workspace-tenant-agent-workspace",
    )
    .journeys.map((journey) => journey.id)
    .sort();
  assert.deepEqual([...AGENT_WORKSPACE_JOURNEY_IDS].sort(), declared);
  assert.equal(new Set(AGENT_WORKSPACE_JOURNEY_IDS).size, 8);
});

test("tenant-level production scope remains revision-bound without inferring a workspace", async () => {
  const calls = [];
  const snapshot = await createAgentWorkspaceJourneyAuthorityClient(
    Object.freeze({ ...cloudConfig, workspaceId: "" }),
    { fetchImpl: fixtureFetch("cloud", calls) },
  ).probe();

  assert.equal(snapshot.authorityRevision, 1);
  assert.equal(snapshot.provenance, "observed");
  assert.deepEqual(snapshot.scope, {
    tenantId: "tenant-1",
    projectId: "project-1",
    workspaceId: null,
  });
  const catalogCall = calls.find(
    (call) => new URL(call.input).pathname === "/api/v1/agent/conversations",
  );
  assert.ok(catalogCall);
  assert.equal(new URL(catalogCall.input).searchParams.get("workspace_id"), null);
});

test("Cloud probe publishes only actions backed by successful scoped GET authorities", async () => {
  const calls = [];
  const snapshot = await createAgentWorkspaceJourneyAuthorityClient(
    cloudConfig,
    {
      fetchImpl: fixtureFetch("cloud", calls),
    },
  ).probe();

  assert.equal(snapshot.authority, "cloud");
  assert.equal(snapshot.authoritySource, "cloud_service");
  assert.equal(snapshot.provenance, "observed");
  assert.equal(snapshot.authorityRevision, 1);
  assert.deepEqual(snapshot.scope, {
    tenantId: "tenant-1",
    projectId: "project-1",
    workspaceId: "workspace-1",
  });
  assert.deepEqual(actions(snapshot, "bootstrap-and-scope"), [
    "restore-session",
    "load-system-features",
    "load-tenants",
    "resolve-conversation",
  ]);
  assert.deepEqual(actions(snapshot, "conversation-lifecycle"), [
    "list-conversations",
    "get-conversation",
    "load-history",
  ]);
  assert.deepEqual(actions(snapshot, "stream-and-run-control"), [
    "get-active-run",
    "get-latest-run",
    "list-run-inputs",
  ]);
  assert.deepEqual(actions(snapshot, "hitl-and-a2ui"), ["render-surface"]);
  assert.deepEqual(actions(snapshot, "roster-and-subagents"), [
    "list-participants",
    "list-subagents",
  ]);
  assert.deepEqual(actions(snapshot, "work-review"), [
    "list-my-work",
    "read-activity",
    "view-run-summary",
    "view-run-changes",
    "view-usage",
    "view-cost",
  ]);
  assert.deepEqual(actions(snapshot, "content-and-export"), [
    "list-attachments",
    "list-artifacts",
  ]);
  assert.deepEqual(actions(snapshot, "local-runtime"), [
    "open-terminal",
    "connect-terminal",
    "open-remote-desktop",
  ]);
  for (const observation of Object.values(snapshot.journeys)) {
    assert.equal(observation.availability, "degraded");
    assert.match(
      observation.reasonCode,
      /^agent_workspace_journey_.+_partial$/u,
    );
  }
  assert.ok(calls.length >= 18);
  for (const call of calls) {
    assert.equal(call.init.method, "GET");
    assert.equal(call.init.credentials, "omit");
    const headers = new Headers(call.init.headers);
    assert.equal(headers.get("Authorization"), "Bearer trusted-session");
    assert.equal(headers.get("X-Agistack-Launch"), null);
  }
  assert.equal(
    calls.filter(
      (call) => new URL(call.input).pathname === "/api/v1/workspace-context",
    ).length,
    2,
  );
  assert.equal(
    requestUrl(calls, "/api/v1/agent/conversations/conversation-1").searchParams.get(
      "project_id",
    ),
    "project-1",
  );
  assert.equal(
    requestUrl(
      calls,
      "/api/v1/agent/conversations/conversation-1/messages",
    ).searchParams.get("project_id"),
    "project-1",
  );
  assert.ok(
    requestUrl(
      calls,
      "/api/v1/agent/hitl/conversations/conversation-1/pending",
    ),
  );
  assert.ok(
    requestUrl(
      calls,
      "/api/v1/agent/conversations/conversation-1/participants",
    ),
  );
  assert.equal(
    requestUrl(calls, "/api/v1/attachments").searchParams.get(
      "conversation_id",
    ),
    "conversation-1",
  );
  assert.equal(
    requestUrl(calls, "/api/v1/artifacts").searchParams.get("project_id"),
    "project-1",
  );
  assert.equal(
    requestUrl(calls, "/api/v1/artifacts").searchParams.get("limit"),
    "100",
  );
  const cloudChanges = requestUrl(calls, "/api/v1/agent/runs/run-1/changes");
  assert.equal(cloudChanges.searchParams.get("expected_revision"), "4");
  assert.equal(cloudChanges.searchParams.get("scope"), "run");
});

test("Local probe uses launch authority and preserves structured runtime unavailability", async () => {
  const calls = [];
  const config = Object.freeze({
    ...cloudConfig,
    apiBaseUrl: "http://127.0.0.1:4777",
    apiKey: "local-session",
    localApiToken: "private-launch",
    mode: "local",
  });
  const snapshot = await createAgentWorkspaceJourneyAuthorityClient(config, {
    fetchImpl: fixtureFetch("local", calls),
  }).probe();

  assert.equal(snapshot.authority, "local");
  assert.equal(snapshot.authoritySource, "sidecar");
  assert.equal(snapshot.authorityRevision, 1);
  assert.deepEqual(actions(snapshot, "bootstrap-and-scope"), [
    "restore-session",
    "load-tenants",
    "resolve-conversation",
  ]);
  assert.deepEqual(actions(snapshot, "conversation-lifecycle"), [
    "list-conversations",
    "get-conversation",
    "load-history",
  ]);
  assert.deepEqual(actions(snapshot, "stream-and-run-control"), [
    "get-active-run",
    "get-latest-run",
    "list-run-inputs",
  ]);
  assert.deepEqual(actions(snapshot, "hitl-and-a2ui"), ["render-surface"]);
  assert.deepEqual(actions(snapshot, "roster-and-subagents"), [
    "list-subagents",
  ]);
  assert.deepEqual(actions(snapshot, "work-review"), [
    "list-my-work",
    "read-activity",
    "view-run-changes",
  ]);
  assert.deepEqual(actions(snapshot, "content-and-export"), ["list-artifacts"]);
  assert.deepEqual(actions(snapshot, "local-runtime"), [
    "open-terminal",
    "connect-terminal",
  ]);
  assert.equal(
    snapshot.journeys["local-runtime"].reasonCode,
    "agent_workspace_journey_local_runtime_partial",
  );
  assert.ok(
    calls.every(
      (call) =>
        new Headers(call.init.headers).get("X-Agistack-Launch") ===
        "private-launch",
    ),
  );
  assert.ok(
    calls.every(
      (call) =>
        new Headers(call.init.headers).get("Authorization") ===
        "Bearer local-session",
    ),
  );
  assert.equal(
    calls.some(
      (call) => new URL(call.input).pathname === "/api/v1/system/features",
    ),
    false,
  );
  assert.ok(
    requestUrl(
      calls,
      "/api/v1/agent/conversations/conversation-1/session",
    ),
  );
  assert.equal(
    requestUrl(
      calls,
      "/api/v1/agent/conversations/conversation-1/messages",
    ).searchParams.get("project_id"),
    "project-1",
  );
  const localChanges = requestUrl(calls, "/api/v1/agent/runs/run-1/changes");
  assert.equal(localChanges.searchParams.get("expected_revision"), "4");
  assert.equal(localChanges.searchParams.get("scope"), null);
  for (const cloudOnlyPath of [
    "/api/v1/agent/conversations/conversation-1/active-run",
    "/api/v1/agent/conversations/conversation-1/latest-run",
    "/api/v1/agent/hitl/conversations/conversation-1/pending",
    "/api/v1/agent/conversations/conversation-1/participants",
    "/api/v1/attachments",
    "/api/v1/artifacts",
  ]) {
    assert.equal(
      calls.some((call) => new URL(call.input).pathname === cloudOnlyPath),
      false,
      cloudOnlyPath,
    );
  }
});

test("empty authorities remain limited and never manufacture mutation reachability", async () => {
  const calls = [];
  const snapshot = await createAgentWorkspaceJourneyAuthorityClient(
    cloudConfig,
    {
      fetchImpl: fixtureFetch("empty", calls),
    },
  ).probe();

  assert.deepEqual(actions(snapshot, "conversation-lifecycle"), [
    "list-conversations",
  ]);
  assert.deepEqual(actions(snapshot, "stream-and-run-control"), []);
  assert.deepEqual(actions(snapshot, "hitl-and-a2ui"), []);
  assert.deepEqual(actions(snapshot, "content-and-export"), ["list-artifacts"]);
  assert.equal(
    snapshot.journeys["stream-and-run-control"].reasonCode,
    "agent_workspace_journey_stream_and_run_control_empty",
  );
  for (const journeyId of [
    "stream-and-run-control",
    "hitl-and-a2ui",
    "roster-and-subagents",
    "local-runtime",
  ]) {
    assert.equal(snapshot.journeys[journeyId].availability, "unavailable");
  }
  assert.equal(
    snapshot.journeys["conversation-lifecycle"].availability,
    "degraded",
  );
  assert.equal(
    snapshot.journeys["content-and-export"].availability,
    "degraded",
  );
  const allActions = Object.values(snapshot.journeys).flatMap(
    (observation) => observation.observedActions,
  );
  for (const mutation of [
    "create-conversation",
    "delete-conversation",
    "send-message",
    "stop-session",
    "queue-input",
    "promote-input",
    "submit-action",
    "write-read-state",
    "upload-attachment",
    "delete-artifact",
    "close-runtime",
  ]) {
    assert.equal(allActions.includes(mutation), false, mutation);
  }
  assert.ok(calls.every((call) => call.init.method === "GET"));
});

test("scope mismatch and oversized JSON fail closed before dependent journey probes", async () => {
  let calls = 0;
  const mismatch = await createAgentWorkspaceJourneyAuthorityClient(
    cloudConfig,
    {
      fetchImpl: async (input) => {
        calls += 1;
        const path = new URL(String(input)).pathname;
        if (path === "/api/v1/auth/me") return jsonResponse(user());
        if (path === "/api/v1/workspace-context") {
          return jsonResponse({
            context: {
              tenant_id: "tenant-1",
              project_id: "wrong-project",
              revision: 1,
              updated_at: "2026-08-05T00:00:00Z",
            },
            membership_role: "owner",
          });
        }
        throw new Error(`unexpected dependent request: ${path}`);
      },
    },
  ).probe();
  assert.equal(calls, 2);
  for (const observation of Object.values(mismatch.journeys)) {
    assert.equal(observation.availability, "unavailable");
    assert.deepEqual(observation.observedActions, []);
  }

  const oversized = await createAgentWorkspaceJourneyAuthorityClient(
    cloudConfig,
    {
      fetchImpl: async () =>
        new Response("{}", {
          status: 200,
          headers: {
            "content-type": "application/json",
            "content-length": String(2 * 1024 * 1024),
          },
        }),
    },
  ).probe();
  assert.equal(
    oversized.journeys["bootstrap-and-scope"].availability,
    "unavailable",
  );
  assert.deepEqual(
    oversized.journeys["bootstrap-and-scope"].observedActions,
    [],
  );
});

test("cross-scope conversation pages fail closed before journey-specific probes", async () => {
  const calls = [];
  const baseFetch = fixtureFetch("cloud", calls);
  const result = await createAgentWorkspaceJourneyAuthorityClient(cloudConfig, {
    fetchImpl: async (input, init) => {
      if (new URL(String(input)).pathname === "/api/v1/agent/conversations") {
        calls.push({ input: String(input), init });
        return jsonResponse({
          ...conversationPage(true),
          items: [{ ...conversation(), workspace_id: "wrong-workspace" }],
        });
      }
      return baseFetch(input, init);
    },
  }).probe();

  const conversationRequest = calls.find(
    (call) => new URL(call.input).pathname === "/api/v1/agent/conversations",
  );
  assert.ok(conversationRequest);
  assert.equal(
    new URL(conversationRequest.input).searchParams.get("workspace_id"),
    "workspace-1",
  );

  for (const observation of Object.values(result.journeys)) {
    assert.equal(observation.availability, "unavailable");
    assert.equal(
      observation.reasonCode,
      "agent_workspace_journey_scope_conflict",
    );
    assert.deepEqual(observation.observedActions, []);
  }
  assert.equal(
    calls.some((call) => new URL(call.input).pathname.includes("/my-work")),
    false,
  );
});

test("conversation catalogs cannot promote another user's conversation into authority", async () => {
  const calls = [];
  const baseFetch = fixtureFetch("cloud", calls);
  const result = await createAgentWorkspaceJourneyAuthorityClient(cloudConfig, {
    fetchImpl: async (input, init) => {
      if (new URL(String(input)).pathname === "/api/v1/agent/conversations") {
        calls.push({ input: String(input), init });
        return jsonResponse({
          ...conversationPage(true),
          items: [{ ...conversation(), user_id: "user-2" }],
        });
      }
      return baseFetch(input, init);
    },
  }).probe();

  for (const observation of Object.values(result.journeys)) {
    assert.equal(observation.availability, "unavailable");
    assert.equal(
      observation.reasonCode,
      "agent_workspace_journey_scope_conflict",
    );
    assert.deepEqual(observation.observedActions, []);
  }
});

test("authority scope and revision are revalidated after all journey probes", async () => {
  for (const scenario of [
    {
      name: "revision changed",
      finalContext: workspaceContext({ revision: 2 }),
      reasonCode: "agent_workspace_journey_authority_stale",
    },
    {
      name: "project changed",
      finalContext: workspaceContext({ projectId: "project-2" }),
      reasonCode: "agent_workspace_journey_scope_conflict",
    },
  ]) {
    const calls = [];
    const baseFetch = fixtureFetch("cloud", calls);
    let contextReads = 0;
    const result = await createAgentWorkspaceJourneyAuthorityClient(cloudConfig, {
      fetchImpl: async (input, init) => {
        if (new URL(String(input)).pathname === "/api/v1/workspace-context") {
          calls.push({ input: String(input), init });
          contextReads += 1;
          return jsonResponse(
            contextReads === 1 ? workspaceContext() : scenario.finalContext,
          );
        }
        return baseFetch(input, init);
      },
    }).probe();

    assert.equal(contextReads, 2, scenario.name);
    assert.equal(result.authorityRevision, null, scenario.name);
    for (const observation of Object.values(result.journeys)) {
      assert.equal(observation.availability, "unavailable", scenario.name);
      assert.equal(observation.reasonCode, scenario.reasonCode, scenario.name);
      assert.deepEqual(observation.observedActions, [], scenario.name);
    }
  }
});

test("missing and unsafe workspace revisions fail closed with a stable reason", async () => {
  for (const revision of [undefined, Number.MAX_SAFE_INTEGER + 1]) {
    const result = await createAgentWorkspaceJourneyAuthorityClient(cloudConfig, {
      fetchImpl: async (input) => {
        const path = new URL(String(input)).pathname;
        if (path === "/api/v1/auth/me") return jsonResponse(user());
        if (path === "/api/v1/workspace-context") {
          const context = workspaceContext();
          if (revision === undefined) delete context.context.revision;
          else context.context.revision = revision;
          return jsonResponse(context);
        }
        throw new Error(`unexpected request after invalid revision: ${path}`);
      },
    }).probe();

    assert.equal(result.authorityRevision, null);
    for (const observation of Object.values(result.journeys)) {
      assert.equal(
        observation.reasonCode,
        "agent_workspace_journey_authority_revision_invalid",
      );
      assert.deepEqual(observation.observedActions, []);
    }
  }
});

test("unknown-length oversized responses cancel the stream at the authority boundary", async () => {
  let cancelled = false;
  const oversizedBody = new ReadableStream({
    start(controller) {
      controller.enqueue(new Uint8Array(1024 * 1024));
      controller.enqueue(new Uint8Array(1024 * 1024));
      controller.enqueue(new Uint8Array(1));
      controller.close();
    },
    cancel() {
      cancelled = true;
    },
  });
  const result = await createAgentWorkspaceJourneyAuthorityClient(cloudConfig, {
    fetchImpl: async () =>
      new Response(oversizedBody, {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  }).probe();

  assert.equal(cancelled, true);
  for (const observation of Object.values(result.journeys)) {
    assert.equal(observation.availability, "unavailable");
    assert.equal(
      observation.reasonCode,
      "agent_workspace_journey_response_too_large",
    );
  }
});

test("journey authority requires trusted session, tenant/project scope and Local launch capability", () => {
  assert.throws(
    () =>
      createAgentWorkspaceJourneyAuthorityClient({
        ...cloudConfig,
        apiKey: "",
      }),
    /agent_workspace_journey_trusted_session_required/u,
  );
  assert.doesNotThrow(() =>
    createAgentWorkspaceJourneyAuthorityClient({
      ...cloudConfig,
      workspaceId: "",
    }),
  );
  assert.throws(
    () =>
      createAgentWorkspaceJourneyAuthorityClient({
        ...cloudConfig,
        mode: "local",
        localApiToken: "",
      }),
    /agent_workspace_journey_launch_capability_required/u,
  );
});

function actions(snapshot, journeyId) {
  return snapshot.journeys[journeyId].observedActions;
}

function requestUrl(calls, path) {
  const call = calls.find((candidate) => new URL(candidate.input).pathname === path);
  assert.ok(call, `missing request ${path}`);
  return new URL(call.input);
}

function fixtureFetch(mode, calls) {
  return async (input, init) => {
    calls.push({ input: String(input), init });
    const url = new URL(String(input));
    const path = url.pathname;
    if (path === "/api/v1/auth/me") return jsonResponse(user());
    if (path === "/api/v1/workspace-context")
      return jsonResponse(workspaceContext());
    if (path === "/api/v1/system/features") {
      return jsonResponse([{ id: "agent_pool", enabled: true }]);
    }
    if (path === (mode === "local" ? "/api/v1/tenants" : "/api/v1/tenants/")) {
      return jsonResponse({
        tenants: [{ id: "tenant-1", name: "Tenant" }],
        total: 1,
        page: 1,
        page_size: 100,
      });
    }
    if (path === (mode === "local" ? "/api/v1/projects" : "/api/v1/projects/")) {
      return jsonResponse({
        projects: [{ id: "project-1", tenant_id: "tenant-1", name: "Project" }],
        total: 1,
        page: 1,
        page_size: 100,
      });
    }
    if (path === "/api/v1/agent/conversations") {
      return jsonResponse(conversationPage(mode !== "empty"));
    }
    if (path === "/api/v1/agent/conversations/conversation-1") {
      return jsonResponse(conversation());
    }
    if (path === "/api/v1/agent/conversations/conversation-1/messages") {
      return jsonResponse(messages(mode === "local"));
    }
    if (path === "/api/v1/agent/conversations/conversation-1/session") {
      return mode === "local"
        ? jsonResponse(sessionProjection())
        : jsonResponse({ detail: "not found" }, 404);
    }
    if (path.endsWith("/active-run")) {
      return jsonResponse(runEnvelope("active_run"));
    }
    if (path.endsWith("/latest-run")) {
      return jsonResponse(runEnvelope("latest_run"));
    }
    if (path === "/api/v1/agent/conversations/conversation-1/runs") {
      return jsonResponse({
        conversation_id: "conversation-1",
        total_count: 1,
        runs: [run(mode === "local")],
      });
    }
    if (path === "/api/v1/agent/runs/run-1/inputs") {
      return jsonResponse({
        run_id: "run-1",
        run_revision: 4,
        inputs: [],
        total_count: 0,
      });
    }
    if (path === "/api/v1/agent/hitl/conversations/conversation-1/pending") {
      if (mode === "local") return jsonResponse({ detail: "not found" }, 404);
      return jsonResponse({
        requests: [
          {
            id: "hitl-1",
            conversation_id: "conversation-1",
            status: "pending",
            authority_revision: 1,
          },
        ],
        total: 1,
      });
    }
    if (path.endsWith("/participants")) {
      if (mode === "local") return jsonResponse({ detail: "not found" }, 404);
      return jsonResponse({
        conversation_id: "conversation-1",
        conversation_mode: "collaborative",
        effective_mode: "collaborative",
        participant_agents: [],
        participant_bindings: [],
        coordinator_agent_id: null,
        focused_agent_id: null,
      });
    }
    if (path === "/api/v1/subagents/") {
      return jsonResponse(
        mode === "local" ? { items: [] } : { subagents: [], total: 0 },
      );
    }
    if (path === "/api/v1/projects/project-1/my-work") {
      return jsonResponse({ project_id: "project-1", items: [], total: 0 });
    }
    if (path === "/api/v1/projects/project-1/activity/read-state") {
      return jsonResponse({
        project_id: "project-1",
        authority_revision: 0,
        entries: [],
      });
    }
    if (path === "/api/v1/agent/runs/run-1/summary") {
      return jsonResponse({
        run_id: "run-1",
        tenant_id: "tenant-1",
        project_id: "project-1",
        conversation_id: "conversation-1",
        revision: 4,
        summary_state: "recorded",
        input_tokens: 10,
        output_tokens: 20,
        cost_usd: 0.1,
      });
    }
    if (path === "/api/v1/agent/runs/run-1/changes") {
      return jsonResponse({
        id: "changes-1",
        run_id: "run-1",
        conversation_id: "conversation-1",
        run_revision: 4,
        status: "ready",
        files: [],
      });
    }
    if (path === "/api/v1/attachments" && mode !== "local") {
      return jsonResponse({ attachments: [], total: 0 });
    }
    if (path === "/api/v1/artifacts" && mode !== "local") {
      return jsonResponse({ artifacts: [], total: 0 });
    }
    if (path === "/api/v1/projects/project-1/sandbox/capabilities") {
      return jsonResponse({
        service_version: "0.1.0",
        contract_version: 2,
        terminal_interactive: {
          availability: "available",
          contract_version: 1,
          reason_code: null,
        },
        terminal_resume: {
          availability: "unavailable",
          contract_version: 2,
          reason_code: "local_terminal_resume_unavailable",
        },
        files: {
          availability: "available",
          contract_version: 1,
          reason_code: null,
        },
        kasm_vnc: {
          availability: "not_applicable",
          contract_version: 1,
          reason_code: "local_kasm_vnc_not_applicable",
        },
      });
    }
    if (path === "/api/v1/projects/project-1/sandbox") {
      return jsonResponse(
        mode === "empty"
          ? {
              sandbox_id: "sandbox-1",
              project_id: "project-1",
              status: "unavailable",
              is_healthy: false,
              terminal_url: null,
              desktop_url: null,
            }
          : {
              sandbox_id: "sandbox-1",
              project_id: "project-1",
              status: "running",
              is_healthy: true,
              terminal_url: "/terminal",
              desktop_url: "/desktop",
            },
      );
    }
    throw new Error(`unhandled ${mode} fixture request: ${url}`);
  };
}

function user() {
  return { user_id: "user-1", email: "user@example.test", is_active: true };
}

function workspaceContext({ projectId = "project-1", revision = 1 } = {}) {
  return {
    context: {
      tenant_id: "tenant-1",
      project_id: projectId,
      revision,
      updated_at: "2026-08-05T00:00:00Z",
    },
    membership_role: "owner",
  };
}

function sessionProjection() {
  return {
    schema_version: 1,
    conversation: conversation(),
    current_run: run(true),
    run_history: [run(true)],
    current_plan: null,
    plan_history: [],
    tasks: [],
    pending_hitl: [
      {
        id: "hitl-1",
        conversation_id: "conversation-1",
        status: "pending",
      },
    ],
    artifact_versions: [],
    artifact_deliveries: [],
    tool_invocations: [],
    capabilities: {
      can_send_message: true,
      can_respond_to_hitl: true,
      can_steer_now: true,
      can_queue_next: true,
      allowed_actions: ["send_message", "respond_to_hitl", "steer_now", "queue_next"],
    },
    snapshot_revision: "session-revision-1",
    updated_at: "2026-08-05T00:00:00Z",
  };
}

function conversationPage(includeItem) {
  return {
    items: includeItem ? [conversation()] : [],
    total: includeItem ? 1 : 0,
    has_more: false,
    offset: 0,
    limit: 1,
    next_offset: null,
  };
}

function conversation() {
  return {
    id: "conversation-1",
    user_id: "user-1",
    tenant_id: "tenant-1",
    project_id: "project-1",
    workspace_id: "workspace-1",
    summary: null,
  };
}

function messages(local) {
  return {
    conversationId: "conversation-1",
    timeline: [],
    total: 0,
    has_more: false,
    ...(local
      ? {
          approval_requests: [
            {
              id: "hitl-1",
              conversation_id: "conversation-1",
              status: "pending",
            },
          ],
          artifact_versions: [],
          artifact_deliveries: [],
          tool_invocations: [],
        }
      : {}),
  };
}

function run(local = false) {
  return {
    id: "run-1",
    ...(local ? {} : { tenant_id: "tenant-1" }),
    project_id: "project-1",
    conversation_id: "conversation-1",
    status: "running",
    revision: 4,
  };
}

function runEnvelope(key) {
  return {
    conversation_id: "conversation-1",
    [key]: run(),
    availability: "available",
    reason_code: null,
    authority_revision: 4,
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}
