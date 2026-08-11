import { readFileSync } from 'node:fs';

import AxeBuilder from '@axe-core/playwright';
import type { Page, Route, TestInfo } from '@playwright/test';

import {
  API_BASE,
  createTestProject,
  fetchAuthToken,
  getAdminAuthToken,
  test,
  expect,
} from './base';

import {
  REQUIRED_ACCESSIBILITY_STATES,
  assertCompleteAccessibilityRouteResults,
  buildCanonicalAccessibilityRouteInventory,
  materializeAccessibilityRoutePath,
} from '../../agi-stack/apps/desktop/contracts/accessibility/accessibility-automation-contract.mjs';
type AccessibilityRoute = Readonly<{
  routeId: string;
  pathTemplate: string;
  contexts: readonly string[];
}>;

type AccessibilityStateResult = {
  stateId: string;
  status: 'passed' | 'failed';
  evidence: string[];
};

type AuthStorage = Readonly<{
  state: Readonly<{
    user: Record<string, unknown>;
    token: string;
    isAuthenticated: true;
  }>;
  version: 0;
}>;

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const routeContract = JSON.parse(
  readFileSync(
    new URL(
      '../../agi-stack/apps/desktop/contracts/desktop-web-parity/web-route-inventory.v2.json',
      import.meta.url
    ),
    'utf8'
  )
);
const inventory = buildCanonicalAccessibilityRouteInventory(routeContract) as Readonly<{
  sourceRevision: string;
  routes: readonly AccessibilityRoute[];
}>;

let tenantId = '';
let projectId = '';
let adminAuthStorage: AuthStorage;
let memberAuthStorage: AuthStorage;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  const token = await getAdminAuthToken();
  adminAuthStorage = await authStorageForToken(token);
  const memberToken = await fetchAuthToken('user@memstack.ai', 'userpassword');
  if (!memberToken) throw new Error('Unable to authenticate member accessibility fixture');
  memberAuthStorage = await authStorageForToken(memberToken);
  const project = await createTestProject({
    name: `WCAG 2.2 AA route audit ${Date.now()}`,
    description: `Canonical route audit for ${inventory.sourceRevision}`,
    token,
  });
  tenantId = project.tenantId;
  projectId = project.id;
});

for (const route of inventory.routes) {
  test(`WCAG 2.2 AA canonical route: ${route.routeId}`, async ({ page }, testInfo) => {
    const path = webRoutePath(route, tenantId, projectId);
    const results = await runAccessibilityStates(page, testInfo, route, path);

    assertCompleteAccessibilityRouteResults(
      { sourceRevision: inventory.sourceRevision, routes: [route] },
      [{ routeId: route.routeId, states: results }]
    );
    await testInfo.attach(`${route.routeId}-accessibility-state-results`, {
      body: JSON.stringify(results, null, 2),
      contentType: 'application/json',
    });
    expect(
      results.filter(({ status }) => status === 'failed'),
      `Every required accessibility state must pass for ${route.routeId}`
    ).toEqual([]);
  });
}

function webRoutePath(route: AccessibilityRoute, scopeTenantId: string, scopeProjectId: string) {
  const path = materializeAccessibilityRoutePath(route, {
    tenantId: scopeTenantId,
    projectId: scopeProjectId,
  });
  if (route.routeId === 'agent-workspace-tenant-agent-workspace') {
    return `${path}?projectId=${encodeURIComponent(scopeProjectId)}`;
  }
  return path;
}

