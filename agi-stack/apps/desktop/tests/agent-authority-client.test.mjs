import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  createDesktopAgentAuthorityAdapter,
} = require("/tmp/agistack-desktop-test-dist/src/features/agent-authority/cloudAgentAuthorityClient.js");
const {
  createLocalStorageActivityReadRetryStore,
} = require("/tmp/agistack-desktop-test-dist/src/features/agent-authority/activityReadRetryStore.js");
const {
  desktopChangeSnapshotFromCloud,
} = require("/tmp/agistack-desktop-test-dist/src/features/agent-authority/agentAuthorityProjection.js");

const cloudConfig = {
  apiBaseUrl: "https://api.example.test",
  deviceAuthorizationBaseUrl: "https://api.example.test",
  apiKey: "cloud-token",
  localApiToken: "",
  tenantId: "tenant-1",
  projectId: "project-1",
  workspaceId: "workspace-1",
  mode: "cloud",
  workspaceRoot: "",
};

const localConfig = {
  ...cloudConfig,
  apiBaseUrl: "http://127.0.0.1:43121",
  apiKey: "",
  localApiToken: "local-launch-capability",
  mode: "local",
};

const scope = {
  authority: "cloud",
  principalId: "user-1",
  tenantId: "tenant-1",
  projectId: "project-1",
};

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
    values,
  };
}

function summary(overrides = {}) {
  return {
    run_id: "run-1",
    tenant_id: "tenant-1",
    project_id: "project-1",
    conversation_id: "conversation-1",
    status: "ready_review",
    revision: 7,
    summary_state: "recorded",
    reason_code: null,
    started_at: "2026-08-04T01:00:00Z",
    completed_at: "2026-08-04T01:01:00Z",
    duration_ms: 60_000,
    input_tokens: 120,
    output_tokens: 80,
    cost_usd: 0.02,
    model_breakdown: [{ model: "test-model", input_tokens: 120 }],
    completion_summary: "Implemented the requested change.",
    artifact_count: 1,
    checks_passed: 4,
    checks_failed: 0,
    files_changed: 2,
    lines_added: 12,
    lines_deleted: 3,
    evidence_references: [{ kind: "test", id: "test-1" }],
    ...overrides,
  };
}

function changes(overrides = {}) {
  return {
    id: "cloud-change-snapshot-1",
    run_id: "run-1",
    conversation_id: "conversation-1",
    run_revision: 7,
    environment_id: "environment-1",
    repository_root: "/repo",
    workspace_path: "/repo/workspace",
    branch: "codex/test",
    base_revision: "base-sha",
    head_revision: null,
    status: "ready",
    reason: null,
    additions: 2,
    deletions: 1,
    files_changed: 1,
    truncated: false,
    captured_at: "2026-08-04T01:01:00Z",
    files: [
      {
        path: "src/example.ts",
        old_path: null,
        status: "modified",
        additions: 2,
        deletions: 1,
        binary: false,
        untracked: false,
        patch_digest: "patch-1",
        hunks: [
          {
            header: "@@ -1 +1 @@",
            old_start: 1,
            new_start: 1,
            lines: [
              { kind: "addition", old_line: null, new_line: 1, text: "next" },
            ],
          },
        ],
      },
    ],
    scope: "run",
    turn_id: null,
    snapshot_revision: "snapshot-revision-1",
    attribution: [],
    ...overrides,
  };
}

test("Local mode exposes narrow Activity authority without a Cloud client", () => {
  let fetched = false;
  const adapter = createDesktopAgentAuthorityAdapter(localConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async () => {
      fetched = true;
      throw new Error("must not fetch");
    },
  });

  assert.equal(adapter.authority, "local");
  assert.equal(adapter.availability, "available");
  assert.equal(adapter.reasonCode, null);
  assert.deepEqual(adapter.allowedActions, ["read_activity", "write_activity"]);
  assert.equal(adapter.client, null);
  assert.equal(typeof adapter.activityClient.getActivityReadState, "function");
  assert.equal(fetched, false);
});

