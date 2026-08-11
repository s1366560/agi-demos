import { readFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import {
  REQUIRED_ACCESSIBILITY_STATES,
  assertCompleteAccessibilityRouteResults,
  buildCanonicalAccessibilityRouteInventory,
  materializeAccessibilityRoutePath,
} from "../contracts/accessibility/accessibility-automation-contract.mjs";

const CONTRACT_URL = new URL(
  "../contracts/desktop-web-parity/web-route-inventory.v2.json",
  import.meta.url,
);
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const TEST_SCOPE = Object.freeze({
  tenantId:
    process.env.AGISTACK_ACCESSIBILITY_TENANT_ID ?? "accessibility-tenant",
  projectId:
    process.env.AGISTACK_ACCESSIBILITY_PROJECT_ID ?? "accessibility-project",
});
const inventory = buildCanonicalAccessibilityRouteInventory(
  JSON.parse(readFileSync(CONTRACT_URL, "utf8")),
);

test.describe.configure({ mode: "serial" });

for (const route of inventory.routes) {
  test(`WCAG 2.2 AA canonical route: ${route.routeId}`, async ({
    page,
  }, testInfo) => {
    const path = materializeAccessibilityRoutePath(route, TEST_SCOPE);
    const results = await runAccessibilityStates(page, testInfo, route, path);

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

async function runAccessibilityStates(page, testInfo, route, path) {
  const assessments = {
    default: async () => {
      await prepareDesktopRoute(page, route, path, "default");
      return runAxeScan(page, testInfo, route.routeId, "default");
    },
    keyboard: async () => {
      await prepareDesktopRoute(page, route, path, "keyboard");
      await page.keyboard.press("Tab");
      const focus = await page.evaluate(() => ({
        tagName: document.activeElement?.tagName ?? "",
        attached: Boolean(
          document.activeElement && document.contains(document.activeElement),
        ),
      }));
      expect(focus.attached, "Tab focus must stay in the document").toBe(true);
      expect(
        ["BODY", "HTML"],
        "Tab focus must move to an interactive element",
      ).not.toContain(focus.tagName);
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "keyboard",
      );
      return [`focus:${focus.tagName}`, ...axeEvidence];
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
      await prepareDesktopRoute(page, route, path, "zoom-400");
      const zoomAudit = await page.evaluate(() => {
        document.documentElement.style.zoom = "4";
        const root = document.documentElement;
        const body = document.body;
        return {
          zoom: document.documentElement.style.zoom,
          horizontalOverflow:
            Math.max(root.scrollWidth, body.scrollWidth) -
            Math.max(root.clientWidth, body.clientWidth),
        };
      });
      expect(zoomAudit.zoom, "The 400% zoom state must be applied").toBe("4");
      expect(
        zoomAudit.horizontalOverflow,
        "The route must reflow without page-level horizontal overflow at 400% zoom",
      ).toBeLessThanOrEqual(1);
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "zoom-400",
      );
      return [
        "css-zoom:4",
        `horizontal-overflow:${zoomAudit.horizontalOverflow}`,
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
      const axeEvidence = await runAxeScan(
        page,
        testInfo,
        route.routeId,
        "forced-colors",
      );
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
      runDesktopRoleState(page, testInfo, route, path, "admin"),
    "role-member": () =>
      runDesktopRoleState(page, testInfo, route, path, "member"),
    "data-loading": () =>
      runInjectedDesktopDataState(page, testInfo, route, path, "loading"),
    "data-empty": () =>
      runInjectedDesktopDataState(page, testInfo, route, path, "empty"),
    "data-forbidden": () =>
      runInjectedDesktopDataState(page, testInfo, route, path, "forbidden"),
    "data-error": () =>
      runInjectedDesktopDataState(page, testInfo, route, path, "error"),
    "data-conflict": () =>
      runInjectedDesktopDataState(page, testInfo, route, path, "conflict"),
  };

  const results = [];
  for (const stateId of REQUIRED_ACCESSIBILITY_STATES) {
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
    }
  }
  return results;
}

async function resetAccessibilityEmulation(page, media = {}) {
  if (page.url() === "about:blank") {
    await page.goto("/", { waitUntil: "domcontentloaded" });
  }
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
      window.localStorage.setItem("agistack.desktop.locale", locale);
      window.localStorage.setItem("agistack.desktop.theme", theme);
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
  const parameters = new URLSearchParams({ accessibilityState: stateId });
  if (options.role) parameters.set("accessibilityRole", options.role);
  const response = await page.goto(`/?${parameters.toString()}#${path}`, {
    waitUntil: "domcontentloaded",
  });
  expect(
    response,
    "Canonical Desktop route must receive an HTTP response",
  ).not.toBeNull();
  expect(
    response?.status(),
    "Canonical Desktop route response must be below 400",
  ).toBeLessThan(400);
  await page.waitForFunction(() =>
    Boolean(document.querySelector("#root")?.firstElementChild),
  );

  const stage = page.locator(
    `.desktop-production-route-stage[data-route-id="${route.routeId}"]`,
  );
  await expect(
    stage,
    "Canonical Desktop route must own the production route stage",
  ).toHaveCount(1);
  const excludedStates = options.allowLoading
    ? /^(?:not_found|malformed)$/u
    : /^(?:loading|not_found|malformed)$/u;
  await expect(stage).not.toHaveAttribute("data-route-state", excludedStates);
  const routeState = await stage.getAttribute("data-route-state");
  expect(
    routeState,
    "Canonical Desktop route state must be observable",
  ).toBeTruthy();
}

async function runDesktopRoleState(page, testInfo, route, path, role) {
  await prepareDesktopRoute(page, route, path, `role-${role}`, { role });
  const stage = page.locator(
    `.desktop-production-route-stage[data-route-id="${route.routeId}"]`,
  );
  await expect(
    stage,
    `Desktop Browser QA must project the requested ${role} authority fixture`,
  ).toHaveAttribute("data-accessibility-role", role);
  const stateId = `role-${role}`;
  const axeEvidence = await runAxeScan(page, testInfo, route.routeId, stateId);
  return [`role:${role}`, ...axeEvidence];
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

async function runInjectedDesktopDataState(page, testInfo, route, path, state) {
  await resetAccessibilityEmulation(page);
  let injectedRequests = 0;
  const pendingRoutes = [];
  const handler = async (intercepted) => {
    const request = intercepted.request();
    const pathname = new URL(request.url()).pathname;
    const eligible =
      request.method() === "GET" &&
      pathname.startsWith("/api/v1/") &&
      !pathname.startsWith("/api/v1/auth/") &&
      pathname !== "/api/v1/users/me";
    if (!eligible || injectedRequests > 0) {
      await intercepted.continue();
      return;
    }
    injectedRequests += 1;
    if (state === "loading") {
      pendingRoutes.push(intercepted);
      return;
    }
    const response = desktopDataStateResponse[state];
    await intercepted.fulfill({
      status: response.status,
      contentType: "application/json",
      body: JSON.stringify(response.body),
    });
  };
  await page.route("**/api/v1/**", handler);
  try {
    await prepareDesktopRoute(page, route, path, `data-${state}`, {
      allowLoading: state === "loading",
    });
    await expect
      .poll(() => injectedRequests, { timeout: 10_000 })
      .toBeGreaterThan(0);
    await expect(
      page.locator(desktopDataStateSelectors[state]).first(),
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
      ...axeEvidence,
    ];
  } finally {
    await Promise.all(
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

function pageHorizontalOverflow() {
  const root = document.documentElement;
  const body = document.body;
  return (
    Math.max(root.scrollWidth, body.scrollWidth) -
    Math.max(root.clientWidth, body.clientWidth)
  );
}

async function runAxeScan(page, testInfo, routeId, stateId) {
  const result = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
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
      nodes: nodes.length,
    })),
    `Axe WCAG A/AA violations for ${routeId} in ${stateId}`,
  ).toEqual([]);
  return [`axe:violations=0`, `axe:passes=${result.passes.length}`];
}
