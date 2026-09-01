import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";

const COMPILED_ROOT = "/tmp/agistack-desktop-test-dist";
const require = createRequire(import.meta.url);
const {
  createDesktopRendererDefinitionsV2,
  GenerationManagerV2,
  LoaderV2,
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
} = require("@agistack/plugin-runtime");
const {
  DESKTOP_WORKSPACE_CATALOG_AUTHORITY_MODULE_REF_V2,
  DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2,
  DESKTOP_WORKSPACE_CATALOG_AUTHORITY_VERSION_V2,
  DesktopWorkspaceCatalogAuthorityUnavailableErrorV2,
  applyDesktopWorkspaceCatalogAuthorityV2,
  createDesktopWorkspaceCatalogOperationsV2,
  desktopWorkspaceCatalogAuthorityDefinitionV2,
  withDesktopWorkspaceCatalogAuthorityOperationV2,
} = require(
  COMPILED_ROOT + "/src/plugins/desktopWorkspaceCatalogAuthorityModuleV2.js",
);
const {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} = require(
  COMPILED_ROOT + "/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js",
);
const { desktopConversationConfigAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + "/src/plugins/desktopConversationConfigAuthorityModuleV2.js",
);
const { desktopConversationLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT +
    "/src/plugins/desktopConversationLifecycleAuthorityModuleV2.js",
);
const { desktopHitlResponseAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + "/src/plugins/desktopHitlResponseAuthorityModuleV2.js",
);
const { desktopSessionProjectionAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + "/src/plugins/desktopSessionProjectionAuthorityModuleV2.js",
);
const { desktopSessionRunChangesAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + "/src/plugins/desktopSessionRunChangesAuthorityModuleV2.js",
);
const { desktopTenantCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + "/src/plugins/desktopTenantCatalogAuthorityModuleV2.js",
);
const { desktopTerminalLifecycleAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + "/src/plugins/desktopTerminalLifecycleAuthorityModuleV2.js",
);
const { desktopWorkspaceContextAuthorityDefinitionV2 } = require(
  COMPILED_ROOT + "/src/plugins/desktopWorkspaceContextAuthorityModuleV2.js",
);
const { desktopWorkspaceMessageCatalogAuthorityDefinitionV2 } = require(
  COMPILED_ROOT +
    "/src/plugins/desktopWorkspaceMessageCatalogAuthorityModuleV2.js",
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + "/src/types.js");

const REPOSITORY_ROOT = new URL("../../../../", import.meta.url);
const BOOTSTRAP_PATH = new URL(
  "shared/profiles/memstack-default-bootstrap.v2.json",
  REPOSITORY_ROOT,
);
const MANIFEST_PATH = new URL(
  "config/plugin-manifests-v2/memstack-renderer-target-hosts.v2.json",
  REPOSITORY_ROOT,
);
const PROFILE_PATH = new URL(
  "config/plugin-profiles/memstack-production-target-hosts.v2.yaml",
  REPOSITORY_ROOT,
);

function loadBootstrap() {
  return JSON.parse(readFileSync(BOOTSTRAP_PATH, "utf8"));
}

function rendererDefinitions() {
  return [
    ...createDesktopRendererDefinitionsV2(),
    desktopWorkspaceContextAuthorityDefinitionV2,
    desktopPluginMarketplaceCatalogDefinitionV2,
    desktopPluginMarketplaceManagementDefinitionV2,
    desktopConversationConfigAuthorityDefinitionV2,
    desktopConversationLifecycleAuthorityDefinitionV2,
    desktopHitlResponseAuthorityDefinitionV2,
    desktopSessionProjectionAuthorityDefinitionV2,
    desktopSessionRunChangesAuthorityDefinitionV2,
    desktopTerminalLifecycleAuthorityDefinitionV2,
    desktopTenantCatalogAuthorityDefinitionV2,
    desktopWorkspaceMessageCatalogAuthorityDefinitionV2,
    desktopWorkspaceCatalogAuthorityDefinitionV2,
  ];
}

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: "http://127.0.0.1:46501",
    apiKey: "workspace-catalog-session",
    localApiToken: "workspace-catalog-launch",
    mode: "local",
    tenantId: "tenant / one",
    projectId: "project / one",
    workspaceId: "",
    workspaceRoot: "/workspace",
    ...overrides,
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function workspaceRecord(id, tenantId, projectId) {
  return {
    id,
    tenant_id: tenantId,
    project_id: projectId,
    name: `Workspace ${id}`,
    created_by: "user-1",
    description: null,
    is_archived: false,
    metadata: {},
    office_status: "idle",
    hex_layout_config: {},
    created_at: "2026-09-01T00:00:00Z",
    updated_at: null,
  };
}

