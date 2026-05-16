/* eslint-disable react-hooks/rules-of-hooks */
import fs from 'fs';
import path from 'path';

import { test as base } from '@playwright/test';

export const API_BASE = process.env.API_BASE || 'http://localhost:8000';
const HEALTH_URL = `${API_BASE}/health`;
let didHealthcheck = false;
let didNormalizeUsers = false;
let didCleanup = false;
const createdProjectIds = new Set<string>();

async function waitForHealth() {
  const deadline = Date.now() + 60_000;
  let lastErr: any;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(HEALTH_URL, { method: 'GET' });
      if (res.ok) return true;
    } catch (e) {
      lastErr = e;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  if (lastErr) throw lastErr;
  throw new Error('Backend healthcheck timeout');
}

export async function fetchAuthToken(email: string, password: string): Promise<string | null> {
  const form = new URLSearchParams();
  form.append('username', email);
  form.append('password', password);
  const tokenResp = await fetch(`${API_BASE}/api/v1/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
  });
  if (!tokenResp.ok) return null;
  const tokenJson = await tokenResp.json();
  return tokenJson.access_token ?? null;
}

export async function getAdminAuthToken(): Promise<string> {
  const token = await fetchAuthToken('admin@memstack.ai', 'adminpassword');
  if (!token) {
    throw new Error('Unable to authenticate admin test user');
  }
  return token;
}

async function getCurrentUser(token: string): Promise<Record<string, unknown>> {
  const userResp = await fetch(`${API_BASE}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!userResp.ok) {
    throw new Error(`Unable to load current user: ${String(userResp.status)}`);
  }
  const userJson = await userResp.json();
  return {
    id: userJson.user_id,
    email: userJson.email,
    name: userJson.name,
    roles: userJson.roles,
    is_active: userJson.is_active,
    created_at: userJson.created_at,
    profile: userJson.profile,
    preferred_language: userJson.preferred_language ?? 'en-US',
  };
}

export async function getFirstTenantId(token?: string): Promise<string> {
  const authToken = token ?? (await getAdminAuthToken());
  const tenantsResp = await fetch(`${API_BASE}/api/v1/tenants/`, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!tenantsResp.ok) {
    throw new Error(`Unable to load tenants: ${String(tenantsResp.status)}`);
  }
  const tenantsJson = await tenantsResp.json();
  const tenantId = tenantsJson.tenants?.[0]?.id ?? tenantsJson[0]?.id;
  if (!tenantId) {
    throw new Error('No tenant available for E2E test setup');
  }
  return tenantId;
}

export async function createTestProject({
  name,
  description = 'Playwright E2E project',
  tenantId,
  token,
}: {
  name: string;
  description?: string;
  tenantId?: string;
  token?: string;
}): Promise<{ id: string; tenantId: string }> {
  const authToken = token ?? (await getAdminAuthToken());
  const resolvedTenantId = tenantId ?? (await getFirstTenantId(authToken));
  const createResp = await fetch(`${API_BASE}/api/v1/projects/`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${authToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      name,
      description,
      tenant_id: resolvedTenantId,
      is_public: false,
    }),
  });
  const text = await createResp.text();
  if (!createResp.ok) {
    throw new Error(`Unable to create project: ${String(createResp.status)} ${text}`);
  }
  const projectJson = JSON.parse(text);
  const id = projectJson.project?.id ?? projectJson.id;
  if (!id) {
    throw new Error(`Project response did not include id: ${text}`);
  }
  createdProjectIds.add(id);
  return { id, tenantId: resolvedTenantId };
}

export async function createTestMemory({
  projectId,
  title,
  content,
  token,
  tags = [],
}: {
  projectId: string;
  title: string;
  content: string;
  token?: string;
  tags?: string[];
}): Promise<{ id: string }> {
  const authToken = token ?? (await getAdminAuthToken());
  const memoryResp = await fetch(`${API_BASE}/api/v1/memories/`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${authToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      project_id: projectId,
      title,
      content,
      content_type: 'text',
      tags,
    }),
  });
  const text = await memoryResp.text();
  if (!memoryResp.ok) {
    throw new Error(`Unable to create memory: ${String(memoryResp.status)} ${text}`);
  }
  const memoryJson = JSON.parse(text);
  return { id: memoryJson.id };
}

