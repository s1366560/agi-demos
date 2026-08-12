import { readFileSync, readdirSync } from 'node:fs';

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
  buildCanonicalAccessibilityDataContract,
  buildCanonicalAccessibilityRouteInventory,
  deriveZoomEquivalentViewport,
  materializeAccessibilityDataPath,
  materializeAccessibilityRoutePath,
} from '../../agi-stack/apps/desktop/contracts/accessibility/accessibility-automation-contract.mjs';
import { auditKeyboardTraversal } from '../../agi-stack/apps/desktop/contracts/accessibility/playwright-keyboard-audit.mjs';
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
const ZOOM_400_VIEWPORT = deriveZoomEquivalentViewport({ width: 1280, height: 720 }, 4);
const routeContract = JSON.parse(
  readFileSync(
    new URL(
      '../../agi-stack/apps/desktop/contracts/desktop-web-parity/web-route-inventory.v2.json',
      import.meta.url
    ),
    'utf8'
  )
);
const parityRoot = new URL(
  '../../agi-stack/apps/desktop/contracts/desktop-web-parity/',
  import.meta.url
);
const inventory = buildCanonicalAccessibilityRouteInventory(routeContract) as Readonly<{
  sourceRevision: string;
  routes: readonly AccessibilityRoute[];
}>;
const dataContractByRouteId = new Map(
  buildCanonicalAccessibilityDataContract(
    routeContract,
    readdirSync(parityRoot)
      .filter((name) => /^parity-capability-definitions\.\d{2}-.+\.v2\.json$/u.test(name))
      .sort()
      .map((name) => JSON.parse(readFileSync(new URL(name, parityRoot), 'utf8')))
  ).routes.map((contract) => [contract.routeId, contract])
);

