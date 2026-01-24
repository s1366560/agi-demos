/* eslint-disable react-hooks/rules-of-hooks */
import { test as base } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const API_BASE = process.env.API_BASE || 'http://localhost:8000';
const HEALTH_URL = `${API_BASE}/health`;
let didHealthcheck = false;
let didCleanup = false;
const TEST_NAME_PATTERNS = [
  'Test Project',
  'Entities Test Project',
  'Communities Test',
  'Maintenance Test Project',
  'Playwright E2E Test',
];

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
    await new Promise(r => setTimeout(r, 1500));
  }
  if (lastErr) throw lastErr;
  throw new Error('Backend healthcheck timeout');
}

export const test = base.extend({
  page: async ({ page }, use) => {
    if (!didHealthcheck) {
      await waitForHealth();
      didHealthcheck = true;
    }
    await use(page);

    // Collect coverage from window.__coverage__
    const coverage = await page.evaluate(() => (window as any).__coverage__);
    if (coverage) {
      const dir = path.join(process.cwd(), '.nyc_output');
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

      // Save with a unique name
      const filename = `coverage-${Date.now()}-${Math.floor(Math.random() * 10000)}.json`;
      fs.writeFileSync(
        path.join(dir, filename),
        JSON.stringify(coverage)
      );
    }
  },
});

export { expect } from '@playwright/test';

// Cleanup test data via API
base.afterAll(async () => {
  if (didCleanup) return;
  try {
    // login and get token
    const form = new URLSearchParams();
    form.append('username', 'admin@memstack.ai');
    form.append('password', 'adminpassword');
    const tokenResp = await fetch(`${API_BASE}/api/v1/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form.toString(),
    });
    if (!tokenResp.ok) return;
    const tokenJson = await tokenResp.json();
    const authHeaders = { Authorization: `Bearer ${tokenJson.access_token}` };

    // list projects and delete matching names
    const listResp = await fetch(`${API_BASE}/api/v1/projects/?page_size=200`, {
      headers: authHeaders,
    });
    if (!listResp.ok) return;
    const listJson = await listResp.json();
    const projects = listJson.projects || [];
    for (const p of projects) {
      const name: string = p.name || '';
      if (TEST_NAME_PATTERNS.some(pattern => name.includes(pattern))) {
        await fetch(`${API_BASE}/api/v1/projects/${p.id}`, {
          method: 'DELETE',
          headers: authHeaders,
        }).catch(() => {});
      }
    }
  } catch (_) {
    // ignore
  }
  didCleanup = true;
});