function acceptedActions(service, digest, lifecycle = []) {
  return {
    acquireServiceOperationLease: async (request) => {
      lifecycle.push({ type: "acquire", digest, request });
      let released = false;
      return {
        status: "accepted",
        digest,
        useService(operation) {
          if (released) throw new Error("lease_released");
          return operation(service);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push({ type: "release", digest });
        },
      };
    },
  };
}

test("generated manifest, catalog and Profile expose one credential-free root Provider", () => {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, "utf8"));
  const profile = readFileSync(PROFILE_PATH, "utf8");
  const bootstrap = loadBootstrap();
  const module = manifest.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  const catalog = PLUGIN_MODULE_CATALOG_V2.modules.find(
    ({ module_ref: moduleRef }) =>
      moduleRef === DESKTOP_WORKSPACE_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  const entry = bootstrap.entries.find(
    ({ entry_id: entryId }) =>
      entryId === "builtin-desktop-workspace-catalog-authority",
  );

  assert.ok(module);
  assert.ok(catalog);
  assert.ok(entry);
  assert.deepEqual(module.targets, ["desktop-renderer"]);
  assert.deepEqual(module.contract.services, {
    provides: [
      {
        service: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_VERSION_V2,
      },
    ],
    requires: [],
  });
  assert.deepEqual(module.contract.events, { emits: [], handles: [] });
  assert.equal(module.contract.config_schema.additionalProperties, false);
  assert.deepEqual(module.contract.config_schema.required, ["strategy"]);
  assert.equal(
    module.contract.config_schema.properties.strategy.const,
    "desktop-api-client",
  );
  assert.equal(module.contract_digest, catalog.contract_digest);
  assert.equal(
    module.contract_digest,
    desktopWorkspaceCatalogAuthorityDefinitionV2.contractDigest,
  );
  assert.equal(catalog.entrypoint, "applyDesktopWorkspaceCatalogAuthorityV2");
  assert.equal(
    catalog.artifact_source,
    "repo+typescript://agi-stack/apps/desktop/src/plugins/" +
      "desktopWorkspaceCatalogAuthorityModuleV2.ts",
  );
  assert.equal(
    entry.module_ref,
    DESKTOP_WORKSPACE_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  assert.equal(entry.parent_entry_id, "builtin-desktop-renderer-host");
  assert.deepEqual(entry.scope, { kind: "root" });
  assert.deepEqual(entry.config, { strategy: "desktop-api-client" });
  assert.deepEqual(entry.inject, {});
  assert.equal(entry.enabled, true);
  assert.match(
    profile,
    /entry_id: builtin-desktop-workspace-catalog-authority/u,
  );
  for (const value of [module, catalog, entry]) {
    assert.doesNotMatch(
      JSON.stringify(value),
      /apiKey|localApiToken|Authorization|workspace-catalog-session/iu,
    );
  }
});