async function runAccessibilityStates(
  page: Page,
  testInfo: TestInfo,
  route: AccessibilityRoute,
  path: string
): Promise<AccessibilityStateResult[]> {
  const assessments: Record<string, () => Promise<string[]>> = {
    default: async () => {
      await prepareWebRoute(page, path);
      return runAxeScan(page, testInfo, route.routeId, 'default');
    },
    keyboard: async () => {
      await prepareWebRoute(page, path);
      await page.keyboard.press('Tab');
      const focus = await page.evaluate(() => ({
        tagName: document.activeElement?.tagName ?? '',
        attached: Boolean(document.activeElement && document.contains(document.activeElement)),
      }));
      expect(focus.attached, 'Tab focus must stay in the document').toBe(true);
      expect(['BODY', 'HTML'], 'Tab focus must move to an interactive element').not.toContain(
        focus.tagName
      );
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'keyboard');
      return [`focus:${focus.tagName}`, ...axeEvidence];
    },
    'text-zoom-200': async () => {
      await prepareWebRoute(page, path);
      const zoomAudit = await page.evaluate(() => {
        document.documentElement.style.fontSize = '200%';
        const root = document.documentElement;
        const body = document.body;
        return {
          fontSize: document.documentElement.style.fontSize,
          horizontalOverflow:
            Math.max(root.scrollWidth, body.scrollWidth) -
            Math.max(root.clientWidth, body.clientWidth),
        };
      });
      expect(zoomAudit.fontSize, 'The 200% text zoom state must be applied').toBe('200%');
      expect(
        zoomAudit.horizontalOverflow,
        'The route must reflow without page-level horizontal overflow at 200% text zoom'
      ).toBeLessThanOrEqual(1);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'text-zoom-200');
      return [
        'text-zoom:200%',
        `horizontal-overflow:${zoomAudit.horizontalOverflow}`,
        ...axeEvidence,
      ];
    },
    'reflow-320': async () => {
      await prepareWebRoute(page, path, { viewport: { width: 320, height: 720 } });
      const horizontalOverflow = await page.evaluate(pageHorizontalOverflow);
      expect(
        horizontalOverflow,
        'The route must reflow without page-level horizontal overflow at 320 CSS px'
      ).toBeLessThanOrEqual(1);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'reflow-320');
      return ['viewport:320x720', `horizontal-overflow:${horizontalOverflow}`, ...axeEvidence];
    },
    'zoom-400': async () => {
      await prepareWebRoute(page, path);
      const zoomAudit = await page.evaluate(() => {
        document.documentElement.style.zoom = '4';
        const root = document.documentElement;
        const body = document.body;
        return {
          zoom: document.documentElement.style.zoom,
          horizontalOverflow:
            Math.max(root.scrollWidth, body.scrollWidth) -
            Math.max(root.clientWidth, body.clientWidth),
        };
      });
      expect(zoomAudit.zoom, 'The 400% zoom state must be applied').toBe('4');
      expect(
        zoomAudit.horizontalOverflow,
        'The route must reflow without page-level horizontal overflow at 400% zoom'
      ).toBeLessThanOrEqual(1);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'zoom-400');
      return ['css-zoom:4', `horizontal-overflow:${zoomAudit.horizontalOverflow}`, ...axeEvidence];
    },
    'reduced-motion': async () => {
      await prepareWebRoute(page, path, { reducedMotion: 'reduce' });
      expect(
        await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches),
        'Reduced-motion emulation must be active'
      ).toBe(true);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'reduced-motion');
      return ['media:prefers-reduced-motion=reduce', ...axeEvidence];
    },
    'forced-colors': async () => {
      await prepareWebRoute(page, path, { forcedColors: 'active' });
      expect(
        await page.evaluate(() => matchMedia('(forced-colors: active)').matches),
        'Forced-colors emulation must be active'
      ).toBe(true);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'forced-colors');
      return ['media:forced-colors=active', ...axeEvidence];
    },
    'theme-light': async () => {
      await prepareWebRoute(page, path, { theme: 'light' });
      expect(
        await page.locator('html').evaluate((element) => element.classList.contains('dark'))
      ).toBe(false);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'theme-light');
      return ['theme:light', ...axeEvidence];
    },
    'theme-dark': async () => {
      await prepareWebRoute(page, path, { theme: 'dark' });
      expect(
        await page.locator('html').evaluate((element) => element.classList.contains('dark'))
      ).toBe(true);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'theme-dark');
      return ['theme:dark', ...axeEvidence];
    },
    'locale-en-US': async () => {
      await prepareWebRoute(page, path, { locale: 'en-US' });
      await expect(page.locator('html')).toHaveAttribute('lang', /^en(?:-|$)/u);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'locale-en-US');
      return ['locale:en-US', ...axeEvidence];
    },
    'locale-zh-CN': async () => {
      await prepareWebRoute(page, path, { locale: 'zh-CN' });
      await expect(page.locator('html')).toHaveAttribute('lang', /^zh(?:-|$)/u);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'locale-zh-CN');
      return ['locale:zh-CN', ...axeEvidence];
    },
    'role-admin': async () => {
      await prepareWebRoute(page, path, { authStorage: adminAuthStorage });
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'role-admin');
      return ['role:admin', ...axeEvidence];
    },
    'role-member': async () => {
      await prepareWebRoute(page, path, { authStorage: memberAuthStorage });
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'role-member');
      return ['role:member', ...axeEvidence];
    },
    'data-loading': () => runInjectedDataState(page, testInfo, route.routeId, path, 'loading'),
    'data-empty': () => runInjectedDataState(page, testInfo, route.routeId, path, 'empty'),
    'data-forbidden': () => runInjectedDataState(page, testInfo, route.routeId, path, 'forbidden'),
    'data-error': () => runInjectedDataState(page, testInfo, route.routeId, path, 'error'),
    'data-conflict': () => runInjectedDataState(page, testInfo, route.routeId, path, 'conflict'),
  };

  const results: AccessibilityStateResult[] = [];
  for (const stateId of REQUIRED_ACCESSIBILITY_STATES as readonly string[]) {
    try {
      const evidence = await test.step(stateId, () => assessments[stateId]());
      results.push({ stateId, status: 'passed', evidence });
    } catch (error) {
      results.push({
        stateId,
        status: 'failed',
        evidence: [`error:${error instanceof Error ? error.message : String(error)}`],
      });
    }
  }
  return results;
}

