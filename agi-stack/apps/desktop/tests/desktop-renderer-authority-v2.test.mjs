import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
require.extensions[".css"] = () => {};

const {
  DESKTOP_AUXILIARY_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_AGENT_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_ADMINISTRATION_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_KNOWLEDGE_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2,
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
    navigationArtifactIds: [DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2],
    navigationDiscoveryRouteIds: ["tenant-tenant-overview"],
    navigationRouteIds: ["tenant-tenant-overview"],
    routeArtifactIds: [DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2],
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
    contribution("desktop.production-routes", "route", [
      DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2,
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
      "desktop.default-navigation",
      "navigation",
      [DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2],
      200,
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
      "desktop.default-ui-slots",
      "ui-slot",
      [DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2],
      300,
    ),
  ]);

  assert.deepEqual(
    artifacts.map(({ id, kind }) => [id, kind]),
    [
      [DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_AUXILIARY_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_PROJECT_KNOWLEDGE_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_PROJECT_AGENT_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_PROJECT_ADMINISTRATION_ROUTE_ARTIFACT_ID_V2, "route"],
      [DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_AUXILIARY_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_PROJECT_KNOWLEDGE_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_PROJECT_AGENT_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_PROJECT_ADMINISTRATION_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2, "ui-slot"],
    ],
  );
  assert.equal(typeof artifacts[0].createRegistry, "function");
  assert.equal(artifacts[0].routeIds.includes("backend-stores"), false);
  assert.equal(artifacts[0].routeIds.includes("project-project-team"), false);
  assert.equal(artifacts[0].routeIds.includes("project-agent-dashboard"), false);
  assert.equal(artifacts[0].routeIds.includes("project-project-schema"), false);
  assert.deepEqual(artifacts[1].routeIds, [
    "project-support",
    "backend-stores",
    "project-playbooks",
  ]);
  const auxiliaryRegistry = artifacts[1].createRegistry({ configRef: { current: {} } });
  assert.deepEqual(
    artifacts[1].routeIds.map((routeId) => auxiliaryRegistry.byId.get(routeId).structuralReadiness),
    [{ status: "ready" }, { status: "ready" }, { status: "ready" }],
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
    "project-project-maintenance",
    "project-project-settings",
  ]);
  const projectAdministrationRegistry = artifacts[4].createRegistry({
    configRef: { current: {} },
  });
  assert.deepEqual(
    artifacts[4].routeIds.map(
      (routeId) => projectAdministrationRegistry.byId.get(routeId).structuralReadiness,
    ),
    [{ status: "ready" }, { status: "ready" }, { status: "ready" }],
  );
  assert.equal(artifacts[5].discoveryRouteIds.includes("backend-stores"), false);
  assert.equal(artifacts[5].discoveryRouteIds.includes("project-project-team"), false);
  assert.equal(artifacts[5].discoveryRouteIds.includes("project-agent-dashboard"), false);
  assert.equal(artifacts[5].discoveryRouteIds.includes("project-project-schema"), false);
  assert.deepEqual(artifacts[6].discoveryRouteIds, [
    "backend-stores",
    "project-playbooks",
    "project-support",
  ]);
  assert.deepEqual(artifacts[7].discoveryRouteIds, [
    "project-project-team",
    "project-project-memories",
    "project-project-entities",
    "project-project-communities",
    "project-project-graph",
  ]);
  assert.deepEqual(artifacts[8].discoveryRouteIds, [
    "project-agent-dashboard",
    "project-agent-logs",
    "project-agent-patterns",
  ]);
  assert.deepEqual(artifacts[9].discoveryRouteIds, [
    "project-project-schema",
    "project-project-maintenance",
    "project-project-settings",
  ]);
  assert.equal(artifacts[10].slotDefinitions.length, 2);
  assert.ok(
    artifacts[10].slotDefinitions.every(({ moduleRef }) =>
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
          DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2,
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
    id: DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2,
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
