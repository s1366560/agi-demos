import { readFileSync, readdirSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import {
  REQUIRED_ACCESSIBILITY_STATES,
  assertCompleteAccessibilityRouteResults,
  buildCanonicalAccessibilityDataContract,
  buildCanonicalAccessibilityRouteInventory,
  classifyDesktopDataStateRequest,
  deriveZoomEquivalentViewport,
  materializeAccessibilityDataPath,
  materializeAccessibilityRoutePath,
} from "../contracts/accessibility/accessibility-automation-contract.mjs";
import { auditKeyboardTraversal } from "../contracts/accessibility/playwright-keyboard-audit.mjs";
import { createAccessibilityAuthorityFixture } from "./accessibility-authority-fixture.mjs";
import { createAccessibilityWebSocketFixture } from "./accessibility-websocket-fixture.mjs";

const PARITY_ROOT = new URL("../contracts/desktop-web-parity/", import.meta.url);
const CONTRACT_URL = new URL("web-route-inventory.v2.json", PARITY_ROOT);
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const ZOOM_400_VIEWPORT = deriveZoomEquivalentViewport(
  { width: 1280, height: 720 },
  4,
);
const TEST_SCOPE = Object.freeze({
  tenantId:
    process.env.AGISTACK_ACCESSIBILITY_TENANT_ID ?? "accessibility-tenant",
  projectId:
    process.env.AGISTACK_ACCESSIBILITY_PROJECT_ID ?? "accessibility-project",
  workspaceId:
    process.env.AGISTACK_ACCESSIBILITY_WORKSPACE_ID ?? "accessibility-workspace",
  conversationId:
    process.env.AGISTACK_ACCESSIBILITY_CONVERSATION_ID ?? "accessibility-conversation",
  instanceId:
    process.env.AGISTACK_ACCESSIBILITY_INSTANCE_ID ?? "accessibility-instance",
});
const routeContract = JSON.parse(readFileSync(CONTRACT_URL, "utf8"));
const inventory = buildCanonicalAccessibilityRouteInventory(
  routeContract,
);
const dataContractByRouteId = new Map(
  buildCanonicalAccessibilityDataContract(
    routeContract,
    readdirSync(PARITY_ROOT)
      .filter((name) =>
        /^parity-capability-definitions\.\d{2}-.+\.v2\.json$/u.test(name),
      )
      .sort()
      .map((name) => JSON.parse(readFileSync(new URL(name, PARITY_ROOT), "utf8"))),
  ).routes.map((contract) => [contract.routeId, contract]),
);

for (const route of inventory.routes) {
  test(`WCAG 2.2 AA canonical route: ${route.routeId}`, async ({
    page,
  }, testInfo) => {
    const path = materializeAccessibilityRoutePath(route, TEST_SCOPE);
    const authorityFixture = createAccessibilityAuthorityFixture(TEST_SCOPE);
    const webSocketFixture = createAccessibilityWebSocketFixture(TEST_SCOPE);
    await installAccessibilityAuthorityFixture(
      page,
      authorityFixture,
      webSocketFixture,
    );
    await authenticateDesktopAuthority(page);
    const results = await runAccessibilityStates(
      page,
      testInfo,
      route,
      path,
      authorityFixture,
      webSocketFixture,
    );

    assertCompleteAccessibilityRouteResults(
      { sourceRevision: inventory.sourceRevision, routes: [route] },
      [{ routeId: route.routeId, states: results }],
    );
    await testInfo.attach(`${route.routeId}-accessibility-state-results`, {
      body: JSON.stringify(results, null, 2),
      contentType: "application/json",
    });
    expect(
      results.filter(({ status }) => status === "failed"),
      `Every required accessibility state must pass for ${route.routeId}`,
    ).toEqual([]);
  });
}

async function runAccessibilityStates(
  page,
  testInfo,
  route,
  path,
  authorityFixture,
  webSocketFixture,
) {
  const assessments = {
    default: async () => {
      await prepareDesktopRoute(page, route, path, "default");
      return runAxeScan(page, testInfo, route.routeId, "default");
    },
    keyboard: async () => {
      await prepareDesktopRoute(page, route, path, "keyboard");
      await waitForDesktopRouteDataBaseline(page, route);
      const keyboardEvidence = await auditKeyboardTraversal(page);
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "keyboard",
      );
      return [...keyboardEvidence, ...axeEvidence];
    },
    "text-zoom-200": async () => {
      await prepareDesktopRoute(page, route, path, "text-zoom-200");
      const zoomAudit = await page.evaluate(() => {
        document.documentElement.style.fontSize = "200%";
        const root = document.documentElement;
        const body = document.body;
        return {
          fontSize: document.documentElement.style.fontSize,
          horizontalOverflow:
            Math.max(root.scrollWidth, body.scrollWidth) -
            Math.max(root.clientWidth, body.clientWidth),
        };
      });
      expect(
        zoomAudit.fontSize,
        "The 200% text zoom state must be applied",
      ).toBe("200%");
      expect(
        zoomAudit.horizontalOverflow,
        "The route must reflow without page-level horizontal overflow at 200% text zoom",
      ).toBeLessThanOrEqual(1);
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "text-zoom-200",
      );
      return [
        "text-zoom:200%",
        `horizontal-overflow:${zoomAudit.horizontalOverflow}`,
        ...axeEvidence,
      ];
    },
    "reflow-320": async () => {
      await prepareDesktopRoute(page, route, path, "reflow-320", {
        viewport: { width: 320, height: 720 },
      });
      const horizontalOverflow = await page.evaluate(pageHorizontalOverflow);
      expect(
        horizontalOverflow,
        "The route must reflow without page-level horizontal overflow at 320 CSS px",
      ).toBeLessThanOrEqual(1);
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "reflow-320",
      );
      return [
        "viewport:320x720",
        `horizontal-overflow:${horizontalOverflow}`,
        ...axeEvidence,
      ];
    },
    "zoom-400": async () => {
      await prepareDesktopRoute(page, route, path, "zoom-400", {
        viewport: {
          width: ZOOM_400_VIEWPORT.width,
          height: ZOOM_400_VIEWPORT.height,
        },
      });
      const horizontalOverflow = await page.evaluate(pageHorizontalOverflow);
      expect(
        horizontalOverflow,
        "The route must reflow without page-level horizontal overflow at the 400% zoom equivalent viewport",
      ).toBeLessThanOrEqual(1);
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "zoom-400",
      );
      return [
        "zoom-factor:4",
        `reference-viewport:${ZOOM_400_VIEWPORT.referenceWidth}x${ZOOM_400_VIEWPORT.referenceHeight}`,
        `equivalent-css-viewport:${ZOOM_400_VIEWPORT.width}x${ZOOM_400_VIEWPORT.height}`,
        `horizontal-overflow:${horizontalOverflow}`,
        ...axeEvidence,
      ];
    },
    "reduced-motion": async () => {
      await prepareDesktopRoute(page, route, path, "reduced-motion", {
        reducedMotion: "reduce",
      });
      expect(
        await page.evaluate(
          () => matchMedia("(prefers-reduced-motion: reduce)").matches,
        ),
        "Reduced-motion emulation must be active",
      ).toBe(true);
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "reduced-motion",
      );
      return ["media:prefers-reduced-motion=reduce", ...axeEvidence];
    },
    "forced-colors": async () => {
      await prepareDesktopRoute(page, route, path, "forced-colors", {
        forcedColors: "active",
      });
      expect(
        await page.evaluate(
          () => matchMedia("(forced-colors: active)").matches,
        ),
        "Forced-colors emulation must be active",
      ).toBe(true);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, "forced-colors", {
        // Chromium emulation exposes author colors over a synthetic black canvas to axe.
        // The remaining A/AA rules still run; contrast is covered in normal light/dark states.
        disabledRules: ["color-contrast"],
      });
      return ["media:forced-colors=active", ...axeEvidence];
    },
    "theme-light": async () => {
      await prepareDesktopRoute(page, route, path, "theme-light", {
        theme: "light",
      });
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "theme-light",
      );
      return ["theme:light", ...axeEvidence];
    },
    "theme-dark": async () => {
      await prepareDesktopRoute(page, route, path, "theme-dark", {
        theme: "dark",
      });
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "theme-dark",
      );
      return ["theme:dark", ...axeEvidence];
    },
    "locale-en-US": async () => {
      await prepareDesktopRoute(page, route, path, "locale-en-US", {
        locale: "en",
      });
      await expect(page.locator("html")).toHaveAttribute("lang", "en");
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "locale-en-US",
      );
      return ["locale:en-US", ...axeEvidence];
    },
    "locale-zh-CN": async () => {
      await prepareDesktopRoute(page, route, path, "locale-zh-CN", {
        locale: "zh-CN",
      });
      await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "locale-zh-CN",
      );
      return ["locale:zh-CN", ...axeEvidence];
    },
    "role-admin": () =>
      runDesktopRoleState(
        page,
        testInfo,
        route,
        path,
        authorityFixture,
        "admin",
      ),
    "role-member": () =>
      runDesktopRoleState(
        page,
        testInfo,
        route,
        path,
        authorityFixture,
        "member",
      ),
    "data-loading": () =>
      runInjectedDesktopDataState(
        page,
        testInfo,
        route,
        path,
        authorityFixture,
        webSocketFixture,
        "loading",
      ),
    "data-empty": () =>
      runInjectedDesktopDataState(
        page,
        testInfo,
        route,
        path,
        authorityFixture,
        webSocketFixture,
        "empty",
      ),
    "data-forbidden": () =>
      runInjectedDesktopDataState(
        page,
        testInfo,
        route,
        path,
        authorityFixture,
        webSocketFixture,
        "forbidden",
      ),
    "data-error": () =>
      runInjectedDesktopDataState(
        page,
        testInfo,
        route,
        path,
        authorityFixture,
        webSocketFixture,
        "error",
      ),
    "data-conflict": () =>
      runInjectedDesktopDataState(
        page,
        testInfo,
        route,
        path,
        authorityFixture,
        webSocketFixture,
        "conflict",
      ),
  };

  const results = [];
  for (const stateId of REQUIRED_ACCESSIBILITY_STATES) {
    webSocketFixture.setState("baseline");
    try {
      const evidence = await test.step(stateId, () => assessments[stateId]());
      results.push({ stateId, status: "passed", evidence });
    } catch (error) {
      results.push({
        stateId,
        status: "failed",
        evidence: [
          `error:${error instanceof Error ? error.message : String(error)}`,
        ],
      });
    } finally {
      webSocketFixture.releasePending();
    }
  }
  return results;
}