async function resetAccessibilityEmulation(
  page: Page,
  media: {
    reducedMotion?: 'reduce';
    forcedColors?: 'active';
    viewport?: Readonly<{ width: number; height: number }>;
  } = {}
) {
  if (page.url() === 'about:blank') {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
  }
  await page.emulateMedia({
    reducedMotion: media.reducedMotion ?? 'no-preference',
    forcedColors: media.forcedColors ?? 'none',
  });
  await page.setViewportSize(media.viewport ?? { width: 1280, height: 720 });
  await page.evaluate(() => {
    document.documentElement.style.removeProperty('font-size');
    document.documentElement.style.removeProperty('zoom');
  });
}

async function prepareWebRoute(
  page: Page,
  path: string,
  options: Readonly<{
    authStorage?: AuthStorage;
    forcedColors?: 'active';
    locale?: 'en-US' | 'zh-CN';
    reducedMotion?: 'reduce';
    theme?: 'light' | 'dark';
    viewport?: Readonly<{ width: number; height: number }>;
  }> = {}
) {
  await resetAccessibilityEmulation(page, options);
  await applyWebRuntimeState(page, {
    authStorage: options.authStorage ?? adminAuthStorage,
    locale: options.locale ?? 'en-US',
    theme: options.theme ?? 'light',
  });
  await assertWebRouteReached(page, path);
}

async function applyWebRuntimeState(
  page: Page,
  state: Readonly<{
    authStorage: AuthStorage;
    locale: 'en-US' | 'zh-CN';
    theme: 'light' | 'dark';
  }>
) {
  await page.evaluate(({ authStorage, locale, theme }) => {
    window.localStorage.setItem('memstack-auth-storage', JSON.stringify(authStorage));
    window.localStorage.setItem('i18nextLng', locale);
    window.localStorage.setItem(
      'theme-storage',
      JSON.stringify({ state: { theme, computedTheme: theme }, version: 0 })
    );
    window.localStorage.setItem('memstack_onboarding_complete', 'true');
  }, state);
}

type DataState = 'loading' | 'empty' | 'forbidden' | 'error' | 'conflict';

const dataStateResponse = Object.freeze({
  empty: Object.freeze({ status: 200, body: { data: [], items: [], results: [], total: 0 } }),
  forbidden: Object.freeze({ status: 403, body: { detail: 'accessibility_fixture_forbidden' } }),
  error: Object.freeze({ status: 500, body: { detail: 'accessibility_fixture_error' } }),
  conflict: Object.freeze({ status: 409, body: { detail: 'accessibility_fixture_conflict' } }),
});

const dataStateSelectors: Readonly<Record<DataState, string>> = Object.freeze({
  loading: '[aria-busy="true"], [role="status"], [data-state="loading"], .ant-spin',
  empty: '[data-state="empty"], [role="status"], .ant-empty',
  forbidden: '[data-state="forbidden"], [role="alert"], .ant-result-403',
  error: '[data-state="error"], [role="alert"], .ant-result-error',
  conflict: '[data-state="conflict"], [role="alert"]',
});