let tenantId = '';
let projectId = '';
let adminAuthStorage: AuthStorage;
let memberAuthStorage: AuthStorage;

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
    workspaceId: 'accessibility-workspace',
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
  const prepare = (options: Parameters<typeof prepareWebRoute>[3] = {}): Promise<void> =>
    prepareWebRoute(page, path, route.routeId, options);
  const assessments: Record<string, () => Promise<string[]>> = {
    default: async () => {
      await prepare();
      return runAxeScan(page, testInfo, route.routeId, 'default');
    },
    keyboard: async () => {
      await prepare();
      await waitForWebKeyboardTarget(page);
      const keyboardEvidence = await auditKeyboardTraversal(page);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'keyboard');
      return [...keyboardEvidence, ...axeEvidence];
    },
    'text-zoom-200': async () => {
      await prepare();
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
      await prepare({ viewport: { width: 320, height: 720 } });
      const horizontalOverflow = await page.evaluate(pageHorizontalOverflow);
      expect(
        horizontalOverflow,
        'The route must reflow without page-level horizontal overflow at 320 CSS px'
      ).toBeLessThanOrEqual(1);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'reflow-320');
      return ['viewport:320x720', `horizontal-overflow:${horizontalOverflow}`, ...axeEvidence];
    },
    'zoom-400': async () => {
      await prepare({
        viewport: { width: ZOOM_400_VIEWPORT.width, height: ZOOM_400_VIEWPORT.height },
      });
      const horizontalOverflow = await page.evaluate(pageHorizontalOverflow);
      expect(
        horizontalOverflow,
        'The route must reflow without page-level horizontal overflow at the 400% zoom equivalent viewport'
      ).toBeLessThanOrEqual(1);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'zoom-400');
      return [
        'zoom-factor:4',
        `reference-viewport:${ZOOM_400_VIEWPORT.referenceWidth}x${ZOOM_400_VIEWPORT.referenceHeight}`,
        `equivalent-css-viewport:${ZOOM_400_VIEWPORT.width}x${ZOOM_400_VIEWPORT.height}`,
        `horizontal-overflow:${horizontalOverflow}`,
        ...axeEvidence,
      ];
    },
    'reduced-motion': async () => {
      await prepare({ reducedMotion: 'reduce' });
      expect(
        await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches),
        'Reduced-motion emulation must be active'
      ).toBe(true);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'reduced-motion');
      return ['media:prefers-reduced-motion=reduce', ...axeEvidence];
    },
    'forced-colors': async () => {
      await prepare({ forcedColors: 'active' });
      expect(
        await page.evaluate(() => matchMedia('(forced-colors: active)').matches),
        'Forced-colors emulation must be active'
      ).toBe(true);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'forced-colors');
      return ['media:forced-colors=active', ...axeEvidence];
    },
    'theme-light': async () => {
      await prepare({ theme: 'light' });
      expect(
        await page.locator('html').evaluate((element) => element.classList.contains('dark'))
      ).toBe(false);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'theme-light');
      return ['theme:light', ...axeEvidence];
    },
    'theme-dark': async () => {
      await prepare({ theme: 'dark' });
      expect(
        await page.locator('html').evaluate((element) => element.classList.contains('dark'))
      ).toBe(true);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'theme-dark');
      return ['theme:dark', ...axeEvidence];
    },
    'locale-en-US': async () => {
      await prepare({ locale: 'en-US' });
      await expect(page.locator('html')).toHaveAttribute('lang', /^en(?:-|$)/u);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'locale-en-US');
      return ['locale:en-US', ...axeEvidence];
    },
    'locale-zh-CN': async () => {
      await prepare({ locale: 'zh-CN' });
      await expect(page.locator('html')).toHaveAttribute('lang', /^zh(?:-|$)/u);
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'locale-zh-CN');
      return ['locale:zh-CN', ...axeEvidence];
    },
    'role-admin': async () => {
      await prepare({ authStorage: adminAuthStorage });
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'role-admin');
      return ['role:admin', ...axeEvidence];
    },
    'role-member': async () => {
      await prepare({ authStorage: memberAuthStorage });
      const axeEvidence = await runAxeScan(page, testInfo, route.routeId, 'role-member');
      return ['role:member', ...axeEvidence];
    },
    'data-loading': () => runInjectedDataState(page, testInfo, route, path, 'loading'),
    'data-empty': () => runInjectedDataState(page, testInfo, route, path, 'empty'),
    'data-forbidden': () => runInjectedDataState(page, testInfo, route, path, 'forbidden'),
    'data-error': () => runInjectedDataState(page, testInfo, route, path, 'error'),
    'data-conflict': () => runInjectedDataState(page, testInfo, route, path, 'conflict'),
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
  routeId: string,
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
  if (routeId === 'tenant-tenant-overview') {
    await expect(page.locator('[data-accessibility-route-ready="tenant-overview"]')).toBeVisible();
  }
  if (options.theme === 'dark') {
    await expect(page.locator('html')).toHaveClass(/dark/u);
  } else {
    await expect(page.locator('html')).not.toHaveClass(/dark/u);
  }
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

const tenantOverviewEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    storage: Object.freeze({ used: 0, total: 0, percentage: 0 }),
    projects: Object.freeze({ active: 0, new_this_week: 0, list: Object.freeze([]) }),
    members: Object.freeze({ total: 0, new_added: 0 }),
    memory_history: Object.freeze([]),
    tenant_info: Object.freeze({ organization_id: 'WCAG-EMPTY', plan: 'basic' }),
  }),
});

const agentWorkspaceEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ projects: Object.freeze([]), total: 0, page: 1, page_size: 100 }),
});

const tenantTasksEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    total: 0,
    pending: 0,
    processing: 0,
    running: 0,
    completed: 0,
    failed: 0,
    throughput_per_minute: 0,
    error_rate: 0,
  }),
});

const tenantBillingEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    tenant: Object.freeze({
      id: tenantId,
      name: 'WCAG Empty Tenant',
      plan: 'free',
      storage_limit: 10 * 1024 * 1024 * 1024,
    }),
    usage: Object.freeze({ projects: 0, memories: 0, users: 0, storage: 0 }),
    invoices: Object.freeze([]),
  }),
});

const tenantAnalyticsEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    summary: Object.freeze({ total_memories: 0, total_projects: 0, total_storage_bytes: 0 }),
    memoryGrowth: Object.freeze([]),
    projectStorage: Object.freeze([]),
  }),
});

const tenantAgentConfigurationEmptyResponse = Object.freeze({ status: 200, body: null });

const tenantAgentDefinitionsEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ definitions: Object.freeze([]), total: 0, limit: 20, offset: 0 }),
});

const tenantAgentBindingsEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze([]),
});

const tenantSkillsEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ skills: Object.freeze([]), total: 0 }),
});

const tenantEvolutionEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    stats: Object.freeze({
      total_sessions: 0,
      skill_sessions: 0,
      no_skill_sessions: 0,
      unprocessed_sessions: 0,
      processed_sessions: 0,
      scored_sessions: 0,
      successful_sessions: 0,
      avg_score: null,
      total_jobs: 0,
      pending_jobs: 0,
      applied_jobs: 0,
      skipped_jobs: 0,
      rejected_jobs: 0,
    }),
    monitor: Object.freeze({
      refresh_interval_seconds: 60,
      latest_session_at: null,
      latest_job_at: null,
      backlog_count: 0,
      unscored_count: 0,
      blocked_by_review_count: 0,
      eligible_skill_count: 0,
      needs_attention: false,
    }),
    stages: Object.freeze([]),
    skills: Object.freeze([]),
    recent_sessions: Object.freeze([]),
    recent_jobs: Object.freeze([]),
    trigger: Object.freeze({
      capture_hook: 'after_turn_complete',
      capture_timing: 'After each completed turn',
      scheduled_timing: 'Every 30 minutes',
      manual_trigger: 'Available',
      min_sessions_per_skill: 3,
      scoring_min_sessions_per_skill: 2,
      min_avg_score: 0.75,
      max_sessions_per_batch: 20,
      publish_mode: 'review',
      auto_apply: false,
      enabled: true,
    }),
  }),
});

const tenantPatternsEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ patterns: Object.freeze([]), total: 0, page: 1, page_size: 50 }),
});

const tenantPluginsEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ items: Object.freeze([]), diagnostics: Object.freeze([]) }),
});

const tenantMcpServersEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze([]),
});

const tenantTemplatesEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ templates: Object.freeze([]), total: 0 }),
});

const tenantProvidersEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze([]),
});

const tenantWebhooksEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze([]),
});

const tenantPoolEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    enabled: true,
    status: 'running',
    total_instances: 0,
    hot_instances: 0,
    warm_instances: 0,
    cold_instances: 0,
    ready_instances: 0,
    executing_instances: 0,
    unhealthy_instances: 0,
    prewarm_pool: null,
    resource_usage: null,
    resolved_scope: 'tenant',
    tenant_id: tenantId,
    reason_code: null,
  }),
});

const tenantInstancesEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    instances: Object.freeze([]),
    total: 0,
    page: 1,
    page_size: 20,
  }),
});

const tenantClustersEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    clusters: Object.freeze([]),
    total: 0,
    page: 1,
    page_size: 20,
  }),
});

const tenantInstanceTemplatesEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    templates: Object.freeze([]),
    total: 0,
    page: 1,
    page_size: 20,
  }),
});

const tenantGenesEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    genes: Object.freeze([]),
    total: 0,
    page: 1,
    page_size: 20,
  }),
});

const tenantUsersEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ members: Object.freeze([]), total: 0 }),
});

const tenantAuditLogsEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ items: Object.freeze([]), total: 0, limit: 20, offset: 0 }),
});

const tenantEventsEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({
    items: Object.freeze([]),
    total: 0,
    page: 1,
    page_size: 20,
    authority_revision: 0,
  }),
});

const tenantDeadLetterQueueEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ messages: Object.freeze([]), total: 0, limit: 20, offset: 0 }),
});

const tenantTrustPoliciesEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ items: Object.freeze([]) }),
});

const tenantDecisionRecordsEmptyResponse = Object.freeze({
  status: 200,
  body: Object.freeze({ items: Object.freeze([]) }),
});