async function installAccessibilityAuthorityFixture(
  page,
  authorityFixture,
  webSocketFixture,
) {
  await page.routeWebSocket(
    /\/api\/v1\/agent\/ws(?:\?.*)?$/u,
    (route) => webSocketFixture.handle(route),
  );
  await page.route("**/api/v1/**", async (intercepted) => {
    const request = intercepted.request();
    const resolved = authorityFixture.resolve({
      method: request.method(),
      url: request.url(),
    });
    if (resolved === null) {
      await intercepted.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "accessibility_authority_fixture_unhandled",
          reason_code: "accessibility_authority_fixture_unhandled",
        }),
      });
      return;
    }
    await intercepted.fulfill({
      status: resolved.status,
      contentType: "application/json",
      body: JSON.stringify(resolved.body),
    });
  });
}

async function authenticateDesktopAuthority(page, expectedRole = "admin") {
  const response = await page.goto("/", { waitUntil: "domcontentloaded" });
  expect(response, "Desktop Browser QA must receive an initial HTTP response").not.toBeNull();
  expect(response?.status(), "Desktop Browser QA entry response must be below 400").toBeLessThan(
    400,
  );
  await page.waitForFunction(() =>
    Boolean(document.querySelector("#root")?.firstElementChild),
  );
  const login = page.locator(".desktop-login-card");
  await expect(login).toBeVisible();
  await login
    .locator('[data-parity-target-id="email_entry"]')
    .fill("admin@accessibility.invalid");
  await login.locator('input[type="password"]').fill("accessibility-fixture-password");
  await login.locator(".desktop-login-submit").click();
  await expect(page.locator(".desktop-login-screen")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.locator(".desktop-design-profile")).toContainText(
    `Accessibility ${expectedRole}`,
  );
}

