import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
const require = createRequire(import.meta.url);
const {
  executeVaultBoundCloudRequest,
} = require("/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js");
function harness(status = 200) {
  const paths = [];
  return {
    paths,
    dependencies: {
      async loadTrustedSession() {
        return {
          version: 1,
          api_base_url: "https://cloud.memstack.test",
          runtime_mode: "cloud",
          credential_kind: "cloud_bearer",
          credential: "test-only-vault-token",
          expires_at: null,
        };
      },
      async fetch(url, init) {
        const path = new URL(url).pathname;
        if (path === "/api/v1/mcp/server-1" && init.method === "GET") {
          paths.push(path);
          return new Response(
            JSON.stringify({
              id: "server-1",
              tenant_id: "tenant-1",
              project_id: "project-1",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        paths.push(path);
        return new Response(
          JSON.stringify(
            path === "/api/v1/workspace-context"
              ? {
                  context: {
                    tenant_id: "tenant-1",
                    project_id: "project-1",
                    revision: 1,
                  },
                }
              : status === 200
                ? []
                : { detail: "Forbidden" },
          ),
          {
            status: path === "/api/v1/workspace-context" ? 200 : status,
            headers: { "Content-Type": "application/json" },
          },
        );
      },
    },
  };
}

test("provider settings read requests and MCP list reach the vault bound cloud API", async () => {
  for (const path of [
    "/api/v1/llm-providers/?include_inactive=true",
    "/api/v1/llm-providers/types",
    "/api/v1/llm-providers/models/openai",
    "/api/v1/llm-providers/provider-1/usage",
    "/api/v1/mcp?project_id=project-1",
    "/api/v1/mcp/server-1",
  ]) {
    const h = harness();
    assert.equal(
      (
        await executeVaultBoundCloudRequest(
          { path, method: "GET" },
          h.dependencies,
        )
      ).status,
      200,
    );
    assert.equal(
      h.paths.at(-1),
      new URL(path, "https://test.invalid").pathname,
    );
  }
});
test("existing settings mutations preserve backend denial and project scoping", async () => {
  for (const input of [
    {
      path: "/api/v1/llm-providers/",
      method: "POST",
      body: {
        name: "QA",
        provider_type: "openai",
        auth_method: "api_key",
        is_active: true,
      },
    },
    {
      path: "/api/v1/llm-providers/provider-1",
      method: "PUT",
      body: { name: "QA", expected_revision: 0 },
    },
    {
      path: "/api/v1/llm-providers/provider-1",
      method: "DELETE",
      body: { expected_revision: 0, idempotency_key: "qa-delete" },
    },
    {
      path: "/api/v1/llm-providers/test-connection",
      method: "POST",
      body: { provider_type: "openai" },
    },
    {
      path: "/api/v1/llm-providers/provider-1/health-check",
      method: "POST",
      body: {},
    },
    {
      path: "/api/v1/mcp",
      method: "POST",
      body: {
        project_id: "project-1",
        name: "QA",
        server_type: "sse",
        transport_config: { url: "https://test.invalid" },
        idempotency_key: "qa-create",
      },
    },
    {
      path: "/api/v1/mcp/server-1",
      method: "PUT",
      body: {
        project_id: "project-1",
        enabled: false,
        idempotency_key: "qa-disable",
      },
    },
    {
      path: "/api/v1/mcp/server-1",
      method: "DELETE",
      body: { project_id: "project-1", idempotency_key: "qa-delete" },
    },
    { path: "/api/v1/mcp/server-1/test", method: "POST" },
  ]) {
    const h = harness(403);
    assert.equal(
      (await executeVaultBoundCloudRequest(input, h.dependencies)).status,
      403,
    );
  }
  for (const input of [
    { path: "/api/v1/mcp?project_id=other", method: "GET" },
    {
      path: "/api/v1/mcp/server-1",
      method: "PUT",
      body: { project_id: "other", enabled: true },
    },
    {
      path: "/api/v1/llm-providers/routing-policy?project_id=other&workspace_id=workspace-1",
      method: "GET",
    },
  ]) {
    const h = harness();
    await assert.rejects(
      executeVaultBoundCloudRequest(input, h.dependencies),
      /project scope mismatch/,
    );
    assert.deepEqual(h.paths, ["/api/v1/workspace-context"]);
  }
});
test("settings gateway rejects unsupported actions and malformed request shapes before network", async () => {
  for (const input of [
    {
      path: "/api/v1/llm-providers/?include_inactive=true&include_inactive=false",
      method: "GET",
    },
    {
      path: "/api/v1/llm-providers/?include_inactive=true&tenant_id=other",
      method: "GET",
    },
    { path: "/api/v1/llm-providers/types", method: "DELETE" },
    {
      path: "/api/v1/llm-providers/provider-1/models/discover",
      method: "POST",
    },
    {
      path: "/api/v1/llm-providers/provider-1",
      method: "PUT",
      body: { expected_revision: 0, is_superuser: true },
    },
    {
      path: "/api/v1/mcp?project_id=project-1&project_id=other",
      method: "GET",
    },
    { path: "/api/v1/mcp/credentials/provision", method: "POST" },
    {
      path: "/api/v1/mcp/server-1",
      method: "PUT",
      body: { project_id: "project-1", secret: "not-a-real-secret" },
    },
    {
      path: "/api/v1/mcp/server-1/test",
      method: "POST",
      body: { command: "unexpected" },
    },
    {
      path: "/api/v1/mcp",
      method: "POST",
      body: { project_id: "project-1" },
      mutation: { kind: "idempotency-only", idempotency_key: "extra" },
    },
    {
      path: "/api/v1/llm-providers/provider-1",
      method: "PUT",
      body: { expected_revision: 0 },
      mutation: { kind: "idempotency-only", idempotency_key: "extra" },
    },
  ]) {
    const h = harness();
    await assert.rejects(
      executeVaultBoundCloudRequest(input, h.dependencies),
      /endpoint is not allowed/,
    );
    assert.deepEqual(h.paths, []);
  }
});

test("MCP target observation blocks other project resources before mutation", async () => {
  for (const method of ["GET", "PUT", "DELETE", "POST"]) {
    const h = harness();
    const original = h.dependencies.fetch;
    h.dependencies.fetch = async (url, init) =>
      new URL(url).pathname === "/api/v1/mcp/server-1"
        ? new Response(
            JSON.stringify({
              id: "server-1",
              tenant_id: "tenant-1",
              project_id: "other",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          )
        : original(url, init);
    await assert.rejects(
      executeVaultBoundCloudRequest(
        {
          path: "/api/v1/mcp/server-1" + (method === "POST" ? "/test" : ""),
          method,
          ...(["PUT", "DELETE"].includes(method)
            ? { body: { project_id: "project-1", idempotency_key: "key" } }
            : {}),
        },
        h.dependencies,
      ),
      /MCP server scope observation failed/,
    );
  }
});
test("provider create accepts only its existing idempotency mutation envelope", async () => {
  const h = harness();
  assert.equal(
    (
      await executeVaultBoundCloudRequest(
        {
          path: "/api/v1/llm-providers/",
          method: "POST",
          body: { name: "QA" },
          mutation: { kind: "idempotency-only", idempotency_key: "qa-create" },
        },
        h.dependencies,
      )
    ).status,
    200,
  );
});