test("Cloud My Work accepts agent_run with a nested authoritative RunSummary", async () => {
  const calls = [];
  const adapter = createDesktopAgentAuthorityAdapter(cloudConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      return jsonResponse({
        project_id: "project-1",
        total: 1,
        items: [
          {
            id: "agent_run:run-1",
            authority_kind: "agent_run",
            authority_id: "run-1",
            run_id: "run-1",
            conversation_id: "conversation-1",
            workspace_id: "workspace-1",
            project_id: "project-1",
            title: "Cloud authority slice",
            capability_mode: "code",
            group: "ready_review",
            status: "ready_review",
            required_action: "observe",
            revision: 7,
            permission_profile: "workspace_write",
            environment: "cloud",
            error: null,
            attempt_number: null,
            created_at: "2026-08-04T01:00:00Z",
            updated_at: "2026-08-04T01:01:00Z",
            last_heartbeat_at: null,
            workspace_name: "Workspace",
            summary: "Ready for review",
            phase: "review",
            progress: 100,
            run_summary: summary(),
          },
        ],
      });
    },
  });

  assert.equal(adapter.availability, "available");
  const response = await adapter.client.listMyWork(scope);

  assert.equal(response.items[0].authority_kind, "agent_run");
  assert.equal(response.items[0].run_summary?.summary_state, "recorded");
  assert.equal(response.items[0].run_summary?.input_tokens, 120);
  assert.equal(
    calls[0].url,
    "https://api.example.test/api/v1/projects/project-1/my-work",
  );
  assert.equal(
    new Headers(calls[0].init.headers).get("Authorization"),
    "Bearer cloud-token",
  );
});

test("Cloud My Work accepts an unbound canonical Agent Workspace run", async () => {
  const adapter = createDesktopAgentAuthorityAdapter(cloudConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async () =>
      jsonResponse({
        project_id: "project-1",
        total: 1,
        items: [
          {
            id: "agent_run:run-1",
            authority_kind: "agent_run",
            authority_id: "run-1",
            run_id: "run-1",
            conversation_id: "conversation-1",
            workspace_id: null,
            project_id: "project-1",
            title: "Unbound Agent Workspace run",
            capability_mode: "work",
            group: "ready_review",
            status: "ready_review",
            required_action: "review_approval",
            revision: 7,
            permission_profile: "read_only",
            environment: null,
            error: null,
            attempt_number: null,
            created_at: "2026-08-04T01:00:00Z",
            updated_at: "2026-08-04T01:01:00Z",
            last_heartbeat_at: null,
            workspace_name: null,
            summary: null,
            phase: null,
            progress: null,
            run_summary: summary({
              summary_state: "partial",
              reason_code: "summary_not_recorded",
            }),
          },
        ],
      }),
  });

  const response = await adapter.client.listMyWork(scope);

  assert.equal(response.items[0].workspace_id, null);
  assert.equal(response.items[0].run_summary?.reason_code, "summary_not_recorded");
});

test("Cloud My Work preserves non-empty titles with trailing whitespace", async () => {
  const adapter = createDesktopAgentAuthorityAdapter(cloudConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async () =>
      jsonResponse({
        project_id: "project-1",
        total: 1,
        items: [
          {
            id: "agent_run:run-1",
            authority_kind: "agent_run",
            authority_id: "run-1",
            run_id: "run-1",
            conversation_id: "conversation-1",
            workspace_id: null,
            project_id: "project-1",
            title: "Persisted conversation title ",
            capability_mode: "work",
            group: "ready_review",
            status: "ready_review",
            required_action: "review_approval",
            revision: 7,
            permission_profile: "read_only",
            environment: null,
            error: null,
            attempt_number: null,
            created_at: "2026-08-04T01:00:00Z",
            updated_at: "2026-08-04T01:01:00Z",
            last_heartbeat_at: null,
            workspace_name: null,
            summary: null,
            phase: null,
            progress: null,
            run_summary: summary(),
          },
        ],
      }),
  });

  const response = await adapter.client.listMyWork(scope);

  assert.equal(response.items[0].title, "Persisted conversation title ");
});