function accessibilityProjectListResponse() {
  return Object.freeze({
    status: 200,
    body: Object.freeze({
      projects: Object.freeze([
        Object.freeze({
          id: projectId,
          tenant_id: tenantId,
          name: 'Accessibility project',
          description: 'Deterministic project scope for the canonical accessibility audit',
          owner_id: 'accessibility-owner',
          member_ids: Object.freeze([]),
          memory_rules: Object.freeze({
            max_episodes: 1000,
            retention_days: 30,
            auto_refresh: true,
            refresh_interval: 300,
          }),
          graph_config: Object.freeze({
            max_nodes: 500,
            max_edges: 1000,
            similarity_threshold: 0.8,
            community_detection: true,
          }),
          is_public: false,
          created_at: '2026-01-01T00:00:00Z',
        }),
      ]),
      total: 1,
      page: 1,
      page_size: 25,
      owner_ids: Object.freeze(['accessibility-owner']),
    }),
  });
}

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
  route: AccessibilityRoute,
  path: string,
  state: DataState
): Promise<string[]> {
  const dataStatePath =
    route.routeId === 'agent-workspace-tenant-agent-workspace' ? path.split('?', 1)[0] : path;
  await resetAccessibilityEmulation(page);
  await applyWebRuntimeState(page, {
    authStorage: adminAuthStorage,
    locale: 'en-US',
    theme: 'light',
  });
  const dataContract = webDataStateContract(route);
  const expectedEndpoint = dataContract.path;
  let injectedRequests = 0;
  const pendingRoutes: Route[] = [];
  const requestSequence: Array<Readonly<{ method: string; pathname: string; action: string }>> = [];
  const handler = async (intercepted: Route) => {
    const request = intercepted.request();
    const pathname = new URL(request.url()).pathname;
    if (
      route.routeId === 'tenant-tenant-workspaces' &&
      request.method() === 'GET' &&
      pathname === '/api/v1/projects/'
    ) {
      requestSequence.push({ method: request.method(), pathname, action: 'fixture:project-scope' });
      const response = accessibilityProjectListResponse();
      await intercepted.fulfill({
        status: response.status,
        contentType: 'application/json',
        body: JSON.stringify(response.body),
      });
      return;
    }
    const eligible = request.method() === dataContract.method && pathname === expectedEndpoint;
    if (!eligible) {
      requestSequence.push({ method: request.method(), pathname, action: 'continued' });
      await intercepted.continue();
      return;
    }
    injectedRequests += 1;
    if (state === 'loading') {
      requestSequence.push({ method: request.method(), pathname, action: 'held' });
      pendingRoutes.push(intercepted);
      return;
    }
    requestSequence.push({ method: request.method(), pathname, action: `fulfilled:${state}` });
    const response = webDataStateResponseForRoute(route.routeId, state);
    await intercepted.fulfill({
      status: response.status,
      contentType: 'application/json',
      body: JSON.stringify(response.body),
    });
  };
  await page.route('**/api/v1/**', handler);
  try {
    const response = await page.goto(dataStatePath, { waitUntil: 'domcontentloaded' });
    expect(response, 'Canonical route navigation must receive an HTTP response').not.toBeNull();
    expect(response?.status(), 'Canonical route response must be below 400').toBeLessThan(400);
    await page.locator('#root').waitFor({ state: 'attached' });
    await triggerWebDataStateRequest(page, route.routeId, dataContract);
    await expect.poll(() => injectedRequests, { timeout: 10_000 }).toBeGreaterThan(0);
    await expect(
      page.locator(dataStateSelectors[state]).filter({ visible: true }).first(),
      `The route must expose a semantic ${state} state after deterministic API injection`
    ).toBeVisible();
    const stateId = `data-${state}`;
    const axeEvidence = await runAxeScan(page, testInfo, route.routeId, stateId);
    await testInfo.attach(`${route.routeId}-${stateId}-request-sequence`, {
      body: JSON.stringify(requestSequence, null, 2),
      contentType: 'application/json',
    });
    return [
      `network-state:${state}`,
      `endpoint:${expectedEndpoint}`,
      `injected-requests:${injectedRequests}`,
      ...axeEvidence,
    ];
  } finally {
    await Promise.all(
      pendingRoutes.map((pending) =>
        pending.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(webDataStateResponseForRoute(route.routeId, 'empty').body),
        })
      )
    );
    await page.unroute('**/api/v1/**', handler);
  }
}

