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
  resolveActivityAuthorityBinding,
} = require("/tmp/agistack-desktop-test-dist/src/features/activity/useActivityInbox.js");

const localConfig = {
  apiBaseUrl: "http://127.0.0.1:43121",
  deviceAuthorizationBaseUrl: "http://127.0.0.1:43121",
  apiKey: "local-session-credential",
  localApiToken: "local-launch-capability",
  tenantId: "tenant-1",
  projectId: "project-1",
  workspaceId: "workspace-1",
  mode: "local",
  workspaceRoot: "/workspace",
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
  };
}

test("Local adapter exposes only the narrow Activity authority client", () => {
  const adapter = createDesktopAgentAuthorityAdapter(localConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async () => {
      throw new Error("must not fetch before an Activity operation");
    },
  });

  assert.equal(adapter.authority, "local");
  assert.equal(adapter.availability, "available");
  assert.equal(adapter.reasonCode, null);
  assert.equal(adapter.client, null);
  assert.deepEqual(adapter.allowedActions, ["read_activity", "write_activity"]);
  assert.equal(typeof adapter.activityClient.getActivityReadState, "function");
  assert.deepEqual(adapter.activityScope, {
    authority: "local",
    principalId: "local-user",
    tenantId: "tenant-1",
    projectId: "project-1",
  });
  const binding = resolveActivityAuthorityBinding(adapter, undefined);
  assert.equal(binding.client, adapter.activityClient);
  assert.equal(binding.scope, adapter.activityScope);
});

test("Local Activity GET uses the canonical path, launch credential, and response contract", async () => {
  const calls = [];
  const adapter = createDesktopAgentAuthorityAdapter(localConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      return jsonResponse({
        project_id: "project-1",
        authority_revision: 3,
        entries: [
          {
            entry_id: "desktop_run:run-1",
            entry_revision: 7,
            read_at: "2026-08-05T01:00:00Z",
          },
        ],
      });
    },
  });

  const state = await adapter.activityClient.getActivityReadState(
    adapter.activityScope,
  );

  assert.equal(state.authority_revision, 3);
  assert.equal(state.entries[0].entry_id, "desktop_run:run-1");
  assert.equal(
    calls[0].url,
    "http://127.0.0.1:43121/api/v1/projects/project-1/activity/read-state",
  );
  assert.equal(
    new Headers(calls[0].init.headers).get("Authorization"),
    "Bearer local-session-credential",
  );
  assert.equal(
    new Headers(calls[0].init.headers).get("x-agistack-launch"),
    "local-launch-capability",
  );
});

test("Local Activity PUT preserves the canonical request and receipt shape", async () => {
  const calls = [];
  const adapter = createDesktopAgentAuthorityAdapter(localConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      return jsonResponse({
        project_id: "project-1",
        authority_revision: 4,
        entries: [
          {
            entry_id: "desktop_run:run-1",
            entry_revision: 8,
            read_at: "2026-08-05T02:00:00Z",
          },
        ],
      });
    },
  });
  const request = {
    expected_authority_revision: 3,
    entries: [
      {
        entry_id: "desktop_run:run-1",
        entry_revision: 8,
        read_at: "2026-08-05T02:00:00Z",
      },
    ],
  };

  const result = await adapter.activityClient.putActivityReadState(
    adapter.activityScope,
    request,
  );

  assert.equal(result.kind, "synced");
  assert.equal(result.state.authority_revision, 4);
  assert.equal(calls[0].init.method, "PUT");
  assert.deepEqual(JSON.parse(calls[0].init.body), request);
});

test("Local Activity scope mismatch fails closed before transport", async () => {
  let fetched = false;
  const adapter = createDesktopAgentAuthorityAdapter(localConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(memoryStorage()),
    fetchImpl: async () => {
      fetched = true;
      return jsonResponse({});
    },
  });

  await assert.rejects(
    adapter.activityClient.getActivityReadState({
      ...adapter.activityScope,
      projectId: "project-2",
    }),
    (error) =>
      error?.message === "local_activity_authority_runtime_scope_mismatch",
  );
  assert.equal(fetched, false);
});

test("Local Activity offline writes retain receipts and replay against the latest revision", async () => {
  const storage = memoryStorage();
  const calls = [];
  let online = false;
  const adapter = createDesktopAgentAuthorityAdapter(localConfig, {
    retryStore: createLocalStorageActivityReadRetryStore(storage),
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      if (!online) throw new TypeError("offline");
      if ((init?.method ?? "GET") === "GET") {
        return jsonResponse({
          project_id: "project-1",
          authority_revision: 9,
          entries: [],
        });
      }
      return jsonResponse({
        project_id: "project-1",
        authority_revision: 10,
        entries: JSON.parse(init.body).entries,
      });
    },
  });
  const entry = {
    entry_id: "desktop_run:run-1",
    entry_revision: 8,
    read_at: "2026-08-05T02:00:00Z",
  };

  const queued = await adapter.activityClient.putActivityReadState(
    adapter.activityScope,
    { expected_authority_revision: 3, entries: [entry] },
  );
  online = true;
  const replayed = await adapter.activityClient.flushPendingActivityReadState(
    adapter.activityScope,
  );

  assert.equal(queued.kind, "queued_offline");
  assert.equal(
    queued.reasonCode,
    "local_activity_read_state_offline_retry_pending",
  );
  assert.equal(replayed.kind, "synced");
  assert.equal(replayed.state.authority_revision, 10);
  assert.equal(JSON.parse(calls.at(-1).init.body).expected_authority_revision, 9);
});