async function navigateDesktopRoute(page, path) {
  await page.evaluate(() => {
    window.location.hash = "";
  });
  await expect(page.locator(".desktop-production-route-stage")).toHaveCount(0);
  await page.evaluate((canonicalPath) => {
    window.location.hash = canonicalPath;
  }, path);
}

async function resetAccessibilityEmulation(page, media = {}) {
  expect(page.url(), "Desktop authority must be authenticated before route auditing").not.toBe(
    "about:blank",
  );
  await page.emulateMedia({
    reducedMotion: media.reducedMotion ?? "no-preference",
    forcedColors: media.forcedColors ?? "none",
  });
  await page.setViewportSize(media.viewport ?? { width: 1280, height: 720 });
  await page.evaluate(() => {
    document.documentElement.style.removeProperty("font-size");
    document.documentElement.style.removeProperty("zoom");
  });
}

async function prepareDesktopRoute(page, route, path, stateId, options = {}) {
  await resetAccessibilityEmulation(page, options);
  await page.evaluate(
    ({ locale, theme }) => {
      const preferences = [
        ["agistack.desktop.locale", locale],
        ["agistack.desktop.theme", theme],
      ];
      for (const [key, value] of preferences) {
        const oldValue = window.localStorage.getItem(key);
        window.localStorage.setItem(key, value);
        window.dispatchEvent(
          new StorageEvent("storage", {
            key,
            oldValue,
            newValue: value,
            storageArea: window.localStorage,
          }),
        );
      }
    },
    {
      locale: options.locale ?? "en",
      theme: options.theme ?? "light",
    },
  );
  await assertDesktopRouteReached(page, route, path, stateId, options);
}

