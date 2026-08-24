import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
require.extensions[".css"] = () => {};

const {
  DESKTOP_AUXILIARY_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
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
  resolveDesktopRendererArtifactsV2,
} = require("/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererArtifactCatalogV2.js");
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
      "desktop.default-ui-slots",
      "ui-slot",
      [DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2],
      300,
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
      [DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2, "ui-slot"],
    ],
  );
  assert.equal(typeof artifacts[0].createRegistry, "function");
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
  const auxiliaryRegistry = artifacts[1].createRegistry({
    configRef: { current: {} },
    setAuth: () => undefined,
  });
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
  const projectKnowledgeRegistry = artifacts[2].createRegistry({
    configRef: { current: {} },
  });
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
  const projectAgentRegistry = artifacts[3].createRegistry({ configRef: { current: {} } });
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
  const projectAdministrationRegistry = artifacts[4].createRegistry({
    configRef: { current: {} },
    projectCronJobsRouteBindingRef: { current: null },
  });
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
  const runtimeInfrastructureRegistry = artifacts[5].createRegistry({
    configRef: { current: {} },
  });
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
  const projectWorkspaceRegistry = artifacts[6].createRegistry({
    configRef: { current: {} },
    desktopProductionRouteNavigation: {
      clearHash: () => undefined,
      openPath: () => undefined,
    },
  });
  assert.deepEqual(
    artifacts[6].routeIds.map(
      (routeId) => projectWorkspaceRegistry.byId.get(routeId).structuralReadiness,
    ),
    [{ status: "ready" }, { status: "ready" }, { status: "ready" }],
  );
  assert.deepEqual(artifacts[7].routeIds, ["project-project-search"]);
  const projectDiscoveryRegistry = artifacts[7].createRegistry({
    configRef: { current: {} },
    projectSearchRouteBindingRef: { current: null },
  });
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
  const tenantCoreRegistry = artifacts[8].createRegistry({
    authRef: { current: { tenants: [] } },
    configRef: { current: {} },
  });
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
  const tenantAgentBuildingRegistry = artifacts[9].createRegistry({
    configRef: { current: {} },
    desktopProductionRouteNavigation: {
      clearHash: () => undefined,
      openPath: () => undefined,
    },
    setSettingsInitialSection: () => undefined,
    setSettingsWindowOpen: () => undefined,
    settingsRouteCloseNavigationRef: { current: null },
  });
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
  const tenantExtensionsIntegrationsRegistry = artifacts[10].createRegistry({
    configRef: { current: {} },
    desktopProductionRouteNavigation: {
      clearHash: () => undefined,
      openPath: () => undefined,
    },
    setSettingsInitialSection: () => undefined,
    setSettingsWindowOpen: () => undefined,
    settingsRouteCloseNavigationRef: { current: null },
  });
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
  const tenantGovernanceRegistry = artifacts[11].createRegistry({
    configRef: { current: {} },
    desktopProductionRouteLocation: { readHash: () => "" },
  });
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
  assert.equal(artifacts[23].slotDefinitions.length, 2);
  assert.ok(
    artifacts[23].slotDefinitions.every(({ moduleRef }) =>
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
    createRegistry: () => {
      artifactRegistryCalls += 1;
      return candidate;
    },
    id: DESKTOP_TENANT_CORE_ROUTE_ARTIFACT_ID_V2,
    kind: "route",
    routeIds: ["tenant-tenant-overview"],
  };
  const kernelFactory = () => candidate;
  const disabled = projectDesktopRouteRegistryV2(
    {},
    {
      ...readyState(),
      routeArtifactIds: [],
      routeArtifacts: [routeArtifact],
      routeIds: [],
      status: "disabled",
    },
    kernelFactory,
  );
  assert.deepEqual(
    disabled.definitions.map(({ id }) => id),
    ["device-approval", "invitation-acceptance"],
  );
  assert.equal(artifactRegistryCalls, 0);

  const active = projectDesktopRouteRegistryV2(
    {},
    readyState({ routeArtifacts: [routeArtifact] }),
    kernelFactory,
  );
  assert.deepEqual(
    active.definitions.map(({ id }) => id),
    ["device-approval", "invitation-acceptance", "tenant-tenant-overview"],
  );
  assert.equal(artifactRegistryCalls, 1);
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
