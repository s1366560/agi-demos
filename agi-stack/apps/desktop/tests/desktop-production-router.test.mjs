import assert from "node:assert/strict";
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const compiledNavigationDirectory =
  "/tmp/agistack-desktop-test-dist/src/features/navigation";
mkdirSync(compiledNavigationDirectory, { recursive: true });
copyFileSync(
  new URL(
    "../src/features/navigation/DesktopProductionRouter.css",
    import.meta.url,
  ),
  `${compiledNavigationDirectory}/DesktopProductionRouter.css`,
);
require.extensions[".css"] = () => {};

const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const { I18nProvider } = require("/tmp/agistack-desktop-test-dist/src/i18n.js");
const {
  DesktopProductionRouter,
  DesktopProductionRouterView,
  handleDesktopProductionRouteBoundaryEscape,
  retryDesktopProductionRoute,
  returnToDesktopWorkbench,
  shouldPassThroughAuthenticationBoundary,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/DesktopProductionRouter.js");
const {
  createDesktopRouteRegistry,
} = require("/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js");

const source = readFileSync(
  new URL(
    "../src/features/navigation/DesktopProductionRouter.tsx",
    import.meta.url,
  ),
  "utf8",
);
const stylesheet = readFileSync(
  new URL(
    "../src/features/navigation/DesktopProductionRouter.css",
    import.meta.url,
  ),
  "utf8",
);
const messages = readFileSync(
  new URL(
    "../src/features/navigation/locales/desktopProductionRouterMessages.ts",
    import.meta.url,
  ),
  "utf8",
);
const globalStylesheet = readFileSync(
  new URL("../src/styles/tokens.css", import.meta.url),
  "utf8",
);

const routeContext = Object.freeze({
  tenantId: "tenant-1",
  projectId: "project-1",
});
const module = Object.freeze({
  routeId: "project-project-overview",
  capability: "project-project-overview",
  localPolicy: "native_equivalent",
  disposition: "implemented",
  availability: "available",
  reasonCode: null,
  Surface({ module: routeModule, context }) {
    return React.createElement("output", {
      "data-surface-route": routeModule.routeId,
      "data-surface-tenant": context.tenantId,
      "data-surface-project": context.projectId,
    });
  },
});
const registry = createDesktopRouteRegistry([
  {
    id: "project-project-overview",
    path: "/tenant/:tenantId/project/:projectId",
    scope: ["tenant", "project"],
    navGroup: "project-workspace",
    capability: "project-project-overview",
    requiredPermission: [["authenticated", "project_member"]],
    localPolicy: "native_equivalent",
    loader: async () => module,
  },
]);
const match = Object.freeze({
  definition: registry.definitions[0],
  context: routeContext,
  canonicalPath: "/tenant/tenant-1/project/project-1",
});
const capability = Object.freeze({
  availability: "available",
  reason_code: null,
  service_version: "3.0.0",
  contract_version: "3.0.0",
  allowed_actions: ["view"],
  scope: {
    tenant_id: "tenant-1",
    project_id: "project-1",
    workspace_id: null,
    instance_id: null,
  },
  authority_revision: 4,
});

test("production router delegates to the React host and keeps legacy children mounted", () => {
  const location = hashLocation("");
  const markup = render(
    React.createElement(
      DesktopProductionRouter,
      {
        registry,
        location: location.port,
        mode: "cloud",
        permissions: new Set(["authenticated", "project_member"]),
        resolveCapability: () => capability,
        switchScope: async () => {},
        navigation: { clearHash() {} },
      },
      React.createElement(
        "article",
        { "data-legacy": true },
        "Legacy workbench",
      ),
    ),
  );

  assert.match(markup, /data-legacy="true"/u);
  assert.match(markup, /Legacy workbench/u);
  assert.doesNotMatch(markup, /desktop-production-route-stage/u);
  assert.match(source, /useDesktopHashRouteHost\(/u);
  assert.match(source, /const hostOptions = useMemo</u);
  assert.doesNotMatch(source, /useState|features\/session|stores\//u);
});

test("ready and degraded states render the exact module Surface and route context", () => {
  for (const status of ["ready", "degraded"]) {
    const markup = renderView({
      state: {
        status,
        match,
        capability: {
          ...capability,
          availability: status === "degraded" ? "degraded" : "available",
          reason_code:
            status === "degraded" ? "project_overview_read_only" : null,
        },
        module,
      },
    });

    assert.match(
      markup,
      /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u,
    );
    assert.match(markup, /data-legacy="true"/u);
    assert.match(markup, new RegExp(`data-route-state="${status}"`, "u"));
    assert.match(markup, /data-surface-route="project-project-overview"/u);
    assert.match(markup, /data-surface-tenant="tenant-1"/u);
    assert.match(markup, /data-surface-project="project-1"/u);
    assert.match(markup, /aria-label="Route breadcrumb"/u);
    assert.match(markup, /Return to workbench/u);
  }
});

test("a route_content module moves legacy content into one production route surface", () => {
  const contentModule = Object.freeze({
    ...module,
    contentPolicy: "route_content",
    Surface({ content }) {
      return React.createElement(
        "section",
        { "data-route-content-owner": true },
        content,
      );
    },
  });
  const markup = renderView({
    state: {
      status: "ready",
      match,
      capability,
      module: contentModule,
    },
  });

  assert.equal((markup.match(/data-legacy="true"/gu) ?? []).length, 1);
  assert.match(markup, /data-route-content-owner="true"/u);
  assert.match(markup, /desktop-production-route-stage/u);
});

test("only an empty hash retains legacy while every rejected deep link uses native recovery", () => {
  const emptyMarkup = renderView({
    state: {
      status: "malformed",
      location: "",
      reasonCode: "desktop_route_malformed",
    },
  });
  assert.match(emptyMarkup, /data-legacy="true"/u);
  assert.doesNotMatch(emptyMarkup, /desktop-production-route-stage/u);

  for (const [state, expected] of [
    [
      {
        status: "malformed",
        location: "#/tenant/%E0%A4%A/project/project-1",
        reasonCode: "desktop_route_malformed",
      },
      "Route could not be restored",
    ],
    [
      {
        status: "not_found",
        location: "#/unknown?token=untrusted",
        reasonCode: "desktop_route_not_found",
      },
      "Native route not found",
    ],
  ]) {
    const markup = renderView({ state });
    assert.match(
      markup,
      /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u,
    );
    assert.match(markup, /data-legacy="true"/u);
    assert.match(markup, new RegExp(expected, "u"));
    assert.match(
      markup,
      new RegExp(`data-reason-code="${state.reasonCode}"`, "u"),
    );
    assert.doesNotMatch(
      markup,
      new RegExp(`<code>${state.reasonCode}</code>`, "u"),
    );
    assert.match(markup, /data-action="return-workbench"[^>]*autofocus=""/u);
    assert.doesNotMatch(markup, /unknown\?token=untrusted/u);
  }
});

test("loading, forbidden, unavailable, and error states expose structured boundaries", () => {
  const cases = [
    [
      {
        status: "loading",
        match,
        capability,
        attempt: 2,
      },
      ["Loading native route", "project-project-overview"],
    ],
    [
      {
        status: "forbidden",
        match,
        reasonCode: "desktop_route_permission_denied",
        missingPermissions: ["project_member"],
      },
      [
        "Permission required",
        "Your current role does not have access to this route.",
        "project_member",
      ],
    ],
    [
      {
        status: "unavailable",
        match,
        reasonCode: "project_overview_authority_unavailable",
        capability: null,
      },
      [
        "Native route unavailable",
        "The required service or authority is currently unavailable.",
        "Retry",
      ],
    ],
    [
      {
        status: "error",
        match,
        reasonCode: "desktop_route_module_load_failed",
        retryable: true,
      },
      [
        "Native route failed",
        "Desktop could not load this route. Retry when the action is available.",
        "Retry",
      ],
    ],
  ];

  for (const [state, expectedValues] of cases) {
    const markup = renderView({ state });
    for (const expected of expectedValues) {
      assert.match(markup, new RegExp(expected, "u"));
    }
  }
});

test("local cloud-only boundaries keep protocol codes non-visible and explain the recovery", () => {
  const markup = renderView({
    state: {
      status: "unavailable",
      match,
      reasonCode: "desktop_route_local_cloud_only",
      capability: null,
    },
  });

  assert.match(
    markup,
    /data-reason-code="desktop_route_local_cloud_only"/u,
  );
  assert.match(
    markup,
    /This feature requires the tenant cloud service. Switch to the Cloud workspace and retry./u,
  );
  assert.doesNotMatch(
    markup,
    /<code>desktop_route_local_cloud_only<\/code>/u,
  );
});

test("authentication-required route can preserve its deep link behind the login surface", () => {
  const deviceMatch = {
    definition: {
      ...match.definition,
      id: "device-approval",
      path: "/device",
      scope: ["global"],
      capability: "device-approval",
      requiredPermission: [["authenticated"]],
      localPolicy: "cloud_only",
    },
    context: {},
    canonicalPath: "/device",
  };
  const state = {
    status: "forbidden",
    match: deviceMatch,
    reasonCode: "desktop_route_permission_denied",
    missingPermissions: ["authenticated"],
  };
  assert.equal(
    shouldPassThroughAuthenticationBoundary(
      state,
      new Set(["device-approval"]),
    ),
    true,
  );
  assert.equal(
    shouldPassThroughAuthenticationBoundary(state, new Set()),
    false,
  );
  const markup = renderView({
    state,
    authenticationPassthroughRouteIds: new Set(["device-approval"]),
  });
  assert.match(markup, /data-legacy="true"/u);
  assert.doesNotMatch(markup, /desktop-production-route-stage/u);
});

test("an explicit legacy-child handoff hides a ready native route without clearing its hash", () => {
  const markup = renderView({
    state: {
      status: "ready",
      match,
      capability,
      module,
    },
    forceLegacyChildren: true,
  });

  assert.match(markup, /data-legacy="true"/u);
  assert.doesNotMatch(markup, /desktop-production-route-stage/u);
  assert.doesNotMatch(
    markup,
    /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u,
  );
});

test("a route-scoped legacy passthrough waits for capability and scope authority", () => {
  const legacyPassthroughRouteIds = new Set(["project-project-overview"]);
  for (const status of ["ready", "degraded"]) {
    const markup = renderView({
      state: {
        status,
        match,
        capability: {
          ...capability,
          availability: status === "degraded" ? "degraded" : "available",
          reason_code:
            status === "degraded" ? "workspace_projection_partial" : null,
        },
        module,
      },
      legacyPassthroughRouteIds,
    });
    assert.match(markup, /data-legacy="true"/u);
    assert.doesNotMatch(markup, /desktop-production-route-stage/u);
    assert.doesNotMatch(
      markup,
      /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u,
    );
  }

  for (const state of [
    { status: "loading", match, capability, attempt: 1 },
    {
      status: "forbidden",
      match,
      reasonCode: "desktop_route_permission_denied",
      missingPermissions: ["project_member"],
    },
    {
      status: "unavailable",
      match,
      reasonCode: "desktop_route_capability_scope_mismatch",
      capability,
    },
  ]) {
    const markup = renderView({ state, legacyPassthroughRouteIds });
    assert.match(
      markup,
      /class="desktop-production-router-legacy"[^>]*hidden="" inert=""/u,
    );
    assert.match(markup, /desktop-production-route-stage/u);
  }
});

test("breadcrumb return and retry actions use only the injected ports", async () => {
  let clearCalls = 0;
  let retryCalls = 0;
  returnToDesktopWorkbench({
    clearHash() {
      clearCalls += 1;
    },
  });
  assert.equal(clearCalls, 1);

  await retryDesktopProductionRoute(async () => {
    retryCalls += 1;
  });
  assert.equal(retryCalls, 1);
  assert.match(
    source,
    /data-action="return-workbench"[\s\S]*returnToDesktopWorkbench/u,
  );
  assert.match(
    source,
    /data-action="retry-route"[\s\S]*retryDesktopProductionRoute/u,
  );
});

test("Escape returns rejected deep links through the injected navigation port only", () => {
  let clearCalls = 0;
  let prevented = 0;
  const navigation = {
    clearHash() {
      clearCalls += 1;
    },
  };
  const event = {
    key: "Escape",
    preventDefault() {
      prevented += 1;
    },
  };

  assert.equal(
    handleDesktopProductionRouteBoundaryEscape("not_found", navigation, event),
    true,
  );
  assert.equal(clearCalls, 1);
  assert.equal(prevented, 1);
  assert.equal(
    handleDesktopProductionRouteBoundaryEscape("ready", navigation, event),
    false,
  );
  assert.equal(clearCalls, 1);
  assert.equal(prevented, 1);
});

test("router styling and copy remain native, responsive, and bilingual", () => {
  assert.doesNotMatch(
    source,
    /<iframe|<webview|shell\.openExternal|window\.open|href=/iu,
  );
  assert.match(stylesheet, /var\(--desktop-surface-3\)/u);
  assert.match(stylesheet, /@media \(max-width:/u);
  assert.match(stylesheet, /:focus-visible/u);
  assert.match(messages, /desktopProductionRouterEnUS/u);
  assert.match(messages, /desktopProductionRouterZhCN/u);
  for (const key of [
    "desktopProductionRouter.breadcrumb",
    "desktopProductionRouter.returnWorkbench",
    "desktopProductionRouter.loading.title",
    "desktopProductionRouter.forbidden.title",
    "desktopProductionRouter.unavailable.title",
    "desktopProductionRouter.error.title",
    "desktopProductionRouter.malformed.title",
    "desktopProductionRouter.notFound.title",
  ]) {
    assert.equal(messages.split(`'${key}'`).length, 3);
  }
  const referencedTokens = new Set(
    [...stylesheet.matchAll(/var\((--desktop-[a-z0-9-]+)/gu)].map(
      (entry) => entry[1],
    ),
  );
  for (const token of referencedTokens) {
    assert.match(globalStylesheet, new RegExp(`${token}\\s*:`, "u"));
  }
});

function renderView({
  state,
  authenticationPassthroughRouteIds,
  forceLegacyChildren,
  legacyPassthroughRouteIds,
}) {
  return render(
    React.createElement(
      DesktopProductionRouterView,
      {
        state,
        registry,
        retry: async () => {},
        navigation: { clearHash() {} },
        authenticationPassthroughRouteIds,
        forceLegacyChildren,
        legacyPassthroughRouteIds,
      },
      React.createElement(
        "article",
        { "data-legacy": true },
        "Legacy workbench",
      ),
    ),
  );
}

function render(element) {
  return renderToStaticMarkup(React.createElement(I18nProvider, null, element));
}

function hashLocation(initialHash) {
  return {
    port: {
      readHash: () => initialHash,
      subscribe: () => () => {},
    },
  };
}