function webDataStateContract(route: AccessibilityRoute) {
  if (route.routeId === 'agent-workspace-tenant-agent-workspace') {
    return Object.freeze({
      method: 'GET',
      path: '/api/v1/projects/',
      injectionTrigger: 'route-open',
    });
  }
  if (
    route.routeId === 'tenant-tenant-org-settings' ||
    route.routeId === 'tenant-tenant-settings'
  ) {
    return Object.freeze({
      method: 'GET',
      path: `/api/v1/tenants/${tenantId}/stats`,
      injectionTrigger: 'route-open',
    });
  }
  if (route.routeId === 'project-blackboard-dynamic-project-blackboard') {
    return Object.freeze({
      method: 'GET',
      path: `/api/v1/tenants/${tenantId}/projects/${projectId}/workspaces`,
      injectionTrigger: 'route-open',
    });
  }
  const contract = dataContractByRouteId.get(route.routeId);
  if (!contract) throw new Error(`accessibility_data_contract_missing:${route.routeId}`);
  if (contract.method === 'WS') {
    throw new Error(`accessibility_web_data_contract_transport_invalid:${route.routeId}`);
  }
  return Object.freeze({
    method: contract.method,
    path: materializeAccessibilityDataPath(contract, {
      tenantId,
      projectId,
      workspaceId: 'accessibility-workspace',
    }),
    injectionTrigger: contract.injectionTrigger ?? 'route-open',
  });
}

function webDataStateResponseForRoute(routeId: string, state: DataState) {
  if (state !== 'empty') return dataStateResponse[state];
  if (routeId === 'tenant-tenant-overview') return tenantOverviewEmptyResponse;
  if (
    routeId === 'agent-workspace-tenant-agent-workspace' ||
    routeId === 'tenant-tenant-projects'
  ) {
    return agentWorkspaceEmptyResponse;
  }
  if (routeId === 'tenant-tenant-tasks') return tenantTasksEmptyResponse;
  if (routeId === 'tenant-tenant-analytics') return tenantAnalyticsEmptyResponse;
  if (routeId === 'tenant-tenant-billing') return tenantBillingEmptyResponse;
  if (routeId === 'tenant-tenant-agent-configuration') {
    return tenantAgentConfigurationEmptyResponse;
  }
  if (routeId === 'tenant-tenant-agent-definitions') return tenantAgentDefinitionsEmptyResponse;
  if (routeId === 'tenant-tenant-agent-bindings') return tenantAgentBindingsEmptyResponse;
  if (routeId === 'tenant-tenant-skills') return tenantSkillsEmptyResponse;
  if (routeId === 'tenant-tenant-evolution') return tenantEvolutionEmptyResponse;
  if (routeId === 'tenant-tenant-patterns') return tenantPatternsEmptyResponse;
  if (routeId === 'tenant-tenant-plugins') return tenantPluginsEmptyResponse;
  if (routeId === 'tenant-tenant-mcp-servers') return tenantMcpServersEmptyResponse;
  if (routeId === 'tenant-tenant-templates') return tenantTemplatesEmptyResponse;
  if (routeId === 'tenant-tenant-providers') return tenantProvidersEmptyResponse;
  if (routeId === 'tenant-tenant-webhooks') return tenantWebhooksEmptyResponse;
  if (routeId === 'tenant-tenant-pool') return tenantPoolEmptyResponse;
  if (routeId === 'tenant-tenant-instances') return tenantInstancesEmptyResponse;
  if (routeId === 'tenant-tenant-clusters') return tenantClustersEmptyResponse;
  if (routeId === 'tenant-tenant-instance-templates') {
    return tenantInstanceTemplatesEmptyResponse;
  }
  if (routeId === 'tenant-tenant-genes') return tenantGenesEmptyResponse;
  if (routeId === 'tenant-tenant-users') return tenantUsersEmptyResponse;
  if (routeId === 'tenant-tenant-audit-logs') return tenantAuditLogsEmptyResponse;
  if (routeId === 'tenant-tenant-events') return tenantEventsEmptyResponse;
  if (routeId === 'tenant-tenant-dead-letter-queue') {
    return tenantDeadLetterQueueEmptyResponse;
  }
  if (routeId === 'tenant-tenant-trust-policies') return tenantTrustPoliciesEmptyResponse;
  if (routeId === 'tenant-tenant-decision-records') return tenantDecisionRecordsEmptyResponse;
  if (routeId === 'project-blackboard-dynamic-project-blackboard') {
    return Object.freeze({ status: 200, body: Object.freeze([]) });
  }
  if (routeId === 'project-project-memories') {
    return Object.freeze({
      status: 200,
      body: Object.freeze({ memories: Object.freeze([]), total: 0, page: 1, page_size: 20 }),
    });
  }
  if (routeId === 'project-project-schema') {
    return Object.freeze({ status: 200, body: Object.freeze([]) });
  }
  if (routeId === 'project-project-maintenance') {
    return Object.freeze({
      status: 200,
      body: Object.freeze({
        stats: Object.freeze({ entities: 0, episodes: 0, communities: 0, old_episodes: 0 }),
        recommendations: Object.freeze([]),
        last_checked: '2026-01-01T00:00:00Z',
      }),
    });
  }
  if (routeId === 'project-project-settings') {
    return Object.freeze({
      status: 404,
      body: Object.freeze({ detail: 'accessibility_fixture_project_not_found' }),
    });
  }
  if (routeId === 'project-agent-dashboard' || routeId === 'project-agent-logs') {
    return Object.freeze({
      status: 200,
      body: Object.freeze({ project_id: projectId, runs: Object.freeze([]), total: 0 }),
    });
  }
  if (routeId === 'project-agent-patterns') {
    return Object.freeze({
      status: 200,
      body: Object.freeze({
        project_id: projectId,
        tenant_id: tenantId,
        scope_kind: 'tenant_shared',
        patterns: Object.freeze([]),
        total: 0,
        page: 1,
        page_size: 50,
      }),
    });
  }
  return dataStateResponse.empty;
}