async function assertDesktopRouteReached(
  page,
  route,
  path,
  stateId,
  options = {},
) {
  await navigateDesktopRoute(page, path);

  const stage = page.locator(
    `.desktop-production-route-stage[data-route-id="${route.routeId}"]`,
  );
  await expect(
    stage,
    "Canonical Desktop route must own the production route stage",
  ).toHaveCount(1);
  await expect(
    stage,
    `Canonical Desktop route must mount its content for ${stateId}`,
  ).toHaveAttribute(
    "data-route-state",
    options.allowMemberRouteState
      ? /^(?:ready|degraded|unavailable|forbidden)$/u
      : /^(?:ready|degraded)$/u,
  );
}

async function runDesktopRoleState(
  page,
  testInfo,
  route,
  path,
  authorityFixture,
  role,
) {
  authorityFixture.setRole(role);
  const before = authorityFixture.observation();
  await authenticateDesktopAuthority(page, role);
  await prepareDesktopRoute(page, route, path, `role-${role}`, {
    allowMemberRouteState: role === "member",
  });
  await expect
    .poll(() => authorityFixture.observation().resolvedRequests)
    .toBeGreaterThan(before.resolvedRequests);
  const authority = authorityFixture.observation();
  expect(authority.role).toBe(role);
  expect(authority.authorityRevision).toBeGreaterThanOrEqual(before.authorityRevision);
  const stateId = `role-${role}`;
  const routeState = await page
    .locator(`.desktop-production-route-stage[data-route-id="${route.routeId}"]`)
    .getAttribute("data-route-state");
  const axeEvidence = await runAxeScan(page, testInfo, route.routeId, stateId);
  return [
    `authority-role:${authority.role}`,
    `authority-revision:${authority.authorityRevision}`,
    `authority-resolved-requests:${authority.resolvedRequests - before.resolvedRequests}`,
    `route-state:${routeState}`,
    ...axeEvidence,
  ];
}