async function runInjectedDataState(
  page: Page,
  testInfo: TestInfo,
  routeId: string,
  path: string,
  state: DataState
): Promise<string[]> {
  await resetAccessibilityEmulation(page);
  await applyWebRuntimeState(page, {
    authStorage: adminAuthStorage,
    locale: 'en-US',
    theme: 'light',
  });
  let injectedRequests = 0;
  const pendingRoutes: Route[] = [];
  const handler = async (intercepted: Route) => {
    const request = intercepted.request();
    const pathname = new URL(request.url()).pathname;
    const eligible =
      request.method() === 'GET' &&
      pathname.startsWith('/api/v1/') &&
      !pathname.startsWith('/api/v1/auth/') &&
      pathname !== '/api/v1/users/me';
    if (!eligible || injectedRequests > 0) {
      await intercepted.continue();
      return;
    }
    injectedRequests += 1;
    if (state === 'loading') {
      pendingRoutes.push(intercepted);
      return;
    }
    const response = dataStateResponse[state];
    await intercepted.fulfill({
      status: response.status,
      contentType: 'application/json',
      body: JSON.stringify(response.body),
    });
  };
  await page.route('**/api/v1/**', handler);
  try {
    const response = await page.goto(path, { waitUntil: 'domcontentloaded' });
    expect(response, 'Canonical route navigation must receive an HTTP response').not.toBeNull();
    expect(response?.status(), 'Canonical route response must be below 400').toBeLessThan(400);
    await page.locator('#root').waitFor({ state: 'attached' });
    await expect.poll(() => injectedRequests, { timeout: 10_000 }).toBeGreaterThan(0);
    await expect(
      page.locator(dataStateSelectors[state]).first(),
      `The route must expose a semantic ${state} state after deterministic API injection`
    ).toBeVisible();
    const stateId = `data-${state}`;
    const axeEvidence = await runAxeScan(page, testInfo, routeId, stateId);
    return [`network-state:${state}`, `injected-requests:${injectedRequests}`, ...axeEvidence];
  } finally {
    await Promise.all(
      pendingRoutes.map((pending) =>
        pending.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(dataStateResponse.empty.body),
        })
      )
    );
    await page.unroute('**/api/v1/**', handler);
  }
}

async function authStorageForToken(token: string): Promise<AuthStorage> {
  const response = await fetch(`${API_BASE}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`Unable to load accessibility user: ${response.status}`);
  const user = (await response.json()) as Record<string, unknown>;
  return Object.freeze({
    state: Object.freeze({
      user: {
        id: user.user_id,
        email: user.email,
        name: user.name,
        roles: user.roles,
        is_active: user.is_active,
        created_at: user.created_at,
        profile: user.profile,
        preferred_language: user.preferred_language ?? 'en-US',
      },
      token,
      isAuthenticated: true,
    }),
    version: 0,
  });
}

function pageHorizontalOverflow() {
  const root = document.documentElement;
  const body = document.body;
  return (
    Math.max(root.scrollWidth, body.scrollWidth) - Math.max(root.clientWidth, body.clientWidth)
  );
}

async function assertWebRouteReached(page: Page, path: string) {
  const response = await page.goto(path, { waitUntil: 'domcontentloaded' });
  expect(response, 'Canonical route navigation must receive an HTTP response').not.toBeNull();
  expect(response?.status(), 'Canonical route response must be below 400').toBeLessThan(400);
  await page.locator('#root').waitFor({ state: 'attached' });
  await page.waitForFunction(() => Boolean(document.querySelector('#root')?.firstElementChild));
  expect(new URL(page.url()).pathname, 'Canonical route must not redirect to login').not.toBe(
    '/login'
  );
  await expect(
    page.locator('.ant-result-404'),
    'Canonical route must not render Ant Design 404'
  ).toHaveCount(0);
}

async function runAxeScan(page: Page, testInfo: TestInfo, routeId: string, stateId: string) {
  const result = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  if (result.violations.length > 0) {
    await testInfo.attach(`${routeId}-${stateId}-axe-violations`, {
      body: JSON.stringify(result.violations, null, 2),
      contentType: 'application/json',
    });
  }
  expect(
    result.violations.map(({ id, impact, nodes }) => ({ id, impact, nodes: nodes.length })),
    `Axe WCAG A/AA violations for ${routeId} in ${stateId}`
  ).toEqual([]);
  return [`axe:violations=0`, `axe:passes=${result.passes.length}`];
}