test("Loader activates the exact service and Profile disable removes it without fallback", async () => {
  const bootstrap = loadBootstrap();
  const loader = new LoaderV2(rendererDefinitions(), "desktop-renderer");
  const generation = await loader.stage(bootstrap);
  const service = generation.resolve(
    DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2,
    { kind: "project", tenant_id: "tenant / one", project_id: "project / one" },
    { version: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_VERSION_V2 },
  );

  assert.equal(Object.isFrozen(service), true);
  assert.deepEqual(Object.keys(service), ["bindOperation"]);
  assert.equal("config" in service, false);
  assert.equal("client" in service, false);
  assert.throws(
    () =>
      applyDesktopWorkspaceCatalogAuthorityV2(
        {
          provide: () =>
            assert.fail("invalid config must not provide a service"),
        },
        { strategy: "legacy-client" },
      ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === "desktop_workspace_catalog_authority_config_invalid",
  );

  const invalid = structuredClone(bootstrap);
  invalid.entries.find(
    ({ entry_id: entryId }) =>
      entryId === "builtin-desktop-workspace-catalog-authority",
  ).config.strategy = "legacy-client";
  await assert.rejects(
    loader.stage(invalid),
    (error) =>
      error instanceof RuntimeV2Error && error.code === "invalid_module_config",
  );

  const disabled = structuredClone(bootstrap);
  disabled.entries.find(
    ({ entry_id: entryId }) =>
      entryId === "builtin-desktop-workspace-catalog-authority",
  ).enabled = false;
  const disabledGeneration = await loader.stage(disabled);
  assert.throws(
    () =>
      disabledGeneration.resolve(
        DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2,
        {
          kind: "project",
          tenant_id: "tenant / one",
          project_id: "project / one",
        },
        { version: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_VERSION_V2 },
      ),
    (error) =>
      error instanceof RuntimeV2Error && error.code === "missing_service",
  );

  const manager = new GenerationManagerV2();
  await manager.publish(generation);
  const wrongDefinitionLoader = new LoaderV2(
    rendererDefinitions().map((definition) =>
      definition.moduleRef === DESKTOP_WORKSPACE_CATALOG_AUTHORITY_MODULE_REF_V2
        ? { ...definition, contractDigest: "sha256:" + "0".repeat(64) }
        : definition,
    ),
    "desktop-renderer",
  );
  await assert.rejects(
    wrongDefinitionLoader.stage(bootstrap),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === "contract_digest_mismatch",
  );
  assert.equal(manager.current, generation);
  await disabledGeneration.dispose();
  await manager.close();
});

test("local and cloud operations freeze config and forward AbortSignal through exact transport", async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const fetchCalls = [];
  const cloudCommands = [];
  globalThis.fetch = async (input, init) => {
    fetchCalls.push({ input: String(input), init });
    return json([
      workspaceRecord("local-workspace", "tenant / one", "project / one"),
    ]);
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          cloudCommands.push({ command, args });
          return {
            status: 200,
            body: [
              workspaceRecord(
                "cloud-workspace",
                "tenant / one",
                "project / one",
              ),
            ],
          };
        },
      },
    },
  };

  try {
    const generation = await new LoaderV2(
      rendererDefinitions(),
      "desktop-renderer",
    ).stage(loadBootstrap());
    const service = generation.resolve(
      DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2,
      {
        kind: "project",
        tenant_id: "tenant / one",
        project_id: "project / one",
      },
      { version: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_VERSION_V2 },
    );
    const controller = new AbortController();
    const localConfig = runtimeConfig();
    const local = service.bindOperation(localConfig);
    localConfig.apiBaseUrl = "http://127.0.0.1:46999";
    localConfig.apiKey = "mutated-session";
    localConfig.projectId = "mutated-project";
    const cloud = service.bindOperation(
      runtimeConfig({
        apiBaseUrl: "https://cloud.example.test",
        apiKey: "",
        localApiToken: "",
        mode: "cloud",
      }),
    );

    const localResult = await local.listWorkspacesForProject(controller.signal);
    const cloudResult = await cloud.listWorkspacesForProject(controller.signal);
    assert.equal(localResult[0].id, "local-workspace");
    assert.equal(cloudResult[0].id, "cloud-workspace");
    assert.equal(Object.isFrozen(local), true);
    assert.equal(Object.isFrozen(cloud), true);
    assert.deepEqual(Object.keys(local), ["listWorkspacesForProject"]);
    assert.equal(fetchCalls.length, 1);
    const localUrl = new URL(fetchCalls[0].input);
    assert.equal(localUrl.origin, "http://127.0.0.1:46501");
    assert.equal(
      localUrl.pathname,
      "/api/v1/tenants/tenant%20%2F%20one/projects/project%20%2F%20one/workspaces",
    );
    assert.equal(localUrl.searchParams.get("limit"), "500");
    assert.equal(localUrl.searchParams.get("offset"), "0");
    assert.equal(fetchCalls[0].init.signal, controller.signal);
    const headers = new Headers(fetchCalls[0].init.headers);
    assert.equal(
      headers.get("Authorization"),
      "Bearer workspace-catalog-session",
    );
    assert.equal(headers.get("X-Agistack-Launch"), "workspace-catalog-launch");
    assert.equal(cloudCommands.length, 1);
    assert.equal(cloudCommands[0].command, "cloud_request");
    assert.equal(
      cloudCommands[0].args.request.path,
      "/api/v1/tenants/tenant%20%2F%20one/projects/project%20%2F%20one/" +
        "workspaces?limit=500&offset=0",
    );
    assert.equal(cloudCommands[0].args.request.method, "GET");
    assert.equal(JSON.stringify(cloudCommands).includes("Bearer"), false);
    await generation.dispose();
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test("one project lease stays pinned through the complete paginated catalog read", async () => {
  const originalFetch = globalThis.fetch;
  const lifecycle = [];
  const offsets = [];
  let resolveLastPage;
  const lastPageReady = new Promise((resolve) => {
    resolveLastPage = resolve;
  });
  let generation;
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    const offset = Number(url.searchParams.get("offset"));
    offsets.push(offset);
    if (offset === 0) {
      return json(
        Array.from({ length: 500 }, (_, index) =>
          workspaceRecord(
            `workspace-${index}`,
            "tenant / one",
            "project / one",
          ),
        ),
      );
    }
    await lastPageReady;
    return json([
      workspaceRecord("workspace-500", "tenant / one", "project / one"),
    ]);
  };

  try {
    generation = await new LoaderV2(
      rendererDefinitions(),
      "desktop-renderer",
    ).stage(loadBootstrap());
    const service = generation.resolve(
      DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2,
      {
        kind: "project",
        tenant_id: "tenant / one",
        project_id: "project / one",
      },
      { version: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_VERSION_V2 },
    );
    const operations = createDesktopWorkspaceCatalogOperationsV2(() =>
      acceptedActions(service, "sha256:pagination", lifecycle),
    );
    const pending = operations.listWorkspacesForProject({
      config: runtimeConfig(),
    });
    await new Promise((resolve) => setImmediate(resolve));

    assert.deepEqual(offsets, [0, 500]);
    assert.equal(
      lifecycle.some((event) => event.type === "release"),
      false,
    );
    resolveLastPage();
    const result = await pending;
    assert.equal(result.length, 501);
    assert.deepEqual(
      lifecycle
        .filter((event) => event.type === "release")
        .map((event) => event.digest),
      ["sha256:pagination"],
    );
  } finally {
    resolveLastPage?.();
    await generation?.dispose();
    globalThis.fetch = originalFetch;
  }
});

