import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const ROOT = "/tmp/agistack-desktop-test-dist";
const runtime = require("@agistack/plugin-runtime");
const moduleV2 = require(
  `${ROOT}/src/plugins/desktopTenantTrustAuthorityModuleV2.js`,
);
const config = () => ({
  apiBaseUrl: "https://api.test",
  deviceAuthorizationBaseUrl: "https://api.test",
  apiKey: "key",
  localApiToken: "local",
  tenantId: "tenant-1",
  projectId: "project-1",
  workspaceId: "workspace-1",
  mode: "cloud",
  workspaceRoot: "",
});
const scope = () => ({
  authority: "cloud",
  tenantId: "tenant-1",
  workspaceId: "workspace-1",
});
const policy = () => ({
  id: "policy-1",
  tenantId: "tenant-1",
  workspaceId: "workspace-1",
  agentInstanceId: "agent-1",
  actionType: "terminal.execute",
  grantedBy: "user-1",
  grantType: "once",
  scope: "agent",
  revision: 1,
  revokedBy: null,
  revokedAt: null,
  createdAt: "2026-09-04T00:00:00Z",
  deletedAt: null,
});
const snapshot = (marker) => {
  const data = { membershipRole: "owner", policies: [policy()] };
  return {
    scope: scope(),
    authority: "cloud",
    availability: "available",
    reasonCode: null,
    contractVersion: "4.0.0",
    allowedActions: ["view", "create"],
    data,
    ...data,
    marker,
  };
};
const service = (client) => Object.freeze({ bindOperation: () => client });
const actions = (value, lifecycle = [], releaseError) => ({
  async acquireServiceOperationLease(descriptor) {
    lifecycle.push(["acquire", descriptor]);
    return {
      status: "accepted",
      useService: (use) => use(value),
      async release() {
        lifecycle.push(["release"]);
        if (releaseError) throw releaseError;
      },
    };
  },
});

test("catalog registers the exact Tenant Trust Provider", () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) =>
      item.module_ref === moduleV2.DESKTOP_TENANT_TRUST_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(
    moduleV2.desktopTenantTrustAuthorityDefinitionV2.contractDigest,
    entry.contract_digest,
  );
  assert.deepEqual(entry.contract.services.provides, [
    {
      service: moduleV2.DESKTOP_TENANT_TRUST_AUTHORITY_SERVICE_V2,
      version: "1.0.0",
    },
  ]);
});
test("load and mutations hold exact tenant leases and freeze inputs", async () => {
  const lifecycle = [];
  const client = {
    async load() {
      return snapshot("load");
    },
    async create(_scope, input) {
      lifecycle.push(["create", input]);
      return policy();
    },
    async revoke(_scope, id) {
      lifecycle.push(["revoke", id]);
      return policy();
    },
  };
  const operations = moduleV2.createDesktopTenantTrustOperationsV2(() =>
    actions(service(client), lifecycle),
  );
  assert.equal(
    (
      await operations.loadTenantTrustPolicies({
        config: config(),
        scope: scope(),
      })
    ).marker,
    "load",
  );
  await operations.createTenantTrustPolicy({
    config: config(),
    scope: scope(),
    policy: {
      agentInstanceId: "agent-1",
      actionType: "terminal.execute",
      grantType: "once",
    },
  });
  await operations.revokeTenantTrustPolicy({
    config: config(),
    scope: scope(),
    policyId: "policy-1",
  });
  assert.deepEqual(
    lifecycle
      .filter(([kind]) => kind === "acquire")
      .map(([, value]) => value.scope),
    Array(3).fill({ kind: "tenant", tenant_id: "tenant-1" }),
  );
});
test("invalid scope and malformed response fail closed before or after admission", async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantTrustOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return actions(
        service({
          async load() {
            return {};
          },
          async create() {},
          async revoke() {},
        }),
      ).acquireServiceOperationLease({});
    },
  }));
  assert.throws(
    () =>
      operations.loadTenantTrustPolicies({
        config: config(),
        scope: { ...scope(), workspaceId: "other" },
      }),
    (error) => error.code === "desktop_tenant_trust_operation_input_invalid",
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () =>
      operations.loadTenantTrustPolicies({ config: config(), scope: scope() }),
    (error) => error.code === "desktop_tenant_trust_operation_response_invalid",
  );
});
test("HMR pins in-flight work and primary error outranks release error", async () => {
  let finish;
  const client = (load) => ({
    load,
    async create() {
      return policy();
    },
    async revoke() {
      return policy();
    },
  });
  let current = actions(
    service(
      client(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      ),
    ),
  );
  const operations = moduleV2.createDesktopTenantTrustOperationsV2(
    () => current,
  );
  const pending = operations.loadTenantTrustPolicies({
    config: config(),
    scope: scope(),
  });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(client(async () => snapshot("new"))));
  finish(snapshot("old"));
  assert.equal((await pending).marker, "old");
  assert.equal(
    (
      await operations.loadTenantTrustPolicies({
        config: config(),
        scope: scope(),
      })
    ).marker,
    "new",
  );
  const primary = new Error("primary");
  const failing = moduleV2.createDesktopTenantTrustOperationsV2(() =>
    actions(
      service(
        client(async () => {
          throw primary;
        }),
      ),
      [],
      new Error("release"),
    ),
  );
  await assert.rejects(
    () => failing.loadTenantTrustPolicies({ config: config(), scope: scope() }),
    primary,
  );
});
