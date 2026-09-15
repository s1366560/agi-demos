import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { afterEach, test } from "node:test";

const require = createRequire(import.meta.url);
const {
  settleTrustedSessionRestoreFailure,
  TrustedSessionAuthenticationInvalidError,
} = require("/tmp/agistack-desktop-test-dist/src/api/trustedSessionRecovery.js");
const {
  desktopCloudSessionProjectionClient,
} = require("/tmp/agistack-desktop-test-dist/src/api/cloudSessionProjectionClient.js");
const {
  projectVaultBoundCloudSession,
  CloudSessionAuthenticationInvalidError,
} = require("/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js");
afterEach(() => {
  delete globalThis.window;
});

const session = {
  version: 1,
  api_base_url: "https://cloud.example.test",
  runtime_mode: "cloud",
  credential_kind: "cloud_bearer",
  credential: "test-only-bearer",
  expires_at: null,
};

for (const status of [401, 403, 429, 500, 503]) {
  test(`restore HTTP ${status} clears credentials only for authentication failure`, async () => {
    let clears = 0;
    globalThis.window = {
      __MEMSTACK_DESKTOP__: {
        core: {
          invoke: async () => {
            try {
              return await projectVaultBoundCloudSession({
                loadTrustedSession: async () => session,
                fetch: async () => new Response("{}", { status }),
              });
            } catch (error) {
              if (error instanceof CloudSessionAuthenticationInvalidError) {
                return {
                  status: "restore_error",
                  reason: "authentication_invalid",
                };
              }
              throw error;
            }
          },
        },
      },
    };
    const error = await desktopCloudSessionProjectionClient()
      .load()
      .catch((caught) => caught);
    assert(error instanceof Error);
    const recovery = await settleTrustedSessionRestoreFailure(
      error,
      async () => {
        clears++;
      },
    );
    assert.equal(clears, status === 401 ? 1 : 0);
    assert.equal(recovery, status === 401 ? "reauthenticate" : "retry");
  });
}

test("offline, malformed projection and plugin authority errors preserve saved credentials", async () => {
  for (const failure of [
    new TypeError("fetch failed"),
    new Error("renderer_credential_required"),
    new Error("cloud_session_projection_contract_invalid"),
    new Error("401"),
  ]) {
    let clears = 0;
    assert.equal(
      await settleTrustedSessionRestoreFailure(failure, async () => {
        clears++;
      }),
      "retry",
    );
    assert.equal(clears, 0);
  }
});

test("a rejected vault clear remains an error rather than claiming sign-out succeeded", async () => {
  await assert.rejects(
    () =>
      settleTrustedSessionRestoreFailure(
        new TrustedSessionAuthenticationInvalidError(),
        async () => {
          throw new Error("vault unavailable");
        },
      ),
    /vault unavailable/,
  );
});

test("offline restore can retry with the same vault session after the service returns", async () => {
  let online = false;
  let clears = 0;
  let calls = 0;
  const fetch = async (url) => {
    calls++;
    if (!online) throw new TypeError("fetch failed");
    const path = new URL(url).pathname;
    const body =
      path === "/api/v1/workspace-context"
        ? {
            context: {
              tenant_id: "tenant",
              project_id: null,
              workspace_id: null,
              revision: 1,
            },
          }
        : path === "/api/v1/auth/me"
          ? { user_id: "user", roles: [] }
          : path === "/api/v1/tenants/"
            ? {
                tenants: [{ id: "tenant", name: "Tenant" }],
                total: 1,
                page: 1,
                page_size: 100,
              }
            : {
                projects: [],
                owner_ids: [],
                total: 0,
                page: 1,
                page_size: 100,
              };
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  const dependencies = { loadTrustedSession: async () => session, fetch };
  const offline = await projectVaultBoundCloudSession(dependencies).catch(
    (error) => error,
  );
  assert.equal(
    await settleTrustedSessionRestoreFailure(offline, async () => {
      clears++;
    }),
    "retry",
  );
  assert.equal(clears, 0);
  assert.equal(calls, 1);
  online = true;
  const projection = await projectVaultBoundCloudSession(dependencies);
  assert.equal(projection.status, "authenticated");
  assert.equal(calls, 5);
  assert.equal(clears, 0);
});