test("Cloud My Work rejects nested summaries outside the requested scope", async () => {
  const adapter = createDesktopAgentAuthorityAdapter(cloudConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async () =>
      jsonResponse({
        project_id: "project-1",
        total: 1,
        items: [
          {
            id: "agent_run:run-1",
            authority_kind: "agent_run",
            authority_id: "run-1",
            run_id: "run-1",
            conversation_id: "conversation-1",
            workspace_id: "workspace-1",
            project_id: "project-1",
            title: "Wrong scope",
            capability_mode: "code",
            group: "running",
            status: "running",
            required_action: "observe",
            revision: 7,
            permission_profile: "workspace_write",
            environment: "cloud",
            error: null,
            attempt_number: null,
            created_at: "2026-08-04T01:00:00Z",
            updated_at: "2026-08-04T01:01:00Z",
            last_heartbeat_at: null,
            workspace_name: "Workspace",
            summary: null,
            phase: null,
            progress: null,
            run_summary: summary({ project_id: "project-2" }),
          },
        ],
      }),
  });

  await assert.rejects(
    adapter.client.listMyWork(scope),
    (error) => error?.message === "cloud_my_work_contract_invalid",
  );
});

test("Activity uses authority revision and localStorage only for offline retry", async () => {
  const storage = memoryStorage();
  const retryStore = createLocalStorageActivityReadRetryStore(storage);
  const calls = [];
  let offline = true;
  const adapter = createDesktopAgentAuthorityAdapter(cloudConfig, {
    retryStore,
    fetchImpl: async (url, init = {}) => {
      calls.push({ url: String(url), init });
      if (init.method === "PUT" && offline)
        throw new TypeError("network offline");
      if (init.method === "PUT") {
        const body = JSON.parse(init.body);
        assert.equal(body.expected_authority_revision, 2);
        assert.deepEqual(body.entries, [
          {
            entry_id: "agent_run:run-1",
            entry_revision: 7,
            read_at: "2026-08-04T02:00:00Z",
          },
        ]);
        return jsonResponse({
          project_id: "project-1",
          authority_revision: 3,
          entries: body.entries,
        });
      }
      return jsonResponse({
        project_id: "project-1",
        authority_revision: 2,
        entries: [],
      });
    },
  });
  const receipt = {
    entry_id: "agent_run:run-1",
    entry_revision: 7,
    read_at: "2026-08-04T02:00:00Z",
  };

  const queued = await adapter.client.putActivityReadState(scope, {
    expected_authority_revision: 2,
    entries: [receipt],
  });
  assert.deepEqual(queued, {
    kind: "queued_offline",
    availability: "degraded",
    reasonCode: "cloud_activity_read_state_offline_retry_pending",
    expectedAuthorityRevision: 2,
    entries: [receipt],
  });
  assert.deepEqual(retryStore.load(scope), [receipt]);

  offline = false;
  const flushed = await adapter.client.flushPendingActivityReadState(scope);
  assert.equal(flushed.kind, "synced");
  assert.equal(flushed.state.authority_revision, 3);
  assert.deepEqual(retryStore.load(scope), []);
  assert.equal(calls.filter((call) => call.init.method === "PUT").length, 2);
});

test("Activity conflict is not mislabeled as offline or cached", async () => {
  const retryStore = createLocalStorageActivityReadRetryStore(memoryStorage());
  const adapter = createDesktopAgentAuthorityAdapter(cloudConfig, {
    retryStore,
    fetchImpl: async () => jsonResponse({ detail: "revision conflict" }, 409),
  });

  await assert.rejects(
    adapter.client.putActivityReadState(scope, {
      expected_authority_revision: 2,
      entries: [
        {
          entry_id: "agent_run:run-1",
          entry_revision: 7,
          read_at: "2026-08-04T02:00:00Z",
        },
      ],
    }),
    (error) => error?.status === 409,
  );
  assert.deepEqual(retryStore.load(scope), []);
});