test("operations acquire the current project generation lease and release after refresh", async () => {
  const lifecycle = [];
  const signals = [];
  const boundConfigs = [];
  const service = Object.freeze({
    bindOperation(config) {
      boundConfigs.push(config);
      return Object.freeze({
        async listWorkspacesForProject(signal) {
          signals.push(signal);
          lifecycle.push("list");
          return [
            workspaceRecord("workspace-1", config.tenantId, config.projectId),
          ];
        },
      });
    },
  });
  let currentActions = acceptedActions(
    service,
    "sha256:generation-1",
    lifecycle,
  );
  const operations = createDesktopWorkspaceCatalogOperationsV2(
    () => currentActions,
  );
  const controller = new AbortController();
  const config = runtimeConfig();
  const pending = operations.listWorkspacesForProject({
    config,
    signal: controller.signal,
  });
  config.apiBaseUrl = "http://127.0.0.1:46999";
  config.apiKey = "mutated-session";
  currentActions = null;

  assert.equal((await pending)[0].id, "workspace-1");
  assert.equal(Object.isFrozen(operations), true);
  assert.equal(Object.isFrozen(boundConfigs[0]), true);
  assert.equal(boundConfigs[0].apiBaseUrl, "http://127.0.0.1:46501");
  assert.equal(boundConfigs[0].apiKey, "workspace-catalog-session");
  assert.equal(signals[0], controller.signal);
  assert.deepEqual(lifecycle[0].request, {
    service: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2,
    version: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_VERSION_V2,
    scope: {
      kind: "project",
      tenant_id: "tenant / one",
      project_id: "project / one",
    },
  });
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === "string"),
    ["list"],
  );
  assert.deepEqual(
    lifecycle
      .filter((event) => event.type === "release")
      .map((event) => event.digest),
    ["sha256:generation-1"],
  );
  assert.throws(
    () => operations.listWorkspacesForProject({ config: runtimeConfig() }),
    (error) =>
      error instanceof DesktopWorkspaceCatalogAuthorityUnavailableErrorV2 &&
      error.reasonCode === "desktop_renderer_generation_actions_unavailable",
  );

  currentActions = {
    acquireServiceOperationLease: async () => ({
      status: "rejected",
      reasonCode: "desktop_renderer_service_resolve_failed",
      runtimeCode: "missing_service",
    }),
  };
  await assert.rejects(
    operations.listWorkspacesForProject({ config: runtimeConfig() }),
    (error) =>
      error instanceof DesktopWorkspaceCatalogAuthorityUnavailableErrorV2 &&
      error.reasonCode === "desktop_renderer_service_resolve_failed" &&
      error.runtimeCode === "missing_service",
  );
});

test("invalid workspace scope fails before lease admission", () => {
  let acquisitions = 0;
  const operations = createDesktopWorkspaceCatalogOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error("must_not_acquire");
    },
  }));

  for (const config of [
    runtimeConfig({ tenantId: "" }),
    runtimeConfig({ projectId: " project-1" }),
    runtimeConfig({ workspaceId: "workspace-1" }),
  ]) {
    assert.throws(
      () => operations.listWorkspacesForProject({ config }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === "desktop_workspace_catalog_input_invalid",
    );
  }
  assert.equal(acquisitions, 0);
});