const desktopDataStateResponse = Object.freeze({
  empty: Object.freeze({
    status: 200,
    body: { data: [], items: [], results: [], total: 0 },
  }),
  forbidden: Object.freeze({
    status: 403,
    body: { detail: "accessibility_fixture_forbidden" },
  }),
  error: Object.freeze({
    status: 500,
    body: { detail: "accessibility_fixture_error" },
  }),
  conflict: Object.freeze({
    status: 409,
    body: { detail: "accessibility_fixture_conflict" },
  }),
});

const desktopDataStateSelectors = Object.freeze({
  loading:
    '[aria-busy="true"], [role="status"], [data-state="loading"], [data-route-state="loading"]',
  empty: '[data-state="empty"], [role="status"], .ant-empty',
  forbidden:
    '[data-state="forbidden"], [role="alert"], [data-route-state="forbidden"]',
  error: '[data-state="error"], [role="alert"], [data-route-state="error"]',
  conflict: '[data-state="conflict"], [role="alert"]',
});

async function runInjectedDesktopDataState(
  page,
  testInfo,
  route,
  path,
  authorityFixture,
  webSocketFixture,
  state,
) {
  await resetAccessibilityEmulation(page);
  authorityFixture.setRole("admin");
  await authenticateDesktopAuthority(page, "admin");
  await prepareDesktopRoute(page, route, path, `data-${state}-baseline`);
  await waitForDesktopRouteDataBaseline(page, route);
  const dataContract = desktopDataStateContract(route);
  if (dataContract.transport === "websocket") {
    return runInjectedDesktopWebSocketState(
      page,
      testInfo,
      route,
      path,
      webSocketFixture,
      state,
    );
  }
  if (dataContract.injectionTrigger === "route-open") {
    await page.evaluate(() => {
      window.location.hash = "";
    });
    await expect(page.locator(".desktop-production-route-stage")).toHaveCount(0);
  }
  let injectedRequests = 0;
  const pendingRoutes = [];
  const requestSequence = [];
  const exactDataMethod = dataContract.method;
  const exactDataPath = dataContract.path;
  const handler = async (intercepted) => {
    const request = intercepted.request();
    const pathname = new URL(request.url()).pathname;
    const routeSurfaceActive =
      (await page
        .locator(
          `.desktop-production-route-stage[data-route-id="${route.routeId}"]`,
        )
        .count()) === 1;
    const classification = classifyDesktopDataStateRequest({
      method: request.method(),
      pathname,
      exactMethod: exactDataMethod,
      exactDataPath,
      routeSurfaceActive,
    });
    if (request.method() === exactDataMethod && pathname === exactDataPath) {
      requestSequence.push(
        `${requestSequence.length + 1}:${classification}:${routeSurfaceActive ? "surface" : "authority"}`,
      );
    }
    const eligible = classification === "inject";
    if (!eligible) {
      await intercepted.fallback();
      return;
    }
    injectedRequests += 1;
    if (state === "loading") {
      pendingRoutes.push(intercepted);
      return;
    }
    const response = desktopDataStateResponseForRoute(
      route,
      dataContract,
      state,
      authorityFixture.observation().authorityRevision,
    );
    await intercepted.fulfill({
      status: response.status,
      contentType: "application/json",
      body: JSON.stringify(response.body),
    });
  };
  await page.route("**/api/v1/**", handler);
  try {
    if (dataContract.injectionTrigger === "route-open") {
      await prepareDesktopRoute(page, route, path, `data-${state}`, {
        allowLoading: state === "loading",
      });
    }
    await triggerDesktopDataStateRequest(page, route, dataContract);
    await expect
      .poll(() => injectedRequests, { timeout: 10_000 })
      .toBeGreaterThan(0);
    if (requestSequence.length > 0) {
      await testInfo.attach(`${route.routeId}-data-${state}-request-sequence`, {
        body: JSON.stringify(requestSequence, null, 2),
        contentType: "application/json",
      });
    }
    await expect(
      page.locator(desktopDataStateSelector(route, state)).first(),
      `The Desktop route must expose a semantic ${state} state after deterministic API injection`,
    ).toBeVisible();
    const stateId = `data-${state}`;
    const axeEvidence = await runAxeScan(
      page,
      testInfo,
      route.routeId,
      stateId,
    );
    return [
      `network-state:${state}`,
      `injected-requests:${injectedRequests}`,
      ...(requestSequence.length > 0
        ? [`request-sequence:${requestSequence.join(",")}`]
        : []),
      ...axeEvidence,
    ];
  } finally {
    await Promise.allSettled(
      pendingRoutes.map((pending) =>
        pending.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(desktopDataStateResponse.empty.body),
        }),
      ),
    );
    await page.unroute("**/api/v1/**", handler);
  }
}