export function tenantProjectPath(tenantId: string, projectId: string, path = ''): string {
  const suffix = path ? `/${path.replace(/^\/+/, '')}` : '';
  return `/tenant/${tenantId}/project/${projectId}${suffix}`;
}

export function agentWorkspacePath(projectId: string): string {
  return `/tenant/agent-workspace?projectId=${encodeURIComponent(projectId)}`;
}

export async function loginAsAdmin(page: import('@playwright/test').Page): Promise<void> {
  const token = await getAdminAuthToken();
  const user = await getCurrentUser(token);
  const authStorage = {
    state: {
      user,
      token,
      isAuthenticated: true,
    },
    version: 0,
  };

  await page.addInitScript((storage) => {
    window.localStorage.setItem('memstack-auth-storage', JSON.stringify(storage));
    window.localStorage.setItem('i18nextLng', 'en-US');
    window.localStorage.setItem('memstack_onboarding_complete', 'true');
  }, authStorage);

  await page.goto('/');
  await page.evaluate((storage) => {
    window.localStorage.setItem('memstack-auth-storage', JSON.stringify(storage));
    window.localStorage.setItem('i18nextLng', 'en-US');
    window.localStorage.setItem('memstack_onboarding_complete', 'true');
  }, authStorage);
}

async function normalizeTestUserPreferences() {
  if (didNormalizeUsers) return;

  const users = [
    { email: 'admin@memstack.ai', password: 'adminpassword' },
    { email: 'user@memstack.ai', password: 'userpassword' },
  ];

  for (const user of users) {
    const token = await fetchAuthToken(user.email, user.password);
    if (!token) continue;
    await fetch(`${API_BASE}/api/v1/users/me`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ preferred_language: 'en-US' }),
    }).catch(() => {});
  }

  didNormalizeUsers = true;
}

async function primeBrowserState(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    if (!window.localStorage.getItem('i18nextLng')) {
      window.localStorage.setItem('i18nextLng', 'en-US');
    }
    window.localStorage.setItem('memstack_onboarding_complete', 'true');
  });
}

async function stopAgentRunIfVisible(page: import('@playwright/test').Page) {
  try {
    const stopButton = page.getByRole('button', { name: /Stop/i });
    if (await stopButton.isVisible({ timeout: 750 }).catch(() => false)) {
      await stopButton.click();
      await page
        .getByTestId('send-button')
        .isVisible({ timeout: 10_000 })
        .catch(() => false);
    }
  } catch {
    // Best-effort cleanup only; individual tests own their assertions.
  }
}

export const test = base.extend({
  page: async ({ page }, use) => {
    if (!didHealthcheck) {
      await waitForHealth();
      didHealthcheck = true;
    }
    await normalizeTestUserPreferences();
    await primeBrowserState(page);
    await use(page);
    await stopAgentRunIfVisible(page);

    // Collect coverage from window.__coverage__
    const coverage = await page.evaluate(() => (window as any).__coverage__);
    if (coverage) {
      const dir = path.join(process.cwd(), '.nyc_output');
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

      // Save with a unique name
      const filename = `coverage-${Date.now()}-${Math.floor(Math.random() * 10000)}.json`;
      fs.writeFileSync(path.join(dir, filename), JSON.stringify(coverage));
    }
  },
});

export { expect } from '@playwright/test';

// Cleanup test data via API
base.afterAll(async () => {
  if (didCleanup) return;
  didCleanup = true;
  if (createdProjectIds.size === 0) return;

  try {
    // login and get token
    const token = await fetchAuthToken('admin@memstack.ai', 'adminpassword');
    if (!token) return;
    const authHeaders = { Authorization: `Bearer ${token}` };

    for (const projectId of createdProjectIds) {
      await fetch(`${API_BASE}/api/v1/projects/${projectId}`, {
        method: 'DELETE',
        headers: authHeaders,
      }).catch(() => {});
    }
  } catch (_) {
    // ignore
  }
});