test("escaped authority is revoked and primary operation failure wins over release failure", async () => {
  const primary = new Error("workspace_catalog_primary_failure");
  let escapedAuthority = null;
  let releaseCount = 0;
  const actions = {
    acquireServiceOperationLease: async () => ({
      status: "accepted",
      digest: "sha256:accepted",
      useService(operation) {
        return operation({
          bindOperation() {
            return Object.freeze({
              async listWorkspacesForProject() {
                return [];
              },
            });
          },
        });
      },
      async release() {
        releaseCount += 1;
        throw new Error("workspace_catalog_release_failure");
      },
    }),
  };

  await assert.rejects(
    withDesktopWorkspaceCatalogAuthorityOperationV2(
      actions,
      { config: runtimeConfig() },
      (authority) => {
        escapedAuthority = authority;
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  assert.throws(
    () => escapedAuthority.listWorkspacesForProject(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === "desktop_workspace_catalog_operation_released",
  );
  assert.equal(releaseCount, 1);

  await assert.rejects(
    withDesktopWorkspaceCatalogAuthorityOperationV2(
      actions,
      { config: runtimeConfig() },
      () => [],
    ),
    /workspace_catalog_release_failure/u,
  );
  assert.equal(releaseCount, 2);
});

test("concurrent project reads acquire and release independent exact leases", async () => {
  const requests = [];
  const releases = [];
  const resolvers = new Map();
  const actions = {
    async acquireServiceOperationLease(request) {
      requests.push(request);
      const projectId = request.scope.project_id;
      let resolveRead;
      const pending = new Promise((resolve) => {
        resolveRead = resolve;
      });
      resolvers.set(projectId, resolveRead);
      return {
        status: "accepted",
        digest: `sha256:${projectId}`,
        useService(operation) {
          return operation({
            bindOperation(config) {
              return Object.freeze({
                async listWorkspacesForProject() {
                  await pending;
                  return [
                    workspaceRecord(
                      projectId,
                      config.tenantId,
                      config.projectId,
                    ),
                  ];
                },
              });
            },
          });
        },
        async release() {
          releases.push(projectId);
        },
      };
    },
  };
  const operations = createDesktopWorkspaceCatalogOperationsV2(() => actions);
  const first = operations.listWorkspacesForProject({
    config: runtimeConfig({ tenantId: "tenant-1", projectId: "project-1" }),
  });
  const second = operations.listWorkspacesForProject({
    config: runtimeConfig({ tenantId: "tenant-2", projectId: "project-2" }),
  });
  await Promise.resolve();

  assert.deepEqual(
    requests.map((request) => request.scope),
    [
      { kind: "project", tenant_id: "tenant-1", project_id: "project-1" },
      { kind: "project", tenant_id: "tenant-2", project_id: "project-2" },
    ],
  );
  resolvers.get("project-2")();
  assert.equal((await second)[0].id, "project-2");
  assert.deepEqual(releases, ["project-2"]);
  resolvers.get("project-1")();
  assert.equal((await first)[0].id, "project-1");
  assert.deepEqual(releases, ["project-2", "project-1"]);
});

test("HMR lets an in-flight read finish on old generation and sends the next to new", async () => {
  const lifecycle = [];
  let resolveOld;
  const oldPending = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const serviceFor = (label) =>
    Object.freeze({
      bindOperation() {
        return Object.freeze({
          async listWorkspacesForProject() {
            lifecycle.push("list:" + label);
            if (label === "old") await oldPending;
            return [
              workspaceRecord(
                "workspace-" + label,
                "tenant / one",
                "project / one",
              ),
            ];
          },
        });
      },
    });
  let currentActions = acceptedActions(
    serviceFor("old"),
    "sha256:old",
    lifecycle,
  );
  const operations = createDesktopWorkspaceCatalogOperationsV2(
    () => currentActions,
  );
  const oldRead = operations.listWorkspacesForProject({
    config: runtimeConfig(),
  });
  await Promise.resolve();
  currentActions = acceptedActions(
    serviceFor("next"),
    "sha256:next",
    lifecycle,
  );
  const nextRead = await operations.listWorkspacesForProject({
    config: runtimeConfig(),
  });
  resolveOld();
  const oldReadResult = await oldRead;

  assert.equal(oldReadResult[0].id, "workspace-old");
  assert.equal(nextRead[0].id, "workspace-next");
  assert.deepEqual(
    lifecycle.filter((event) => typeof event === "string"),
    ["list:old", "list:next"],
  );
  assert.deepEqual(
    lifecycle
      .filter((event) => event.type === "release")
      .map((event) => event.digest),
    ["sha256:next", "sha256:old"],
  );
});