test("Activity invalid server contracts are not mislabeled as offline or cached", async () => {
  const retryStore = createLocalStorageActivityReadRetryStore(memoryStorage());
  const adapter = createDesktopAgentAuthorityAdapter(cloudConfig, {
    retryStore,
    fetchImpl: async () =>
      jsonResponse({ project_id: "project-1", entries: [] }),
  });

  await assert.rejects(
    adapter.client.putActivityReadState(scope, {
      expected_authority_revision: 2,
      entries: [
        {
          entry_id: "agent_run:run-1",
          entry_revision: 7,
          read_at: "2026-08-04T02:00:00Z",
        },
      ],
    }),
    (error) => error?.message === "cloud_activity_read_state_contract_invalid",
  );
  assert.deepEqual(retryStore.load(scope), []);
});

test("Run Summary and scoped Changes preserve revision and attribution contracts", async () => {
  const calls = [];
  const adapter = createDesktopAgentAuthorityAdapter(cloudConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      if (String(url).endsWith("/summary")) return jsonResponse(summary());
      return jsonResponse({
        id: "cloud-change-snapshot-1",
        run_id: "run-1",
        conversation_id: "conversation-1",
        run_revision: 7,
        environment_id: "environment-1",
        repository_root: "/repo",
        workspace_path: "/repo/workspace",
        branch: "codex/test",
        base_revision: "base-sha",
        head_revision: null,
        status: "ready",
        reason: null,
        additions: 2,
        deletions: 1,
        files_changed: 1,
        truncated: false,
        captured_at: "2026-08-04T01:01:00Z",
        files: [
          {
            path: "src/example.ts",
            old_path: null,
            status: "modified",
            additions: 2,
            deletions: 1,
            binary: false,
            untracked: false,
            patch_digest: "patch-1",
            hunks: [
              {
                header: "@@ -1 +1 @@",
                old_start: 1,
                new_start: 1,
                lines: [
                  {
                    kind: "addition",
                    old_line: null,
                    new_line: 1,
                    text: "next",
                  },
                ],
              },
            ],
          },
        ],
        scope: "turn",
        turn_id: "turn-1",
        snapshot_revision: "snapshot-revision-1",
        attribution: [
          {
            file_path: "src/example.ts",
            hunk_id: "hunk-1",
            attribution: "attributed",
            turn_id: "turn-1",
            event_id: "event-1",
            event_revision: "10:1",
            payload: { path: "src/example.ts" },
          },
        ],
      });
    },
  });

  const runSummary = await adapter.client.getRunSummary(scope, "run-1");
  const changes = await adapter.client.getRunChanges(scope, "run-1", {
    scope: "turn",
    turn_id: "turn-1",
    expected_revision: 7,
  });

  assert.equal(
    runSummary.completion_summary,
    "Implemented the requested change.",
  );
  assert.equal(changes.snapshot_revision, "snapshot-revision-1");
  assert.equal(changes.attribution[0].event_revision, "10:1");
  assert.match(calls[1].url, /scope=turn/);
  assert.match(calls[1].url, /turn_id=turn-1/);
  assert.match(calls[1].url, /expected_revision=7/);
});

test("turn-scoped Changes require a turn_id before transport", async () => {
  let fetched = false;
  const adapter = createDesktopAgentAuthorityAdapter(cloudConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async () => {
      fetched = true;
      return jsonResponse({});
    },
  });

  await assert.rejects(
    adapter.client.getRunChanges(scope, "run-1", {
      scope: "turn",
      expected_revision: 7,
    }),
    (error) => error?.message === "cloud_run_changes_turn_id_required",
  );
  assert.equal(fetched, false);
});

test("Cloud Changes project into the existing Desktop review model without sharing arrays", () => {
  const cloud = changes();
  const projected = desktopChangeSnapshotFromCloud(cloud);

  assert.equal(projected.id, cloud.id);
  assert.equal(projected.scope, "run");
  assert.equal(projected.snapshot_revision, "snapshot-revision-1");
  assert.deepEqual(projected.attribution, cloud.attribution);
  assert.notEqual(projected.attribution, cloud.attribution);
  assert.deepEqual(projected.files, cloud.files);
  assert.notEqual(projected.files, cloud.files);
  assert.notEqual(projected.files[0].hunks, cloud.files[0].hunks);
});
