import { readFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import {
  buildReleaseAccessibilitySurfaceInventory,
  deriveZoomEquivalentViewport,
} from "../contracts/accessibility/accessibility-automation-contract.mjs";
import { auditKeyboardTraversal } from "../contracts/accessibility/playwright-keyboard-audit.mjs";

const CONTRACT_URL = new URL(
  "../contracts/desktop-web-parity/web-route-inventory.v2.json",
  import.meta.url,
);
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const ZOOM_400_VIEWPORT = deriveZoomEquivalentViewport(
  { width: 1280, height: 720 },
  4,
);
const STATES = Object.freeze([
  "default",
  "keyboard",
  "text-zoom-200",
  "reflow-320",
  "zoom-400",
  "reduced-motion",
  "forced-colors",
  "theme-light",
  "theme-dark",
  "bridge-connected",
  "bridge-disconnected",
  "data-empty",
  "data-error",
]);
const inventory = buildReleaseAccessibilitySurfaceInventory(
  JSON.parse(readFileSync(CONTRACT_URL, "utf8")),
);

for (const route of inventory.surfaces.browser_extension) {
  test(`WCAG 2.2 AA Browser Extension: ${route.routeId}`, async ({ page }, testInfo) => {
    const pageName = route.launchTarget.split("/").at(-1);
    if (!pageName) throw new Error("browser_extension_accessibility_target_invalid");
    const results = [];
    for (const stateId of STATES) {
      try {
        const evidence = await test.step(stateId, () =>
          runExtensionState(page, testInfo, route.routeId, pageName, stateId),
        );
        results.push({ stateId, status: "passed", evidence });
      } catch (error) {
        results.push({
          stateId,
          status: "failed",
          evidence: [`error:${error instanceof Error ? error.message : String(error)}`],
        });
      }
    }
    await testInfo.attach(`${route.routeId}-accessibility-state-results`, {
      body: JSON.stringify(results, null, 2),
      contentType: "application/json",
    });
    expect(results.filter(({ status }) => status === "failed")).toEqual([]);
  });
}

async function runExtensionState(page, testInfo, routeId, pageName, stateId) {
  await page.setViewportSize(
    stateId === "reflow-320"
      ? { width: 320, height: 720 }
      : stateId === "zoom-400"
        ? { width: ZOOM_400_VIEWPORT.width, height: ZOOM_400_VIEWPORT.height }
        : { width: 1280, height: 720 },
  );
  await page.emulateMedia({
    reducedMotion: stateId === "reduced-motion" ? "reduce" : "no-preference",
    forcedColors: stateId === "forced-colors" ? "active" : "none",
    colorScheme: stateId === "theme-dark" ? "dark" : "light",
  });
  await installExtensionApiFixture(page, stateId);
  const response = await page.goto(`/${pageName}`, { waitUntil: "domcontentloaded" });
  expect(response?.status()).toBeLessThan(400);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page).toHaveTitle(/MemStack/u);

  const evidence = [`surface:${routeId}`, `state:${stateId}`];
  if (stateId === "keyboard") {
    evidence.push(
      ...(await auditKeyboardTraversal(page, {
        allowNoFocusable: pageName === "options.html",
      })),
    );
  }
  if (stateId === "text-zoom-200") {
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    evidence.push("text-zoom:200%");
  }
  if (stateId === "zoom-400") {
    evidence.push(
      "zoom-factor:4",
      `reference-viewport:${ZOOM_400_VIEWPORT.referenceWidth}x${ZOOM_400_VIEWPORT.referenceHeight}`,
      `equivalent-css-viewport:${ZOOM_400_VIEWPORT.width}x${ZOOM_400_VIEWPORT.height}`,
    );
  }
  if (["text-zoom-200", "reflow-320", "zoom-400"].includes(stateId)) {
    const overflow = await page.evaluate(pageHorizontalOverflow);
    expect(overflow).toBeLessThanOrEqual(1);
    evidence.push(`horizontal-overflow:${overflow}`);
  }
  if (stateId === "bridge-connected" && pageName === "options.html") {
    await expect(page.locator("#connection-state")).toHaveText("connected");
  }
  if (stateId === "bridge-disconnected" && pageName === "options.html") {
    await expect(page.locator("#connection-state")).toHaveText("disconnected");
  }
  if (stateId === "data-empty" && pageName === "sidepanel.html") {
    await expect(page.locator("#conversation-picker option")).toHaveText("No conversations yet");
  }
  if (stateId === "data-error" && pageName === "sidepanel.html") {
    await expect(page.locator("#status")).toContainText("accessibility fixture unavailable");
  }
  evidence.push(...(await runAxeScan(page, testInfo, routeId, stateId)));
  return evidence;
}

async function installExtensionApiFixture(page, stateId) {
  await page.addInitScript((fixtureState) => {
    const connected = fixtureState === "bridge-connected";
    const failCalls = fixtureState === "data-error";
    const listeners = [];
    globalThis.chrome = {
      runtime: {
        id: "enbljdpbhdllbbkcjhccmbgpkfmcdkkl",
        sendMessage: async (message) => {
          if (failCalls) return { ok: false, error: "accessibility fixture unavailable" };
          if (message?.method === "sidepanel.listConversations") {
            return { ok: true, result: { conversations: [] } };
          }
          return { ok: true, result: {} };
        },
        onMessage: { addListener: (listener) => listeners.push(listener) },
      },
      storage: {
        local: {
          get: async () => ({
            memstackNativeStatus: {
              connected,
              lastConnectedAt: connected ? "2026-08-11T00:00:00.000Z" : null,
              lastError: connected ? null : "native_host_disconnected",
            },
          }),
        },
        onChanged: { addListener: (listener) => listeners.push(listener) },
      },
    };
  }, stateId);
}

function pageHorizontalOverflow() {
  const root = document.documentElement;
  const body = document.body;
  return Math.max(root.scrollWidth, body.scrollWidth) - Math.max(root.clientWidth, body.clientWidth);
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
    result.violations.map(({ id, impact, nodes }) => ({ id, impact, nodes: nodes.length })),
  ).toEqual([]);
  return [`axe:violations=0`, `axe:passes=${result.passes.length}`];
}
