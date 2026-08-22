import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
require.extensions[".css"] = () => {};

const {
  DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2,
  DESKTOP_DEFAULT_ROUTE_ARTIFACT_ID_V2,
  DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2,
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
      "desktop.default-navigation",
      "navigation",
      [DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2],
      200,
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
      [DESKTOP_DEFAULT_NAVIGATION_ARTIFACT_ID_V2, "navigation"],
      [DESKTOP_DEFAULT_UI_SLOT_ARTIFACT_ID_V2, "ui-slot"],
    ],
  );
  assert.equal(typeof artifacts[0].createRegistry, "function");
  assert.equal(artifacts[2].slotDefinitions.length, 2);
  assert.ok(
    artifacts[2].slotDefinitions.every(({ moduleRef }) =>
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
