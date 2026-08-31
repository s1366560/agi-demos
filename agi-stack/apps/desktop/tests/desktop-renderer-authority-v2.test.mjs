import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
require.extensions[".css"] = () => {};

const {
  DESKTOP_ACTIVITY_INBOX_SURFACE_ARTIFACT_ID_V2,
  DESKTOP_AUTHENTICATED_SHELL_SURFACE_ARTIFACT_ID_V2,
  DESKTOP_AUXILIARY_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_CONVERSATION_SURFACE_ARTIFACT_ID_V2,
  DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
  DESKTOP_MY_WORK_QUEUE_SURFACE_ARTIFACT_ID_V2,
  DESKTOP_NEW_THREAD_COMPOSER_SURFACE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_AGENT_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_ADMINISTRATION_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_KNOWLEDGE_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_RUNTIME_INFRASTRUCTURE_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_RUNTIME_INFRASTRUCTURE_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_WORKSPACE_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_WORKSPACE_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_DISCOVERY_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_DISCOVERY_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_TENANT_CORE_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_TENANT_AGENT_BUILDING_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_TENANT_AGENT_BUILDING_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_TENANT_GOVERNANCE_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_TENANT_GOVERNANCE_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_TENANT_CREATION_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_SESSION_CANVAS_SURFACE_ARTIFACT_ID_V2,
  DESKTOP_SESSION_WORKSPACE_SURFACE_ARTIFACT_ID_V2,
  DESKTOP_WORKSPACE_COLLABORATION_SURFACE_ARTIFACT_ID_V2,
  defineDesktopUiSlotArtifactV2,
  resolveDesktopRendererArtifactsV2,
  DESKTOP_WORKBENCH_SURFACE_ARTIFACT_ID_V2,
} = require("/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererArtifactCatalogV2.js");
const {
  createDesktopRendererAppCompositionPortV2,
} = require("/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererAppCompositionV2.js");
const {
  DesktopConversationSurfaceV2,
} = require("/tmp/agistack-desktop-test-dist/src/plugins/DesktopConversationSurfaceV2.js");
const {
  DesktopMyWorkQueueSurfaceV2,
} = require("/tmp/agistack-desktop-test-dist/src/plugins/DesktopMyWorkQueueSurfaceV2.js");
const {
  DesktopNewThreadComposerSurfaceV2,
} = require("/tmp/agistack-desktop-test-dist/src/plugins/DesktopNewThreadComposerSurfaceV2.js");
const {
  DesktopSessionWorkspaceSurfaceV2,
} = require("/tmp/agistack-desktop-test-dist/src/plugins/DesktopSessionWorkspaceSurfaceV2.js");
const {
  DesktopWorkspaceCollaborationSurfaceV2,
} = require("/tmp/agistack-desktop-test-dist/src/plugins/DesktopWorkspaceCollaborationSurfaceV2.js");
const {
  isDesktopNavigationRouteEnabledV2,
  projectDesktopNavigationRegistryV2,
  projectDesktopRouteRegistryV2,
  selectDesktopUiSlotsV2,
} = require("/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererAuthorityStateV2.js");
const {
  createDesktopRouteRegistry,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js");

function contribution(id, kind, artifactRefs, order = 100) {
  return {
    id,
    kind,
    order,
    payload: { artifact_refs: artifactRefs, schema_version: 1 },
    sourceEntryId: `entry:${id}`,
  };
}

function route(id, path, scope = ["global"]) {
  return {
    id,
    path,
    scope,
    navGroup: "test",
    capability: id,
    requiredPermission: [["authenticated"]],
    localPolicy: "native_equivalent",
    loader: async () => ({ routeId: id }),
  };
}

function readyState(overrides = {}) {
  return {
    error: undefined,
    navigationArtifactIds: [DESKTOP_TENANT_CORE_NAVIGATION_ARTIFACT_ID_V2],
    navigationDiscoveryRouteIds: ["tenant-tenant-overview"],
    navigationRouteIds: ["tenant-tenant-overview"],
    routeArtifactIds: [DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2],
    routeArtifacts: [],
    routeIds: ["tenant-tenant-overview"],
    slotDefinitions: [],
    status: "ready",
    uiSlotArtifactIds: [DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2],
    ...overrides,
  };
}

const appComposition = createDesktopRendererAppCompositionPortV2({
  api: {},
  authRef: { current: { tenants: [] } },
  configRef: { current: {} },
  desktopProductionRouteLocation: { readHash: () => "", subscribe: () => () => {} },
  desktopProductionRouteNavigation: {
    clearHash: () => undefined,
    openPath: () => undefined,
  },
  projectCronJobsRouteBindingRef: { current: null },
  projectSearchRouteBindingProviderV2: {
    publish: () => undefined,
    resolve: () => {
      throw new Error("project_search_route_binding_unpublished");
    },
  },
  setAuth: () => undefined,
  setInvitationSignInRequested: () => undefined,
  setSettingsInitialSection: () => undefined,
  setSettingsWindowOpen: () => undefined,
  settingsRouteCloseNavigationRef: { current: null },
  commitRuntimeConfig: () => undefined,
});

test("conversation resolver requires the exact builtin V2 slot contract", () => {
  const definition = Object.freeze({
    pluginId: "builtin-shell",
    slot: "conversation_surface",
    id: "conversation",
    contract: "ui-builtin:desktop-conversation-surface",
    moduleRef: "builtin:desktop-conversation-surface",
    permission: "ui.conversation",
    sandbox: true,
  });

  assert.equal(
    appComposition.resolveConversationSurface(definition),
    DesktopConversationSurfaceV2,
  );
  for (const invalid of [
    { ...definition, pluginId: "third-party-shell" },
    { ...definition, slot: "conversation_renderer" },
    { ...definition, id: "wrong-conversation" },
    { ...definition, contract: "ui-builtin:wrong-conversation-surface" },
    { ...definition, moduleRef: "builtin:wrong-conversation-surface" },
    { ...definition, permission: "ui.wrong-conversation" },
    { ...definition, sandbox: false },
  ]) {
    assert.equal(appComposition.resolveConversationSurface(invalid), null);
  }
});

test("My Work queue resolver requires the exact builtin V2 slot contract", () => {
  const definition = Object.freeze({
    pluginId: "builtin-shell",
    slot: "my_work_queue_surface",
    id: "my-work-queue",
    contract: "ui-builtin:desktop-my-work-queue-surface",
    moduleRef: "builtin:desktop-my-work-queue-surface",
    permission: "ui.my-work-queue",
    sandbox: true,
  });

  assert.equal(
    appComposition.resolveMyWorkQueueSurface(definition),
    DesktopMyWorkQueueSurfaceV2,
  );
  for (const invalid of [
    { ...definition, pluginId: "third-party-shell" },
    { ...definition, slot: "workbench_surface" },
    { ...definition, id: "wrong-my-work-queue" },
    { ...definition, contract: "ui-builtin:wrong-my-work-queue-surface" },
    { ...definition, moduleRef: "builtin:wrong-my-work-queue-surface" },
    { ...definition, permission: "ui.wrong-my-work-queue" },
    { ...definition, sandbox: false },
  ]) {
    assert.equal(appComposition.resolveMyWorkQueueSurface(invalid), null);
  }
});

test("new-thread composer resolver requires the exact builtin V2 slot contract", () => {
  const definition = Object.freeze({
    pluginId: "builtin-shell",
    slot: "new_thread_composer_surface",
    id: "new-thread-composer",
    contract: "ui-builtin:desktop-new-thread-composer-surface",
    moduleRef: "builtin:desktop-new-thread-composer-surface",
    permission: "ui.new-thread-composer",
    sandbox: true,
  });

  assert.equal(
    appComposition.resolveNewThreadComposerSurface(definition),
    DesktopNewThreadComposerSurfaceV2,
  );
  for (const invalid of [
    { ...definition, pluginId: "third-party-shell" },
    { ...definition, slot: "workbench_surface" },
    { ...definition, id: "wrong-new-thread-composer" },
    { ...definition, contract: "ui-builtin:wrong-new-thread-composer-surface" },
    { ...definition, moduleRef: "builtin:wrong-new-thread-composer-surface" },
    { ...definition, permission: "ui.wrong-new-thread-composer" },
    { ...definition, sandbox: false },
  ]) {
    assert.equal(appComposition.resolveNewThreadComposerSurface(invalid), null);
  }
});

test("session workspace resolver requires the exact builtin V2 slot contract", () => {
  const definition = Object.freeze({
    pluginId: "builtin-shell",
    slot: "session_workspace_surface",
    id: "session-workspace",
    contract: "ui-builtin:desktop-session-workspace-surface",
    moduleRef: "builtin:desktop-session-workspace-surface",
    permission: "ui.session-workspace",
    sandbox: true,
  });

  assert.equal(
    appComposition.resolveSessionWorkspaceSurface(definition),
    DesktopSessionWorkspaceSurfaceV2,
  );
  for (const invalid of [
    { ...definition, pluginId: "third-party-shell" },
    { ...definition, slot: "workbench_surface" },
    { ...definition, id: "wrong-session-workspace" },
    { ...definition, contract: "ui-builtin:wrong-session-workspace-surface" },
    { ...definition, moduleRef: "builtin:wrong-session-workspace-surface" },
    { ...definition, permission: "ui.wrong-session-workspace" },
    { ...definition, sandbox: false },
  ]) {
    assert.equal(appComposition.resolveSessionWorkspaceSurface(invalid), null);
  }
});

test("workspace collaboration resolver requires the exact builtin V2 slot contract", () => {
  const definition = Object.freeze({
    pluginId: "builtin-shell",
    slot: "workspace_collaboration_surface",
    id: "workspace-collaboration",
    contract: "ui-builtin:desktop-workspace-collaboration-surface",
    moduleRef: "builtin:desktop-workspace-collaboration-surface",
    permission: "ui.workspace-collaboration",
    sandbox: true,
  });

  assert.equal(
    appComposition.resolveWorkspaceCollaborationSurface(definition),
    DesktopWorkspaceCollaborationSurfaceV2,
  );
  for (const invalid of [
    { ...definition, pluginId: "third-party-shell" },
    { ...definition, slot: "workbench_surface" },
    { ...definition, id: "wrong-workspace-collaboration" },
    {
      ...definition,
      contract: "ui-builtin:wrong-workspace-collaboration-surface",
    },
    {
      ...definition,
      moduleRef: "builtin:wrong-workspace-collaboration-surface",
    },
    { ...definition, permission: "ui.wrong-workspace-collaboration" },
    { ...definition, sandbox: false },
  ]) {
    assert.equal(appComposition.resolveWorkspaceCollaborationSurface(invalid), null);
  }
});

test("desktop V2 UI-slot artifacts reject runtime signed module references", () => {
  assert.throws(
    () =>
      defineDesktopUiSlotArtifactV2("desktop.ui-slots.signed", [
        {
          pluginId: "third-party-ui",
          slot: "conversation_renderer",
          id: "signed-conversation",
          contract: "ui:signed-conversation",
          moduleRef: `signed:${"a".repeat(64)}`,
          permission: "ui.render",
          sandbox: true,
        },
      ]),
    (error) => error.code === "desktop_renderer_ui_slot_module_ref_invalid",
  );
});

test("desktop catalog resolves explicit route, navigation, and UI-slot artifacts", () => {
  const artifacts = resolveDesktopRendererArtifactsV2([
    contribution("desktop.tenant-creation-routes", "route", [
      DESKTOP_TENANT_CREATION_ROUTE_ARTIFACT_ID_V2,
    ]),
    contribution(
      "desktop.auxiliary-routes",
      "route",
      [DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2],
      110,
    ),
    contribution(
      "desktop.project-knowledge-routes",
      "route",
      [DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2],
      120,
    ),
    contribution(
      "desktop.project-agent-routes",
      "route",
      [DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2],
      130,
    ),
    contribution(
      "desktop.project-administration-routes",
      "route",
      [DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2],
      140,
    ),
    contribution(
      "desktop.runtime-infrastructure-routes",
      "route",
      [DESKTOP_RUNTIME_INFRASTRUCTURE_ROUTE_ARTIFACT_ID_V2],
      150,
    ),
    contribution(
      "desktop.project-workspace-routes",
      "route",
      [DESKTOP_PROJECT_WORKSPACE_ROUTE_ARTIFACT_ID_V2],
      160,
    ),
    contribution(
      "desktop.project-discovery-routes",
      "route",
      [DESKTOP_PROJECT_DISCOVERY_ROUTE_ARTIFACT_ID_V2],
      170,
    ),
    contribution(
      "desktop.tenant-core-routes",
      "route",
      [DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2],
      180,
    ),
    contribution(
      "desktop.tenant-agent-building-routes",
      "route",
      [DESKTOP_TENANT_AGENT_BUILDING_ROUTE_ARTIFACT_ID_V2],
      190,
    ),
    contribution(
      "desktop.tenant-extensions-integrations-routes",
      "route",
      [DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ARTIFACT_ID_V2],
      195,
    ),
    contribution(
      "desktop.tenant-governance-routes",
      "route",
      [DESKTOP_TENANT_GOVERNANCE_ROUTE_ARTIFACT_ID_V2],
      197,
    ),
    contribution(
      "desktop.auxiliary-navigation",
      "navigation",
      [DESKTOP_AUXILIARY_NAVIGATION_ARTIFACT_ID_V2],
      210,
    ),
    contribution(
      "desktop.project-knowledge-navigation",
      "navigation",
      [DESKTOP_PROJECT_KNOWLEDGE_NAVIGATION_ARTIFACT_ID_V2],
      220,
    ),
    contribution(
      "desktop.project-agent-navigation",
      "navigation",
      [DESKTOP_PROJECT_AGENT_NAVIGATION_ARTIFACT_ID_V2],
      230,
    ),
    contribution(
      "desktop.project-administration-navigation",
      "navigation",
      [DESKTOP_PROJECT_ADMINISTRATION_NAVIGATION_ARTIFACT_ID_V2],
      240,
    ),
    contribution(
      "desktop.runtime-infrastructure-navigation",
      "navigation",
      [DESKTOP_RUNTIME_INFRASTRUCTURE_NAVIGATION_ARTIFACT_ID_V2],
      250,
    ),
    contribution(
      "desktop.project-workspace-navigation",
      "navigation",
      [DESKTOP_PROJECT_WORKSPACE_NAVIGATION_ARTIFACT_ID_V2],
      260,
    ),
    contribution(
      "desktop.project-discovery-navigation",
      "navigation",
      [DESKTOP_PROJECT_DISCOVERY_NAVIGATION_ARTIFACT_ID_V2],
      270,
    ),
    contribution(
      "desktop.tenant-core-navigation",
      "navigation",
      [DESKTOP_TENANT_CORE_NAVIGATION_ARTIFACT_ID_V2],
      280,
    ),
    contribution(
      "desktop.tenant-agent-building-navigation",
      "navigation",
      [DESKTOP_TENANT_AGENT_BUILDING_NAVIGATION_ARTIFACT_ID_V2],
      290,
    ),
    contribution(
      "desktop.tenant-extensions-integrations-navigation",
      "navigation",
      [DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_NAVIGATION_ARTIFACT_ID_V2],
      295,
    ),
    contribution(
      "desktop.tenant-governance-navigation",
      "navigation",
      [DESKTOP_TENANT_GOVERNANCE_NAVIGATION_ARTIFACT_ID_V2],
      297,
    ),
    contribution(
      "desktop.authenticated-shell-surface",
      "ui-slot",
      [DESKTOP_AUTHENTICATED_SHELL_SURFACE_ARTIFACT_ID_V2],
      298,
    ),
    contribution(
      "desktop.session-canvas-surface",
      "ui-slot",
      [DESKTOP_SESSION_CANVAS_SURFACE_ARTIFACT_ID_V2],
      299,
    ),
    contribution(
      "desktop.workbench-surface",
      "ui-slot",
      [DESKTOP_WORKBENCH_SURFACE_ARTIFACT_ID_V2],
      300,
    ),
    contribution(
      "desktop.session-workspace-surface",
      "ui-slot",
      [DESKTOP_SESSION_WORKSPACE_SURFACE_ARTIFACT_ID_V2],
      301,
    ),
    contribution(
      "desktop.workspace-collaboration-surface",
      "ui-slot",
      [DESKTOP_WORKSPACE_COLLABORATION_SURFACE_ARTIFACT_ID_V2],
      302,
    ),
    contribution(
      "desktop.new-thread-composer-surface",
      "ui-slot",
      [DESKTOP_NEW_THREAD_COMPOSER_SURFACE_ARTIFACT_ID_V2],
      303,
    ),
    contribution(
      "desktop.my-work-queue-surface",
      "ui-slot",
      [DESKTOP_MY_WORK_QUEUE_SURFACE_ARTIFACT_ID_V2],
      304,
    ),
    contribution(
      "desktop.activity-inbox-surface",
      "ui-slot",
      [DESKTOP_ACTIVITY_INBOX_SURFACE_ARTIFACT_ID_V2],
      305,
    ),
    contribution(
      "desktop.conversation-surface",
      "ui-slot",
      [DESKTOP_CONVERSATION_SURFACE_ARTIFACT_ID_V2],
      306,
    ),
    contribution(
      "desktop.default-ui-slots",
      "ui-slot",
      [DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2],
      307,
    ),
  ]);

  assert.deepEqual(
    artifacts.map(({ id, kind }) => [id, kind]),
    [
      [DESKTOP_TENANT_CREATION_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_RUNTIME_INFRASTRUCTURE_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_PROJECT_WORKSPACE_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_PROJECT_DISCOVERY_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_TENANT_AGENT_BUILDING_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_TENANT_GOVERNANCE_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_AUXILIARY_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_PROJECT_KNOWLEDGE_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_PROJECT_AGENT_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_PROJECT_ADMINISTRATION_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_RUNTIME_INFRASTRUCTURE_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_PROJECT_WORKSPACE_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_PROJECT_DISCOVERY_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_TENANT_CORE_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_TENANT_AGENT_BUILDING_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_TENANT_EXTENSIONS_INTEGRATIONS_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_TENANT_GOVERNANCE_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_AUTHENTICATED_SHELL_SURFACE_ARTIFACT_ID_V2, "ui-slot"],
      [DESKTOP_SESSION_CANVAS_SURFACE_ARTIFACT_ID_V2, "ui-slot"],
      [DESKTOP_WORKBENCH_SURFACE_ARTIFACT_ID_V2, "ui-slot"],
      [DESKTOP_SESSION_WORKSPACE_SURFACE_ARTIFACT_ID_V2, "ui-slot"],
      [DESKTOP_WORKSPACE_COLLABORATION_SURFACE_ARTIFACT_ID_V2, "ui-slot"],
      [DESKTOP_NEW_THREAD_COMPOSER_SURFACE_ARTIFACT_ID_V2, "ui-slot"],
      [DESKTOP_MY_WORK_QUEUE_SURFACE_ARTIFACT_ID_V2, "ui-slot"],
      [DESKTOP_ACTIVITY_INBOX_SURFACE_ARTIFACT_ID_V2, "ui-slot"],
      [DESKTOP_CONVERSATION_SURFACE_ARTIFACT_ID_V2, "ui-slot"],
      [DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2, "ui-slot"],
    ],
  );
  assert.equal(Object.hasOwn(artifacts[0], "createRegistry"), false);
  assert.deepEqual(artifacts[0].routeIds, ["tenant-creation"]);
  assert.equal(artifacts[0].routeIds.includes("backend-stores"), false);
  assert.equal(artifacts[0].routeIds.includes("project-project-team"), false);
  assert.equal(artifacts[0].routeIds.includes("project-agent-dashboard"), false);
  assert.equal(artifacts[0].routeIds.includes("project-project-schema"), false);
  assert.equal(artifacts[0].routeIds.includes("tenant-tenant-pool"), false);
  assert.equal(artifacts[0].routeIds.includes("project-project-overview"), false);
  assert.equal(artifacts[0].routeIds.includes("project-project-channels"), false);
  assert.equal(artifacts[0].routeIds.includes("project-project-search"), false);
  assert.equal(artifacts[0].routeIds.includes("project-project-cron-jobs"), false);
  assert.equal(artifacts[0].routeIds.includes("agent-workspace-tenant-agent-workspace"), false);
  assert.equal(artifacts[0].routeIds.includes("tenant-tenant-overview"), false);
  assert.equal(artifacts[0].routeIds.includes("tenant-tenant-agent-configuration"), false);
  assert.equal(artifacts[0].routeIds.includes("tenant-tenant-plugins"), false);
  assert.equal(artifacts[0].routeIds.includes("tenant-tenant-genes"), false);
  assert.equal(artifacts[0].routeIds.includes("tenant-tenant-users"), false);
  assert.deepEqual(artifacts[1].routeIds, [
    "project-support",
    "backend-stores",
    "project-playbooks",
    "user-profile",
  ]);
  const auxiliaryRegistry = appComposition.createRouteRegistry(artifacts[1].id);
  assert.deepEqual(
    artifacts[1].routeIds.map((routeId) => auxiliaryRegistry.byId.get(routeId).structuralReadiness),
    [
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
    ],
  );
  assert.equal(
    auxiliaryRegistry.byId.get("tenant-tenant-overview").structuralReadiness.status,
    "unavailable",
  );
  assert.deepEqual(artifacts[2].routeIds, [
    "project-project-team",
    "project-project-memories",
    "project-project-entities",
    "project-project-communities",
    "project-project-graph",
  ]);
  const projectKnowledgeRegistry = appComposition.createRouteRegistry(artifacts[2].id);
  assert.deepEqual(
    artifacts[2].routeIds.map(
      (routeId) => projectKnowledgeRegistry.byId.get(routeId).structuralReadiness,
    ),
    [
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
    ],
  );
  assert.deepEqual(artifacts[3].routeIds, [
    "project-agent-dashboard",
    "project-agent-logs",
    "project-agent-patterns",
  ]);
  const projectAgentRegistry = appComposition.createRouteRegistry(artifacts[3].id);
  assert.deepEqual(
    artifacts[3].routeIds.map(
      (routeId) => projectAgentRegistry.byId.get(routeId).structuralReadiness,
    ),
    [{ status: "ready" }, { status: "ready" }, { status: "ready" }],
  );
  assert.deepEqual(artifacts[4].routeIds, [
    "project-project-schema",
    "project-project-channels",
    "project-project-maintenance",
    "project-project-cron-jobs",
    "project-project-settings",
  ]);
  const projectAdministrationRegistry = appComposition.createRouteRegistry(artifacts[4].id);
  assert.deepEqual(
    artifacts[4].routeIds.map(
      (routeId) => projectAdministrationRegistry.byId.get(routeId).structuralReadiness,
    ),
    [
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
    ],
  );
  assert.deepEqual(artifacts[5].routeIds, [
    "tenant-tenant-runtimes",
    "tenant-tenant-pool",
    "tenant-tenant-instances",
    "tenant-tenant-clusters",
    "tenant-tenant-deploy",
    "tenant-tenant-instance-templates",
    "tenant-tenant-genes",
  ]);
  const runtimeInfrastructureRegistry = appComposition.createRouteRegistry(artifacts[5].id);
  assert.deepEqual(
    artifacts[5].routeIds.map(
      (routeId) => runtimeInfrastructureRegistry.byId.get(routeId).structuralReadiness,
    ),
    [
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
    ],
  );
  assert.deepEqual(artifacts[6].routeIds, [
    "project-project-overview",
    "project-project-workspaces",
    "project-blackboard-dynamic-project-blackboard",
  ]);
  const projectWorkspaceRegistry = appComposition.createRouteRegistry(artifacts[6].id);
  assert.deepEqual(
    artifacts[6].routeIds.map(
      (routeId) => projectWorkspaceRegistry.byId.get(routeId).structuralReadiness,
    ),
    [{ status: "ready" }, { status: "ready" }, { status: "ready" }],
  );
  assert.deepEqual(artifacts[7].routeIds, ["project-project-search"]);
  const projectDiscoveryRegistry = appComposition.createRouteRegistry(artifacts[7].id);
  assert.equal(
    projectDiscoveryRegistry.byId.get("project-project-search").structuralReadiness.status,
    "ready",
  );
  assert.deepEqual(artifacts[8].routeIds, [
    "agent-workspace-tenant-agent-workspace",
    "tenant-tenant-overview",
    "tenant-tenant-projects",
    "tenant-tenant-workspaces",
    "tenant-tenant-tasks",
    "tenant-tenant-analytics",
  ]);
  const tenantCoreRegistry = appComposition.createRouteRegistry(artifacts[8].id);
  assert.deepEqual(
    artifacts[8].routeIds.map((routeId) => tenantCoreRegistry.byId.get(routeId).structuralReadiness),
    [
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
    ],
  );
  assert.deepEqual(artifacts[9].routeIds, [
    "tenant-tenant-agent-configuration",
    "tenant-tenant-agent-definitions",
    "tenant-tenant-agent-bindings",
    "tenant-tenant-skills",
    "tenant-tenant-evolution",
    "tenant-tenant-patterns",
  ]);
  const tenantAgentBuildingRegistry = appComposition.createRouteRegistry(artifacts[9].id);
  assert.deepEqual(
    artifacts[9].routeIds.map(
      (routeId) => tenantAgentBuildingRegistry.byId.get(routeId).structuralReadiness,
    ),
    [
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
    ],
  );
  assert.deepEqual(artifacts[10].routeIds, [
    "tenant-tenant-plugins",
    "tenant-tenant-mcp-servers",
    "tenant-tenant-acp",
    "tenant-tenant-templates",
    "tenant-tenant-providers",
    "tenant-tenant-webhooks",
  ]);
  const tenantExtensionsIntegrationsRegistry = appComposition.createRouteRegistry(
    artifacts[10].id,
  );
  assert.deepEqual(
    artifacts[10].routeIds.map(
      (routeId) => tenantExtensionsIntegrationsRegistry.byId.get(routeId).structuralReadiness,
    ),
    [
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
    ],
  );
  assert.deepEqual(artifacts[11].routeIds, [
    "tenant-tenant-users",
    "tenant-tenant-audit-logs",
    "tenant-tenant-events",
    "tenant-tenant-dead-letter-queue",
    "tenant-tenant-trust-policies",
    "tenant-tenant-decision-records",
    "tenant-tenant-billing",
    "tenant-tenant-org-settings",
    "tenant-tenant-settings",
  ]);
  const tenantGovernanceRegistry = appComposition.createRouteRegistry(artifacts[11].id);
  assert.deepEqual(
    artifacts[11].routeIds.map(
      (routeId) => tenantGovernanceRegistry.byId.get(routeId).structuralReadiness,
    ),
    [
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
      { status: "ready" },
    ],
  );
  assert.deepEqual(artifacts[12].discoveryRouteIds, [
    "backend-stores",
    "project-playbooks",
    "project-support",
  ]);
  assert.deepEqual(artifacts[13].discoveryRouteIds, [
    "project-project-team",
    "project-project-memories",
    "project-project-entities",
    "project-project-communities",
    "project-project-graph",
  ]);
  assert.deepEqual(artifacts[14].discoveryRouteIds, [
    "project-agent-dashboard",
    "project-agent-logs",
    "project-agent-patterns",
  ]);
  assert.deepEqual(artifacts[15].discoveryRouteIds, [
    "project-project-schema",
    "project-project-channels",
    "project-project-maintenance",
    "project-project-cron-jobs",
    "project-project-settings",
  ]);
  assert.deepEqual(artifacts[16].discoveryRouteIds, [
    "tenant-tenant-runtimes",
    "tenant-tenant-pool",
    "tenant-tenant-instances",
    "tenant-tenant-clusters",
    "tenant-tenant-deploy",
    "tenant-tenant-instance-templates",
    "tenant-tenant-genes",
  ]);
  assert.deepEqual(artifacts[17].discoveryRouteIds, [
    "project-project-overview",
    "project-project-workspaces",
    "project-blackboard-dynamic-project-blackboard",
  ]);
  assert.deepEqual(artifacts[18].discoveryRouteIds, ["project-project-search"]);
  assert.deepEqual(artifacts[19].discoveryRouteIds, [
    "agent-workspace-tenant-agent-workspace",
    "tenant-tenant-overview",
    "tenant-tenant-projects",
    "tenant-tenant-workspaces",
    "tenant-tenant-tasks",
    "tenant-tenant-analytics",
  ]);
  assert.deepEqual(artifacts[20].discoveryRouteIds, [
    "tenant-tenant-agent-configuration",
    "tenant-tenant-agent-definitions",
    "tenant-tenant-agent-bindings",
    "tenant-tenant-skills",
    "tenant-tenant-evolution",
    "tenant-tenant-patterns",
  ]);
  assert.deepEqual(artifacts[21].discoveryRouteIds, [
    "tenant-tenant-plugins",
    "tenant-tenant-mcp-servers",
    "tenant-tenant-acp",
    "tenant-tenant-templates",
    "tenant-tenant-providers",
    "tenant-tenant-webhooks",
  ]);
  assert.deepEqual(artifacts[22].discoveryRouteIds, [
    "tenant-tenant-users",
    "tenant-tenant-audit-logs",
    "tenant-tenant-events",
    "tenant-tenant-dead-letter-queue",
    "tenant-tenant-trust-policies",
    "tenant-tenant-decision-records",
    "tenant-tenant-billing",
    "tenant-tenant-org-settings",
    "tenant-tenant-settings",
  ]);
  assert.deepEqual(artifacts[23].slotDefinitions, [
    {
      pluginId: "builtin-shell",
      slot: "authenticated_shell_surface",
      id: "authenticated-shell",
      contract: "ui-builtin:desktop-authenticated-shell-surface",
      moduleRef: "builtin:desktop-authenticated-shell-surface",
      permission: "ui.authenticated-shell",
      sandbox: true,
    },
  ]);
  assert.deepEqual(artifacts[24].slotDefinitions, [
    {
      pluginId: "builtin-shell",
      slot: "session_canvas_surface",
      id: "session-canvas",
      contract: "ui-builtin:desktop-session-canvas-surface",
      moduleRef: "builtin:desktop-session-canvas-surface",
      permission: "ui.session-canvas",
      sandbox: true,
    },
  ]);
  assert.deepEqual(artifacts[25].slotDefinitions, [
    {
      pluginId: "builtin-shell",
      slot: "workbench_surface",
      id: "workbench",
      contract: "ui-builtin:desktop-workbench-surface",
      moduleRef: "builtin:desktop-workbench-surface",
      permission: "ui.workbench",
      sandbox: true,
    },
  ]);
  assert.deepEqual(artifacts[26].slotDefinitions, [
    {
      pluginId: "builtin-shell",
      slot: "session_workspace_surface",
      id: "session-workspace",
      contract: "ui-builtin:desktop-session-workspace-surface",
      moduleRef: "builtin:desktop-session-workspace-surface",
      permission: "ui.session-workspace",
      sandbox: true,
    },
  ]);
  assert.deepEqual(artifacts[27].slotDefinitions, [
    {
      pluginId: "builtin-shell",
      slot: "workspace_collaboration_surface",
      id: "workspace-collaboration",
      contract: "ui-builtin:desktop-workspace-collaboration-surface",
      moduleRef: "builtin:desktop-workspace-collaboration-surface",
      permission: "ui.workspace-collaboration",
      sandbox: true,
    },
  ]);
  assert.deepEqual(artifacts[28].slotDefinitions, [
    {
      pluginId: "builtin-shell",
      slot: "new_thread_composer_surface",
      id: "new-thread-composer",
      contract: "ui-builtin:desktop-new-thread-composer-surface",
      moduleRef: "builtin:desktop-new-thread-composer-surface",
      permission: "ui.new-thread-composer",
      sandbox: true,
    },
  ]);
  assert.deepEqual(artifacts[29].slotDefinitions, [
    {
      pluginId: "builtin-shell",
      slot: "my_work_queue_surface",
      id: "my-work-queue",
      contract: "ui-builtin:desktop-my-work-queue-surface",
      moduleRef: "builtin:desktop-my-work-queue-surface",
      permission: "ui.my-work-queue",
      sandbox: true,
    },
  ]);
  assert.deepEqual(artifacts[30].slotDefinitions, [
    {
      pluginId: "builtin-shell",
      slot: "activity_inbox_surface",
      id: "activity-inbox",
      contract: "ui-builtin:desktop-activity-inbox-surface",
      moduleRef: "builtin:desktop-activity-inbox-surface",
      permission: "ui.activity-inbox",
      sandbox: true,
    },
  ]);
  assert.deepEqual(artifacts[31].slotDefinitions, [
    {
      pluginId: "builtin-shell",
      slot: "conversation_surface",
      id: "conversation",
      contract: "ui-builtin:desktop-conversation-surface",
      moduleRef: "builtin:desktop-conversation-surface",
      permission: "ui.conversation",
      sandbox: true,
    },
  ]);
  assert.equal(artifacts[32].slotDefinitions.length, 1);
  assert.ok(
    artifacts[32].slotDefinitions.every(({ moduleRef }) =>
      moduleRef.startsWith("builtin:"),
    ),
  );
});

test("desktop catalog rejects unknown, mismatched, and duplicate artifact ownership", () => {
  assert.throws(
    () =>
      resolveDesktopRendererArtifactsV2([
        contribution("unknown", "route", ["missing"]),
      ]),
    (error) => error.code === "desktop_renderer_artifact_unknown",
  );
  assert.throws(
    () =>
      resolveDesktopRendererArtifactsV2([
        contribution("wrong-kind", "navigation", [
          DESKTOP_TENANT_CREATION_ROUTE_ARTIFACT_ID_V2,
        ]),
      ]),
    (error) => error.code === "desktop_renderer_artifact_kind_mismatch",
  );
  assert.throws(
    () =>
      resolveDesktopRendererArtifactsV2([
        contribution("slots-a", "ui-slot", [
          DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
        ]),
        contribution(
          "slots-b",
          "ui-slot",
          [DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2],
          200,
        ),
      ]),
    (error) => error.code === "desktop_renderer_ui_slot_artifact_conflict",
  );
});

test("route projection always retains only the authentication kernel without V2 business routes", () => {
  let artifactRegistryCalls = 0;
  const candidate = createDesktopRouteRegistry([
    route("device-approval", "/device"),
    route("invitation-acceptance", "/invite"),
    route("tenant-tenant-overview", "/tenant/:tenantId", ["tenant"]),
  ]);
  const routeArtifact = {
    id: DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2,
    kind: "route",
    routeIds: ["tenant-tenant-overview"],
  };
  const composition = Object.freeze({
    createAuthenticationRouteRegistry: () => candidate,
    createRouteRegistry: (artifactId) => {
      assert.equal(artifactId, DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2);
      artifactRegistryCalls += 1;
      return candidate;
    },
    resolveWorkbenchSurface: () => null,
  });
  const disabled = projectDesktopRouteRegistryV2(
    composition,
    {
      ...readyState(),
      routeArtifactIds: [],
      routeArtifacts: [routeArtifact],
      routeIds: [],
      status: "disabled",
    },
  );
  assert.deepEqual(
    disabled.definitions.map(({ id }) => id),
    ["device-approval", "invitation-acceptance"],
  );
  assert.equal(artifactRegistryCalls, 0);

  const active = projectDesktopRouteRegistryV2(
    composition,
    readyState({ routeArtifacts: [routeArtifact] }),
  );
  assert.deepEqual(
    active.definitions.map(({ id }) => id),
    ["device-approval", "invitation-acceptance", "tenant-tenant-overview"],
  );
  assert.equal(artifactRegistryCalls, 1);
});

test("disabled project discovery contributions expose neither search route nor navigation", () => {
  const state = readyState({
    navigationArtifactIds: [],
    navigationDiscoveryRouteIds: [],
    navigationRouteIds: [],
    routeArtifactIds: [],
    routeArtifacts: [],
    routeIds: [],
  });
  const routes = projectDesktopRouteRegistryV2(appComposition, state);
  const navigation = projectDesktopNavigationRegistryV2(routes, state);

  assert.equal(routes.byId.has("project-project-search"), false);
  assert.equal(navigation.byId.has("project-project-search"), false);
  assert.equal(isDesktopNavigationRouteEnabledV2(state, "project-project-search"), false);
});

test("navigation and UI-slot selectors expose only active V2 contributions", () => {
  const routes = createDesktopRouteRegistry([
    route("device-approval", "/device"),
    route("tenant-tenant-overview", "/tenant/:tenantId", ["tenant"]),
  ]);
  const state = readyState({
    slotDefinitions: [
      {
        pluginId: "builtin-ui",
        slot: "settings_page",
        id: "plugin-settings",
        contract: "ui-builtin:plugin-settings",
        moduleRef: "builtin:plugin-settings",
        permission: "ui.settings.plugins",
        sandbox: true,
      },
    ],
  });
  const navigation = projectDesktopNavigationRegistryV2(routes, state);

  assert.deepEqual(
    navigation.definitions.map(({ id }) => id),
    ["tenant-tenant-overview"],
  );
  assert.equal(
    isDesktopNavigationRouteEnabledV2(state, "tenant-tenant-overview"),
    true,
  );
  assert.equal(
    isDesktopNavigationRouteEnabledV2(state, "device-approval"),
    false,
  );
  assert.equal(selectDesktopUiSlotsV2(state, "settings_page").length, 1);
  assert.deepEqual(
    selectDesktopUiSlotsV2({ ...state, status: "loading" }, "settings_page"),
    [],
  );
});