async function runInjectedDesktopWebSocketState(
  page,
  testInfo,
  route,
  path,
  webSocketFixture,
  state,
) {
  webSocketFixture.setState(state);
  const before = webSocketFixture.observation();
  try {
    await authenticateDesktopAuthority(page, "admin");
    await prepareDesktopRoute(page, route, path, `data-${state}`, {
      allowLoading: state === "loading",
    });
    await expect
      .poll(() => webSocketFixture.observation().connections, {
        timeout: 10_000,
      })
      .toBeGreaterThan(before.connections);
    const liveState = page.locator(
      `.desktop-status-bar-segment[data-state="${state}"]`,
    );
    await expect(
      liveState,
      `The Agent Workspace must expose the ${state} WebSocket state semantically`,
    ).toBeVisible();
    const axeEvidence = await runAxeScan(
      page,
      testInfo,
      route.routeId,
      `data-${state}`,
    );
    const observation = webSocketFixture.observation();
    return [
      `network-state:${state}`,
      `transport:websocket`,
      `websocket-connections:${observation.connections - before.connections}`,
      `websocket-client-messages:${observation.receivedMessages - before.receivedMessages}`,
      ...axeEvidence,
    ];
  } finally {
    webSocketFixture.releasePending();
    webSocketFixture.setState("baseline");
  }
}

async function waitForDesktopRouteDataBaseline(page, route) {
  const pageState = page
    .locator(
      `.desktop-production-route-stage[data-route-id="${route.routeId}"] [data-state]`,
    )
    .first();
  await expect(
    pageState,
    "The canonical route must expose a page-level data state before fault injection",
  ).toHaveCount(1);
  await expect(
    pageState,
    "The canonical route baseline must settle before fault injection",
  ).not.toHaveAttribute("data-state", /^(?:loading|scope_switch)$/u);
}

function desktopDataStateSelector(route, state) {
  if (route.routeId === "tenant-tenant-overview") {
    if (state === "empty") return '.tenant-overview-page [data-state="empty"]';
    return `.tenant-overview-page[data-state="${state}"]`;
  }
  return desktopDataStateSelectors[state];
}

function desktopDataStateContract(route) {
  const contract = dataContractByRouteId.get(route.routeId);
  if (!contract) {
    throw new Error(`accessibility_data_contract_missing:${route.routeId}`);
  }
  if (contract.method === "WS") {
    return Object.freeze({ transport: "websocket" });
  }
  return Object.freeze({
    transport: "http",
    method: contract.method,
    path: materializeAccessibilityDataPath(contract, TEST_SCOPE),
    injectionTrigger: contract.injectionTrigger ?? "route-open",
  });
}

async function triggerDesktopDataStateRequest(page, route, dataContract) {
  if (dataContract.injectionTrigger === "route-open") return;
  if (dataContract.injectionTrigger === "search-submit") {
    const surface = page.locator(
      `.desktop-production-route-stage[data-route-id="${route.routeId}"] .desktop-search`,
    );
    const query = surface.locator('[data-action="search-query"]');
    const submit = surface.locator('[data-action="search-submit"]');
    await expect(query, "The Search surface must expose its contract-bound query input").toBeVisible();
    await expect(submit, "The Search surface must expose its contract-bound submit action").toBeVisible();
    await query.fill("accessibility deterministic search");
    await submit.click();
    return;
  }
  if (dataContract.injectionTrigger !== "workspace-collaboration-refresh") {
    throw new Error(
      `accessibility_data_injection_trigger_invalid:${dataContract.injectionTrigger}`,
    );
  }
  const refresh = page.locator(
    `.desktop-production-route-stage[data-route-id="${route.routeId}"] ` +
      '.workspace-collaboration-canvas [data-action="refresh"]',
  );
  await expect(
    refresh,
    "The collaboration surface must expose its contract-bound refresh action",
  ).toBeVisible();
  await expect(refresh).toBeEnabled();
  await refresh.click();
}