async function triggerWebDataStateRequest(
  page: Page,
  routeId: string,
  dataContract: Readonly<{ method: string; path: string; injectionTrigger: string }>
) {
  if (dataContract.injectionTrigger === 'route-open') return;
  if (dataContract.injectionTrigger === 'search-submit') {
    const query = page.getByRole('searchbox', { name: /search query/i });
    const submit = page.getByRole('button', { name: /^retrieve$/i });
    await expect(query, 'The Web Search route must expose its query input').toBeVisible();
    await query.fill('accessibility deterministic search');
    await expect(submit, 'The Web Search route must expose its submit action').toBeVisible();
    await submit.click();
    return;
  }
  if (dataContract.injectionTrigger === 'workspace-collaboration-refresh') {
    const refresh = page
      .locator('button')
      .filter({ hasText: /refresh/i })
      .first();
    await expect(
      refresh,
      'The Web collaboration route must expose its refresh action'
    ).toBeVisible();
    await refresh.click();
    return;
  }
  throw new Error(
    `accessibility_web_data_injection_trigger_invalid:${routeId}:${dataContract.injectionTrigger}`
  );
}

async function waitForWebKeyboardTarget(page: Page) {
  const selector =
    "a[href],button:not([disabled]),input:not([disabled]):not([type='hidden'])," +
    "select:not([disabled]),textarea:not([disabled]),summary,[contenteditable='true']," +
    "[tabindex]:not([tabindex='-1'])";
  await expect
    .poll(
      () =>
        page.locator(selector).evaluateAll(
          (elements) =>
            elements.filter((element) => {
              const htmlElement = element as HTMLElement;
              const style = getComputedStyle(htmlElement);
              const rect = htmlElement.getBoundingClientRect();
              return (
                htmlElement.tabIndex >= 0 &&
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                rect.width > 0 &&
                rect.height > 0
              );
            }).length
        ),
      { timeout: 10_000 }
    )
    .toBeGreaterThan(0);
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
  await expect(page.locator('html')).toHaveClass(/app-ready/u);
  await expect(page.locator('[data-app-initializer-state="loading"]')).toHaveCount(0);
  expect(new URL(page.url()).pathname, 'Canonical route must not redirect to login').not.toBe(
    '/login'
  );
  await expect(
    page.locator('.ant-result-404'),
    'Canonical route must not render Ant Design 404'
  ).toHaveCount(0);
}

async function runAxeScan(page: Page, testInfo: TestInfo, routeId: string, stateId: string) {
  let builder = new AxeBuilder({ page }).withTags(WCAG_TAGS);
  const forcedColors = stateId === 'forced-colors';
  if (forcedColors) {
    builder = builder.disableRules(['color-contrast']);
  }
  const result = await builder.analyze();
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
  return [
    `axe:violations=0`,
    `axe:passes=${result.passes.length}`,
    forcedColors ? 'axe:color-contrast=disabled-for-forced-colors' : 'axe:color-contrast=enabled',
  ];
}