function desktopDataStateResponseForRoute(route, dataContract, state, authorityRevision) {
  if (route.routeId === "project-project-search" && state === "empty") {
    return {
      status: 200,
      body: {
        results: [],
        total: 0,
        limit: 50,
        search_type: "advanced",
      },
    };
  }
  if (
    state === "empty" &&
    dataContract.path.endsWith("/collaboration/authority")
  ) {
    return {
      status: 200,
      body: {
        contract_version: "2.0.0",
        tenant_id: TEST_SCOPE.tenantId,
        project_id: TEST_SCOPE.projectId,
        workspace_id: TEST_SCOPE.workspaceId,
        revision: authorityRevision,
        cursor: `accessibility-workspace-revision-${authorityRevision}`,
      },
    };
  }
  if (route.routeId === "tenant-tenant-overview" && state === "empty") {
    return {
      status: 200,
      body: {
        authority_revision: authorityRevision,
        tenant_info: {
          organization_id: "Accessibility QA",
          plan: "enterprise",
          region: null,
          next_billing_date: null,
        },
        storage: { used: 0, total: 1024, percentage: 0 },
        projects: { active: 0, new_this_week: 0, list: [] },
        members: { total: 0, new_added: 0 },
        memory_history: [],
      },
    };
  }
  if (route.routeId === "tenant-tenant-instances" && state === "empty") {
    return {
      status: 200,
      body: {
        instances: [],
        total: 0,
        page: 1,
        page_size: 20,
        authority_revision: authorityRevision,
      },
    };
  }
  if (route.routeId === "tenant-tenant-clusters" && state === "empty") {
    return {
      status: 200,
      body: {
        clusters: [],
        total: 0,
        page: 1,
        page_size: 20,
        authority_revision: authorityRevision,
      },
    };
  }
  if (route.routeId === "tenant-tenant-deploy" && state === "empty") {
    return {
      status: 200,
      body: {
        deploys: [],
        total: 0,
        page: 1,
        page_size: 20,
        authority_revision: authorityRevision,
      },
    };
  }
  if (route.routeId === "tenant-tenant-instance-templates" && state === "empty") {
    return {
      status: 200,
      body: {
        templates: [],
        total: 0,
        page: 1,
        page_size: 20,
        authority_revision: authorityRevision,
      },
    };
  }
  if (route.routeId === "tenant-tenant-dead-letter-queue" && state === "empty") {
    return {
      status: 200,
      body: {
        messages: [],
        total: 0,
        limit: 50,
        offset: 0,
        authority_revision: authorityRevision,
      },
    };
  }
  return desktopDataStateResponse[state];
}

function pageHorizontalOverflow() {
  const root = document.documentElement;
  const body = document.body;
  return (
    Math.max(root.scrollWidth, body.scrollWidth) -
    Math.max(root.clientWidth, body.clientWidth)
  );
}

async function runAxeScan(page, testInfo, routeId, stateId, options = {}) {
  const builder = new AxeBuilder({ page }).withTags(WCAG_TAGS);
  if (options.disabledRules?.length) builder.disableRules(options.disabledRules);
  const result = await builder.analyze();
  if (result.violations.length > 0) {
    await testInfo.attach(`${routeId}-${stateId}-axe-violations`, {
      body: JSON.stringify(result.violations, null, 2),
      contentType: "application/json",
    });
  }
  expect(
    result.violations.map(({ id, impact, nodes }) => ({
      id,
      impact,
      nodes: nodes.map(({ target, html, failureSummary }) => ({
        target,
        html,
        failureSummary,
      })),
    })),
    `Axe WCAG A/AA violations for ${routeId} in ${stateId}`,
  ).toEqual([]);
  return [`axe:violations=0`, `axe:passes=${result.passes.length}`];
}
